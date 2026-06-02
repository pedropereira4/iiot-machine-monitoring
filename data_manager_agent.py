import json
import os
import socket
import base64
import sys
from datetime import datetime
from dotenv import load_dotenv
from paho.mqtt.client import Client, CallbackAPIVersion
from influxdb_client import InfluxDBClient, Point, WriteOptions

load_dotenv()

if len(sys.argv) < 2:
    print("Uso: python data_manager_agent.py <GroupID>")
    sys.exit(1)
GROUP_ID = sys.argv[1]
MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883
MACHINE_IDS = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"]

INFLUX_TOKEN = os.getenv("INFLUX_TOKEN")
INFLUX_ORG = "b2dce2c3f25d6d00"
INFLUX_BUCKET = "SRSA"
INFLUX_URL = "https://eu-central-1-1.aws.cloud2.influxdata.com"

UDP_IP = "127.0.0.1"
UDP_PORT_AM_TO_DMA = 5006

PARAMS_TO_BYTE_CODE = {
    "rpm": 0x01,
    "consumption": 0x02,
    "coolant_temperature": 0x03,
    "oil_pressure": 0x04,
    "battery_potential": 0x05
}

BASE_UNITS = {
    "rpm": "rpm",
    "coolant_temperature": "°C",
    "oil_pressure": "bar",
    "battery_potential": "V",
    "consumption": "l/h"
}

MACHINE_ORIGINAL_UNITS = {
    "A23X": {"rpm": "rpm", "oil_pressure": "psi", "coolant_temperature": "°C", "battery_potential": "V", "consumption": "l/h"},
    "B47Y": {"rpm": "rpm", "oil_pressure": "bar", "coolant_temperature": "°C", "battery_potential": "V", "consumption": "gal/h"},
    "C89Z": {"rpm": "rpm", "oil_pressure": "psi", "coolant_temperature": "°C", "battery_potential": "V", "consumption": "gal/h"},
    "D56W": {"rpm": "rpm", "oil_pressure": "bar", "coolant_temperature": "°C", "battery_potential": "V", "consumption": "l/h"},
    "E34V": {"rpm": "rpm", "oil_pressure": "psi", "coolant_temperature": "°F", "battery_potential": "V", "consumption": "gal/h"},
    "F78T": {"rpm": "rpm", "oil_pressure": "bar", "coolant_temperature": "°F", "battery_potential": "V", "consumption": "l/h"},
    "G92Q": {"rpm": "rpm", "oil_pressure": "psi", "coolant_temperature": "°F", "battery_potential": "V", "consumption": "l/h"},
    "H65P": {"rpm": "rpm", "oil_pressure": "bar", "coolant_temperature": "°F", "battery_potential": "mV", "consumption": "gal/h"}
}

# Shared globals used by MQTT callbacks — initialised inside main()
write_api = None
influx_client = None


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------

def convert_to_base_unit(value, param_name, original_unit):
    target_base_unit = BASE_UNITS.get(param_name)
    if original_unit == target_base_unit:
        return float(value)
    try:
        val = float(value)
        if param_name == "oil_pressure" and original_unit == "psi" and target_base_unit == "bar":
            return val / 14.5038
        elif param_name == "coolant_temperature" and original_unit == "°F" and target_base_unit == "°C":
            return (val - 32) * 5 / 9
        elif param_name == "battery_potential" and original_unit == "mV" and target_base_unit == "V":
            return val / 1000
        elif param_name == "consumption" and original_unit == "gal/h" and target_base_unit == "l/h":
            return val / 0.264172
        else:
            print(f"[AVISO CONVERSÃO] Sem regra para {param_name} de {original_unit} para {target_base_unit}. Usando valor original.")
            return val
    except ValueError:
        print(f"[ERRO CONVERSÃO] Não foi possível converter '{value}' para float para o parâmetro {param_name}.")
        return None


def topic_up(machine_id):
    return f"v3/{GROUP_ID}@ttn/devices/{machine_id}/up"


def encode_control_command(param_name, adjustment_value):
    param_byte = PARAMS_TO_BYTE_CODE.get(param_name)
    if param_byte is None:
        print(f"[AVISO DMA] Parâmetro desconhecido para codificação de comando: {param_name}")
        return None
    adj_byte_val = adjustment_value if adjustment_value >= 0 else 256 + adjustment_value
    command_bytes = bytes([0x01, 0x01, param_byte, adj_byte_val])
    return base64.b64encode(command_bytes).decode('utf-8')


def encode_alert_command(action_type, reason_code=0x01):
    if action_type == 0x01:
        command_bytes = bytes([0x02, 0x01, reason_code])
    elif action_type == 0x02:
        command_bytes = bytes([0x02, 0x02, 0x00])
    else:
        print(f"[ERRO DMA] Tipo de ação de alerta desconhecido: {action_type}")
        return None
    return base64.b64encode(command_bytes).decode('utf-8')


# ---------------------------------------------------------------------------
# MQTT callbacks
# ---------------------------------------------------------------------------

def on_machine_data(client, userdata, msg):
    try:
        payload_str = msg.payload.decode()
        payload = json.loads(payload_str)

        received_machine_id = payload['end_device_ids']['machine_id']
        decoded_payload_original = payload['uplink_message']['decoded_payload']
        machine_code = decoded_payload_original.get("machine_type")
        timestamp = payload.get("received_at", datetime.utcnow().isoformat())

        snr_value = None
        rssi_value = None
        channel_rssi_value = None
        if ('uplink_message' in payload
                and 'rx_metadata' in payload['uplink_message']
                and payload['uplink_message']['rx_metadata']):
            rx_meta = payload['uplink_message']['rx_metadata'][0]
            if 'rssi' in rx_meta:
                rssi_value = float(rx_meta['rssi'])
            if 'snr' in rx_meta:
                snr_value = float(rx_meta['snr'])
            if 'channel_rssi' in rx_meta:
                channel_rssi_value = float(rx_meta['channel_rssi'])

        print(f"[DEBUG DMA] RSSI: {rssi_value}, SNR: {snr_value}, ChRSSI: {channel_rssi_value} para {received_machine_id}")

        if not machine_code or machine_code not in MACHINE_ORIGINAL_UNITS:
            print(f"[ERRO] Machine_code '{machine_code}' desconhecido ou ausente no payload de {received_machine_id}.")
            return

        original_units_config = MACHINE_ORIGINAL_UNITS[machine_code]
        converted_sensors = {}
        status_from_machine = "UNKNOWN"

        for key, original_value in decoded_payload_original.items():
            if key == "machine_type":
                converted_sensors[key] = original_value
                continue
            if key == "status":
                status_from_machine = str(original_value)
                converted_sensors[key] = status_from_machine
                continue
            original_unit = original_units_config.get(key)
            if original_unit and key in BASE_UNITS:
                converted_value = convert_to_base_unit(original_value, key, original_unit)
                converted_sensors[key] = round(converted_value, 4) if converted_value is not None else original_value
            else:
                converted_sensors[key] = float(original_value) if isinstance(original_value, (int, float)) else original_value

        final_sensor_data = {}
        for k, v in converted_sensors.items():
            if k in ("machine_type", "status"):
                final_sensor_data[k] = v
            elif isinstance(v, (int, float)):
                final_sensor_data[k] = float(v)

        internal_topic = f"{GROUP_ID}/internal/{received_machine_id}"
        internal_payload = {
            "group": GROUP_ID,
            "machine": received_machine_id,
            "timestamp": timestamp,
            "sensors": final_sensor_data
        }
        client.publish(internal_topic, json.dumps(internal_payload))

        point = (
            Point("machine_data")
            .tag("machine_id", received_machine_id)
            .tag("machine_code", machine_code)
            .field("status", status_from_machine)
            .time(timestamp)
        )
        if rssi_value is not None:
            point = point.field("rssi", rssi_value)
        if snr_value is not None:
            point = point.field("snr", snr_value)
        if channel_rssi_value is not None:
            point = point.field("channel_rssi", channel_rssi_value)
        for key, value in final_sensor_data.items():
            if key not in ("machine_type", "status") and isinstance(value, (int, float)):
                point = point.field(key, float(value))

        write_api.write(bucket=INFLUX_BUCKET, record=point)
        print(f"[INFLUXDB] Ponto escrito para {received_machine_id} (Status: {status_from_machine})")

    except json.JSONDecodeError:
        print(f"[ERRO MQTT JSON] Payload não é JSON válido: {msg.payload.decode(errors='ignore')}")
    except KeyError as e:
        print(f"[ERRO MQTT KEY] Chave em falta no payload MQTT: {e}")
    except Exception as e:
        print(f"[ERRO GERAL DMA] Em on_machine_data: {e} - Payload: {msg.payload.decode(errors='ignore')}")


def on_mdm_control_command(client, userdata, msg):
    try:
        payload_str = msg.payload.decode()
        command_data = json.loads(payload_str)
        current_timestamp_iso = datetime.utcnow().isoformat()
        print(f"[DEBUG DMA] Recebido comando de controlo do MDM: {command_data}")

        machine_id = msg.topic.split('/')[-1]
        action = command_data.get("action")
        param_to_modify = command_data.get("parameter")
        adj_value = command_data.get("value")

        if action == "adjust_parameter" and param_to_modify and adj_value is not None:
            frm_payload_encoded = encode_control_command(param_to_modify, adj_value)
            if frm_payload_encoded:
                downlink_topic = f"v3/{GROUP_ID}@ttn/devices/{machine_id}/down/push_machine"
                downlink_msg = {"downlinks": [{"frm_payload": frm_payload_encoded, "f_port": 10, "priority": "NORMAL"}]}
                client.publish(downlink_topic, json.dumps(downlink_msg))
                print(f"[DMA->MÁQUINA] Ajuste {param_to_modify}={adj_value} para {machine_id} em {downlink_topic}")
                try:
                    control_event_point = (
                        Point("control_log")
                        .tag("machine_id", machine_id)
                        .field("command_type", "control_mdm")
                        .field("parameter_modified", param_to_modify)
                        .field("adjustment_value", float(adj_value))
                        .field("frm_payload_sent", frm_payload_encoded)
                        .time(current_timestamp_iso)
                    )
                    write_api.write(bucket=INFLUX_BUCKET, record=control_event_point)
                    print(f"[INFLUXDB LOG] Evento de controlo (MDM) para {machine_id} registado.")
                except Exception as e_influx_log:
                    print(f"[ERRO INFLUXDB LOG] Falha ao registar evento de controlo (MDM): {e_influx_log}")
            else:
                print(f"[ERRO DMA] Falha ao codificar comando de ajuste para {machine_id}, param {param_to_modify}")
        else:
            print(f"[AVISO DMA] Comando de controlo do MDM mal formado ou incompleto: {command_data}")

    except json.JSONDecodeError:
        print(f"[ERRO DMA JSON] Payload de comando do MDM não é JSON válido: {msg.payload.decode(errors='ignore')}")
    except Exception as e:
        print(f"[ERRO GERAL DMA] Em on_mdm_control_command: {e} - Payload: {msg.payload.decode(errors='ignore')}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global influx_client, write_api

    if not INFLUX_TOKEN:
        print("[ERRO CRÍTICO] INFLUX_TOKEN não definido. Cria .env com INFLUX_TOKEN=<token>")
        sys.exit(1)

    influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = influx_client.write_api(write_options=WriteOptions(batch_size=1))

    dma_udp_receiver_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        dma_udp_receiver_sock.bind((UDP_IP, UDP_PORT_AM_TO_DMA))
        dma_udp_receiver_sock.settimeout(1.0)
        print(f"[INFO DMA] À escuta de comandos do Alert Manager em UDP {UDP_IP}:{UDP_PORT_AM_TO_DMA}")
    except Exception as e:
        print(f"[ERRO DMA] Não foi possível ligar o socket UDP para o Alert Manager: {e}")

    mqttc = Client(CallbackAPIVersion.VERSION2)
    mqttc.message_callback_add(f"v3/{GROUP_ID}@ttn/devices/+/up", on_machine_data)
    mqttc.message_callback_add(f"{GROUP_ID}/control_commands/mdm_to_dma/+", on_mdm_control_command)

    try:
        mqttc.connect(MQTT_BROKER, MQTT_PORT, 60)
        print(f"[INFO DMA] Conectado ao Broker MQTT {MQTT_BROKER}:{MQTT_PORT}")

        for machine_id_to_sub in MACHINE_IDS:
            mqttc.subscribe(topic_up(machine_id_to_sub))
            print(f"[DMA MQTT] Subscrito a dados de máquina: {topic_up(machine_id_to_sub)}")

        mdm_control_topic_pattern = f"{GROUP_ID}/control_commands/mdm_to_dma/+"
        mqttc.subscribe(mdm_control_topic_pattern)
        print(f"[DMA MQTT] Subscrito a comandos de controlo do MDM: {mdm_control_topic_pattern}")
        print("[INFO DMA] Data Manager Agent pronto e à escuta de mensagens MQTT e UDP...")

        while True:
            mqttc.loop(timeout=0.1)

            try:
                udp_data, udp_addr = dma_udp_receiver_sock.recvfrom(1024)
                if not udp_data:
                    continue
                current_timestamp_iso_alert = datetime.utcnow().isoformat()
                print(f"[DMA UDP RECEBIDO de AM {udp_addr}] {udp_data.decode()}")
                try:
                    am_command = json.loads(udp_data.decode())
                    machine_id_am = am_command.get("machine_id")
                    command_type_am = am_command.get("type")
                    action_am = am_command.get("action")
                    reason_code_from_am = am_command.get("reason_code")

                    if machine_id_am and command_type_am == "alert":
                        alert_action_type_byte = 0x00
                        effective_reason_code_byte = 0x00
                        frm_payload_alert_encoded = None

                        if action_am == "stop":
                            alert_action_type_byte = 0x01
                            effective_reason_code_byte = reason_code_from_am if reason_code_from_am is not None else 0x01
                            frm_payload_alert_encoded = encode_alert_command(alert_action_type_byte, effective_reason_code_byte)
                        elif action_am == "danger_reduce":
                            alert_action_type_byte = 0x02
                            effective_reason_code_byte = reason_code_from_am if reason_code_from_am is not None else 0x00
                            frm_payload_alert_encoded = encode_alert_command(alert_action_type_byte, effective_reason_code_byte)

                        if frm_payload_alert_encoded:
                            alert_downlink_topic = f"v3/{GROUP_ID}@ttn/devices/{machine_id_am}/down/push_alert"
                            alert_downlink_msg = {"downlinks": [{"frm_payload": frm_payload_alert_encoded, "f_port": 1, "priority": "NORMAL"}]}
                            mqttc.publish(alert_downlink_topic, json.dumps(alert_downlink_msg))
                            print(f"[DMA->MÁQUINA via AM] Alerta '{action_am}' para {machine_id_am} enviado em {alert_downlink_topic}")
                            try:
                                alert_event_point = (
                                    Point("alert_log")
                                    .tag("machine_id", machine_id_am)
                                    .field("command_type", "alert_am")
                                    .field("action_commanded", action_am)
                                    .field("action_byte_sent", alert_action_type_byte)
                                    .field("reason_code_byte_sent", effective_reason_code_byte)
                                    .field("frm_payload_sent", frm_payload_alert_encoded)
                                    .time(current_timestamp_iso_alert)
                                )
                                if reason_code_from_am is not None:
                                    alert_event_point = alert_event_point.field("reason_code_received_am", int(reason_code_from_am))
                                write_api.write(bucket=INFLUX_BUCKET, record=alert_event_point)
                                print(f"[INFLUXDB LOG] Evento de alerta (AM) para {machine_id_am} registado.")
                            except Exception as e_influx_log_alert:
                                print(f"[ERRO INFLUXDB LOG] Falha ao registar evento de alerta (AM): {e_influx_log_alert}")
                        else:
                            print(f"[ERRO DMA] Falha ao codificar alerta do AM para {machine_id_am}")
                    else:
                        print(f"[AVISO DMA] Comando UDP do AM mal formado: {am_command}")

                except json.JSONDecodeError:
                    print(f"[ERRO DMA UDP JSON] Payload UDP do AM não é JSON: {udp_data.decode()}")
                except Exception as e_udp_proc:
                    print(f"[ERRO DMA] Ao processar comando UDP do AM: {e_udp_proc}")

            except socket.timeout:
                pass
            except Exception as e_udp_sock:
                print(f"[ERRO DMA] No socket UDP de escuta do AM: {e_udp_sock}")

    except KeyboardInterrupt:
        print("\n[INFO DMA] Data Manager Agent a ser desligado...")
    except Exception as e:
        print(f"[ERRO CRÍTICO] No Data Manager Agent: {e}")
    finally:
        print("[INFO] A limpar recursos do Data Manager Agent...")
        if mqttc.is_connected():
            mqttc.loop_stop(force=False)
            mqttc.disconnect()
            print("[INFO] Cliente MQTT do Data Manager Agent desconectado.")
        if write_api:
            write_api.close()
            print("[INFO] Cliente InfluxDB Write API fechado.")
        if influx_client:
            influx_client.close()
            print("[INFO] Cliente InfluxDB fechado.")
        dma_udp_receiver_sock.close()
        print("[INFO DMA] Socket UDP de escuta do AM fechado.")
        print("[INFO] Data Manager Agent desligado.")


if __name__ == "__main__":
    main()

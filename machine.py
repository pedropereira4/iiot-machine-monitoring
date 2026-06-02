import json
import random
import time
import sys
from datetime import datetime
import paho.mqtt.client as mqtt
import base64 


if len(sys.argv) != 4:
    print("Uso: python3 machine.py <GroupID> <UpdateTime> <MachineCode>")
    sys.exit(1)

GROUP_ID = sys.argv[1]
UPDATE_TIME = int(sys.argv[2])
MACHINE_CODE = sys.argv[3]

MACHINE_DEFINITIONS = {
    "A23X": {"id": "M1", "units": {"rpm": "rpm", "oil_pressure": "psi", "coolant_temperature": "°C", "battery_potential": "V", "consumption": "l/h"}},
    "B47Y": {"id": "M2", "units": {"rpm": "rpm", "oil_pressure": "bar", "coolant_temperature": "°C", "battery_potential": "V", "consumption": "gal/h"}},
    "C89Z": {"id": "M3", "units": {"rpm": "rpm", "oil_pressure": "psi", "coolant_temperature": "°C", "battery_potential": "V", "consumption": "gal/h"}},
    "D56W": {"id": "M4", "units": {"rpm": "rpm", "oil_pressure": "bar", "coolant_temperature": "°C", "battery_potential": "V", "consumption": "l/h"}},
    "E34V": {"id": "M5", "units": {"rpm": "rpm", "oil_pressure": "psi", "coolant_temperature": "°F", "battery_potential": "V", "consumption": "gal/h"}},
    "F78T": {"id": "M6", "units": {"rpm": "rpm", "oil_pressure": "bar", "coolant_temperature": "°F", "battery_potential": "V", "consumption": "l/h"}},
    "G92Q": {"id": "M7", "units": {"rpm": "rpm", "oil_pressure": "psi", "coolant_temperature": "°F", "battery_potential": "V", "consumption": "l/h"}},
    "H65P": {"id": "M8", "units": {"rpm": "rpm", "oil_pressure": "bar", "coolant_temperature": "°F", "battery_potential": "mV", "consumption": "gal/h"}}
}

current_machine_def = MACHINE_DEFINITIONS.get(MACHINE_CODE)

if not current_machine_def:
    print(f"Erro: MachineCode {MACHINE_CODE} é inválido.")
    sys.exit(1)

MACHINE_ID = current_machine_def["id"]

MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883

topic_up = f"v3/{GROUP_ID}@ttn/devices/{MACHINE_ID}/up"
topic_down_machine = f"v3/{GROUP_ID}@ttn/devices/{MACHINE_ID}/down/push_machine"
topic_down_alert = f"v3/{GROUP_ID}@ttn/devices/{MACHINE_ID}/down/push_alert"

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

MACHINE_DEV_ADDRS = {
    "M1": "260B0001", "M2": "260B0002", "M3": "260B0003", "M4": "260B0004",
    "M5": "260B0005", "M6": "260B0006", "M7": "260B0007", "M8": "260B0008"
}

f_counter = 0
IS_SHUTDOWN = False

IS_IN_DANGER_MODE = False
DANGER_MODE_END_TIME = 0
DANGER_MODE_DURATION_SECONDS = 0 


machine_state = {
    "rpm": {"value": random.uniform(1500, 2000), "min_op": 800, "max_op": 3000, "delta_range": (-50, 200)},
    "coolant_temperature": {"value": random.uniform(80, 90), "min_op": 70.0, "max_op": 130.0, "delta_range": (-0.3, 1.0)}, 
    "oil_pressure": {"value": random.uniform(3, 5), "min_op": 1.5, "max_op": 8.0, "delta_range": (-0.1, 0.5)}, 
    "battery_potential": {"value": random.uniform(11, 13), "min_op": 10.0, "max_op": 14.0, "delta_range": (-0.1, 0.2)},
    "consumption": {"value": random.uniform(10, 20), "min_op": 1.0, "max_op": 50.0, "delta_range": (-1.0, 1.0)}, 
    # Parâmetros LoRaWAN
    "rssi": {"value": random.uniform(-100, -60), "min_op": -120, "max_op": -50, "delta_range": (-3, 3)},
    "snr": {"value": random.uniform(-10, 5), "min_op": -20, "max_op": 10, "delta_range": (-0.5, 0.5)},
    "channel_rssi": {"value": random.uniform(-100, -60), "min_op": -120, "max_op": -50, "delta_range": (-3, 3)}
}

def update_parameters():
    global IS_SHUTDOWN, machine_state, IS_IN_DANGER_MODE, DANGER_MODE_END_TIME

    if IS_SHUTDOWN:
        
        machine_state["oil_pressure"]["value"] *= 0.8 
        machine_state["battery_potential"]["value"] *= 0.9 
        
        
        
        if machine_state["coolant_temperature"]["value"] > 20:
            machine_state["coolant_temperature"]["value"] -= 5 
        else:
            machine_state["coolant_temperature"]["value"] *= 0.95 
        
        machine_state["coolant_temperature"]["value"] = max(0, machine_state["coolant_temperature"]["value"])
        machine_state["oil_pressure"]["value"] = max(0, machine_state["oil_pressure"]["value"])
        machine_state["battery_potential"]["value"] = max(0, machine_state["battery_potential"]["value"])

        
        temp_check_c = machine_state["coolant_temperature"]["value"] < 20
        
        if current_machine_def["units"]["coolant_temperature"] == "°F":
            temp_in_f = (machine_state["coolant_temperature"]["value"] * 9/5) + 32
            temp_check_f = temp_in_f < 68
            if not temp_check_f: 
                 pass 
            else: 
                 if machine_state["rpm"]["value"] == 0 and \
                   machine_state["oil_pressure"]["value"] < 0.1 and \
                   machine_state["consumption"]["value"] == 0:
                    print("[REINÍCIO] Condições de reinício atingidas (temp em F). A reiniciar máquina...")
                    IS_SHUTDOWN = False
                    
                    machine_state["rpm"]["value"] = random.uniform(1500, 2000)
                    machine_state["coolant_temperature"]["value"] = random.uniform(80, 100) 
                    machine_state["oil_pressure"]["value"] = random.uniform(3, 6) 
                    machine_state["battery_potential"]["value"] = random.uniform(11, 13) 
                    machine_state["consumption"]["value"] = random.uniform(10, 30)   
                    return 

        elif temp_check_c: 
            if machine_state["rpm"]["value"] == 0 and \
               machine_state["oil_pressure"]["value"] < 0.1 and \
               machine_state["consumption"]["value"] == 0:
                print("[REINÍCIO] Condições de reinício atingidas (temp em C). A reiniciar máquina...")
                IS_SHUTDOWN = False
                machine_state["rpm"]["value"] = random.uniform(1500, 2000)
                machine_state["coolant_temperature"]["value"] = random.uniform(80, 100)
                machine_state["oil_pressure"]["value"] = random.uniform(3, 6)
                machine_state["battery_potential"]["value"] = random.uniform(11, 13)
                machine_state["consumption"]["value"] = random.uniform(10, 30)
                return
        
        for key in ["oil_pressure", "battery_potential", "coolant_temperature"]:
             machine_state[key]["value"] = round(machine_state[key]["value"], 2)

    elif IS_IN_DANGER_MODE and not IS_SHUTDOWN: 
        print(f"[DANGER MODE] Máquina {MACHINE_ID} em modo de perigo.")
        if time.time() >= DANGER_MODE_END_TIME:
            print(f"[DANGER MODE] Fim do modo de perigo para {MACHINE_ID}.")
            IS_IN_DANGER_MODE = False
            
        else:
                        
            machine_state["rpm"]["value"] *= 0.95 
            machine_state["rpm"]["value"] = max(machine_state["rpm"]["min_op"], machine_state["rpm"]["value"])
            
            machine_state["consumption"]["value"] *= 0.90
            machine_state["consumption"]["value"] = max(machine_state["consumption"]["min_op"], machine_state["consumption"]["value"])

            
            for key in ["coolant_temperature", "oil_pressure", "battery_potential"]:
                params = machine_state[key]
                
                delta_variation = random.uniform(params["delta_range"][0] * 0.2, params["delta_range"][1] * 0.2)
                bias = -abs(params["delta_range"][0] + params["delta_range"][1]) / 10 
                
                params["value"] += (delta_variation + bias) * 0.5 
                params["value"] = max(params["min_op"], min(params["value"], params["max_op"]))
            
            print(f"[DANGER MODE] Valores ajustados: RPM={machine_state['rpm']['value']:.0f}, Cons={machine_state['consumption']['value']:.1f}")

            
            for key in machine_state:
                if key not in ["rssi", "snr", "channel_rssi"] and "value" in machine_state[key]:
                    if key == "rpm": machine_state[key]["value"] = round(machine_state[key]["value"], 0)
                    else: machine_state[key]["value"] = round(machine_state[key]["value"], 2)

    else: 
        for key, params in machine_state.items():
            if key in ["rpm", "coolant_temperature", "oil_pressure", "battery_potential", "consumption", "rssi", "snr", "channel_rssi"]:
                delta = random.uniform(params["delta_range"][0], params["delta_range"][1])
                params["value"] += delta
                params["value"] = max(params["min_op"], min(params["value"], params["max_op"]))
                
                if key not in ["rssi", "channel_rssi"]:
                    params["value"] = round(params["value"], 2)
                elif key == "snr":
                    params["value"] = round(params["value"], 1)
                else: 
                    params["value"] = round(params["value"])

def get_converted_value(param_name, base_value):
    target_unit = current_machine_def["units"].get(param_name)
    
    if param_name == "coolant_temperature": 
        if target_unit == "°F":
            return round((base_value * 9/5) + 32, 2)
    elif param_name == "oil_pressure": 
        if target_unit == "psi":
            return round(base_value * 14.5038, 2)
    elif param_name == "battery_potential": 
        if target_unit == "mV":
            return round(base_value * 1000, 2)
    elif param_name == "consumption": 
        if target_unit == "gal/h":
            return round(base_value * 0.264172, 2)
    
    
    
    if param_name in ["rpm", "coolant_temperature", "oil_pressure", "battery_potential", "consumption"]:
        return round(base_value, 2)
    return base_value

def generate_payload():
    global f_counter
    f_counter += 1
    update_parameters()

    
    current_machine_status_string = "OPERATIONAL"
    if IS_SHUTDOWN:
        current_machine_status_string = "SHUTDOWN"
    elif IS_IN_DANGER_MODE:
        current_machine_status_string = "DANGER"

    decoded_payload = {
        "rpm": get_converted_value("rpm", machine_state["rpm"]["value"]),
        "coolant_temperature": get_converted_value("coolant_temperature", machine_state["coolant_temperature"]["value"]),
        "oil_pressure": get_converted_value("oil_pressure", machine_state["oil_pressure"]["value"]),
        "battery_potential": get_converted_value("battery_potential", machine_state["battery_potential"]["value"]),
        "consumption": get_converted_value("consumption", machine_state["consumption"]["value"]),
        "machine_type": MACHINE_CODE,
        "status": current_machine_status_string 
    }

    return {
        "end_device_ids": {
            "machine_id": MACHINE_ID,
            "application_id": "srsa_app",
            "dev_eui": f"70B3D57ED003{MACHINE_ID[1:].zfill(4)}C5",
            "join_eui": "0000000000000000",
            "dev_addr": MACHINE_DEV_ADDRS.get(MACHINE_ID, "260B0000")
        },
        "received_at": datetime.utcnow().isoformat() + "Z",
        "uplink_message": {
            "f_port": 1,
            "f_cnt": f_counter,
            "frm_payload": "BASE64_ENCODED_PAYLOAD", 
            "decoded_payload": decoded_payload,
            "rx_metadata": [{
                "gateway_id": "gateway-1",
                "rssi": machine_state["rssi"]["value"],
                "snr": machine_state["snr"]["value"],
                "channel_rssi": machine_state["channel_rssi"]["value"],
                "uplink_token": "TOKEN_VALUE_EXAMPLE" 
            }],
            "settings": {
                "data_rate": {
                    "modulation": "LORA",
                    "bandwidth": 125000,
                    "spreading_factor": 7
                },
                "frequency": "868300000",
                "timestamp": int(time.time()) 
            },
            "consumed_airtime": "0.061696s" 
        }
    }


def process_control_command(payload_bytes):
    global machine_state
    print(f"[CMD CTRL] Bytes recebidos: {payload_bytes}")
    if len(payload_bytes) == 4:
        msg_type = payload_bytes[0]
        action_type = payload_bytes[1]
        param_to_modify_code = payload_bytes[2]
        adjustment_value = int.from_bytes([payload_bytes[3]], byteorder='big', signed=True)

        print(f"[CMD CTRL] Descodificado: TipoMsg={hex(msg_type)}, Ação={hex(action_type)}, ParamCode={hex(param_to_modify_code)}, Ajuste={adjustment_value}")

        if msg_type == 0x01 and action_type == 0x01: 
            param_map = {0x01: "rpm", 0x02: "consumption", 0x03: "coolant_temperature", 0x04: "oil_pressure", 0x05: "battery_potential"}
            param_key = param_map.get(param_to_modify_code)

            if param_key:
                
                                                                                                                          
                print(f"[CMD CTRL] A ajustar {param_key} por {adjustment_value}")
                machine_state[param_key]["value"] += adjustment_value 
                
                if param_key != "rpm":
                    machine_state["rpm"]["value"] -= abs(adjustment_value) * 10 
                    machine_state["rpm"]["value"] = max(machine_state["rpm"]["min_op"], machine_state["rpm"]["value"])

                
                machine_state[param_key]["value"] = max(machine_state[param_key]["min_op"], 
                                                      min(machine_state[param_key]["value"], machine_state[param_key]["max_op"]))
                print(f"[CMD CTRL] Novo valor de {param_key}: {machine_state[param_key]['value']:.2f}")
            else:
                print(f"[CMD CTRL] Código de parâmetro desconhecido: {hex(param_to_modify_code)}")
        else:
            print(f"[CMD CTRL] Tipo de mensagem/ação de controlo não suportado: {hex(msg_type)}/{hex(action_type)}")
    else:
        print(f"[CMD CTRL] Payload de controlo com tamanho inesperado: {len(payload_bytes)} bytes")

def process_alert_command(frm_payload_bytes):
    global IS_SHUTDOWN, IS_IN_DANGER_MODE, DANGER_MODE_END_TIME, DANGER_MODE_DURATION_SECONDS
    try:
        print(f"[CMD ALERTA] Bytes recebidos: {frm_payload_bytes}")
        
        if not frm_payload_bytes or len(frm_payload_bytes) < 2: 
            print(f"[CMD ALERTA][ERRO] Payload de alerta inválido ou muito curto: {frm_payload_bytes}")
            return

        msg_type = frm_payload_bytes[0]
        action = frm_payload_bytes[1]
        
        

        print(f"[CMD ALERTA] Descodificado: TipoMsg={hex(msg_type)}, Acao={hex(action)}")

        if msg_type == 0x02:  
            if action == 0x01:  
                print("[CMD ALERTA] ORDEM DE PARAGEM (0x01) RECEBIDA! A iniciar processo de desligamento.")
                IS_SHUTDOWN = True
                IS_IN_DANGER_MODE = False 
                
                machine_state["rpm"]["value"] = 0
                machine_state["consumption"]["value"] = 0
                print(f"[SHUTDOWN] RPM e Consumo definidos para 0.")

            elif action == 0x02: 
                if not IS_SHUTDOWN: 
                    print("[CMD ALERTA] ORDEM DE REDUÇÃO POR PERIGO (0x02) RECEBIDA!")
                    IS_IN_DANGER_MODE = True
                    DANGER_MODE_DURATION_SECONDS = 5 * UPDATE_TIME 
                    DANGER_MODE_END_TIME = time.time() + DANGER_MODE_DURATION_SECONDS
                    print(f"[DANGER MODE] Modo de perigo ativado por {DANGER_MODE_DURATION_SECONDS} segundos.")
                else:
                    print("[CMD ALERTA] Ordem de DANGER recebida, mas máquina já está em SHUTDOWN. Ignorando.")
            else:
                print(f"[CMD ALERTA] Ação de alerta não suportada: {hex(action)}")
        else:
            print(f"[CMD ALERTA] Tipo de mensagem de alerta não suportado: {hex(msg_type)}")

    
    
    except Exception as e:
        print(f"[CMD ALERTA][ERRO] Falha ao processar comando de alerta: {e} | Payload raw: {frm_payload_bytes}")

def on_message(client, userdata, msg):
    print(f"\n[MSG RECEBIDA] Tópico: {msg.topic}")
    try:
        data = json.loads(msg.payload.decode())
        if "downlinks" in data and len(data["downlinks"]) > 0:
            frm_payload_b64 = data["downlinks"][0].get("frm_payload")
            if frm_payload_b64:
                
                frm_payload_b64_cleaned = "".join(frm_payload_b64.split())
                payload_bytes = base64.b64decode(frm_payload_b64_cleaned)
                
                if msg.topic == topic_down_machine:
                    process_control_command(payload_bytes)
                elif msg.topic == topic_down_alert:
                    process_alert_command(payload_bytes)
            else:
                print("[MSG RECEBIDA] frm_payload em branco ou ausente.")
        else:
            print("[MSG RECEBIDA] Estrutura de downlink inesperada.")

    except json.JSONDecodeError:
        print(f"[MSG RECEBIDA][ERRO] Payload não é JSON válido: {msg.payload.decode()}")
    except base64.binascii.Error:
        print(f"[MSG RECEBIDA][ERRO] Payload Base64 inválido: {frm_payload_b64}")
    except Exception as e:
        print(f"[MSG RECEBIDA][ERRO] Erro ao processar mensagem: {e}")

client.on_message = on_message


try:
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    print(f"[MQTT] Conectado ao broker {MQTT_BROKER}:{MQTT_PORT}")
    client.loop_start() 
    
    client.subscribe(topic_down_machine)
    print(f"[MQTT] Subscrito a {topic_down_machine}")
    client.subscribe(topic_down_alert)
    print(f"[MQTT] Subscrito a {topic_down_alert}")

    while True:
        payload = generate_payload()
        client.publish(topic_up, json.dumps(payload))
        dp = payload['uplink_message']['decoded_payload']
        print(f"[{datetime.now()}] Sent to {topic_up} ({MACHINE_ID}/{MACHINE_CODE}) [{dp.get('status','?')}]: {dp}")

        time.sleep(UPDATE_TIME)

except KeyboardInterrupt:
    print("Simulation stopped by user.")
finally:
    client.loop_stop()
    client.disconnect()
    print("MQTT client disconnected.") 
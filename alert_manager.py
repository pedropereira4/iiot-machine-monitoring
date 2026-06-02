import json
import socket
import sys
import time
from datetime import datetime, timedelta
from paho.mqtt.client import Client, CallbackAPIVersion

if len(sys.argv) < 2:
    print("Uso: python alert_manager.py <GroupID>")
    sys.exit(1)
GROUP_ID = sys.argv[1]

DMA_UDP_IP = "127.0.0.1"
DMA_UDP_PORT = 5006

MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883

CRITICAL_ALARM_COUNT_THRESHOLD = 3
DANGER_ALARM_COUNT_THRESHOLD = 1
ALARM_EVALUATION_WINDOW_MINUTES = 2

# Shared globals used by callbacks — udp_sock_to_dma is set inside main()
machine_states = {}
udp_sock_to_dma = None


# ---------------------------------------------------------------------------
# MQTT callbacks
# ---------------------------------------------------------------------------

def on_connect_mdm_listener(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("[AM MQTT Listener] Conectado ao Broker MQTT para escutar comandos MDM.")
        mdm_to_dma_control_topic = f"{GROUP_ID}/control_commands/mdm_to_dma/+"
        client.subscribe(mdm_to_dma_control_topic)
        print(f"[AM MQTT Listener] Subscrito a: {mdm_to_dma_control_topic}")
    else:
        print(f"[AM MQTT Listener] Falha ao conectar, código de retorno: {rc}")


def on_message_mdm_command(client, userdata, msg):
    try:
        payload_str = msg.payload.decode()
        command_data = json.loads(payload_str)
        machine_id = msg.topic.split('/')[-1]

        print(f"[AM MQTT Listener] Comando MDM->DMA recebido para {machine_id}: {command_data}")

        if command_data.get("action") == "adjust_parameter":
            if machine_id not in machine_states:
                machine_states[machine_id] = {
                    "alarm_timestamps": [],
                    "last_danger_ts": 0,
                    "last_critical_ts": 0
                }
            machine_states[machine_id]["alarm_timestamps"].append(datetime.utcnow())
            print(f"[AM INFO] Alarme registado para {machine_id} às {datetime.utcnow()}")
            evaluate_machine_health(machine_id)

    except json.JSONDecodeError:
        print(f"[AM MQTT Listener ERRO JSON] Payload não é JSON válido: {msg.payload.decode(errors='ignore')}")
    except Exception as e:
        print(f"[AM MQTT Listener ERRO GERAL] Em on_message_mdm_command: {e}")


# ---------------------------------------------------------------------------
# Health evaluation
# ---------------------------------------------------------------------------

def evaluate_machine_health(machine_id):
    if machine_id not in machine_states:
        return

    current_time = datetime.utcnow()
    state = machine_states[machine_id]

    # Keep only alarms within the evaluation window
    state["alarm_timestamps"] = [
        ts for ts in state["alarm_timestamps"]
        if current_time - ts <= timedelta(minutes=ALARM_EVALUATION_WINDOW_MINUTES)
    ]
    num_alarms = len(state["alarm_timestamps"])
    print(f"[AM HEALTH CHECK] Máquina {machine_id}: {num_alarms} alarmes nos últimos {ALARM_EVALUATION_WINDOW_MINUTES} min.")

    # Use utcfromtimestamp so both sides of the subtraction are UTC-naive
    time_since_last_critical = (
        (current_time - datetime.utcfromtimestamp(state["last_critical_ts"])).total_seconds()
        if state["last_critical_ts"] else float('inf')
    )
    time_since_last_danger = (
        (current_time - datetime.utcfromtimestamp(state["last_danger_ts"])).total_seconds()
        if state["last_danger_ts"] else float('inf')
    )

    if num_alarms >= CRITICAL_ALARM_COUNT_THRESHOLD:
        if time_since_last_critical > ALARM_EVALUATION_WINDOW_MINUTES * 60:
            print(f"[AM STATUS CRITICAL] Máquina {machine_id} atingiu {num_alarms} alarmes. A enviar STOP.")
            send_command_to_dma(machine_id, "stop")
            state["last_critical_ts"] = current_time.timestamp()
            state["alarm_timestamps"] = []
        else:
            print(f"[AM INFO] Estado CRITICAL para {machine_id} já accionado recentemente. A aguardar.")

    elif num_alarms >= DANGER_ALARM_COUNT_THRESHOLD:
        if time_since_last_danger > (ALARM_EVALUATION_WINDOW_MINUTES * 60) / 2:
            print(f"[AM STATUS DANGER] Máquina {machine_id} atingiu {num_alarms} alarmes. A enviar DANGER_REDUCE.")
            send_command_to_dma(machine_id, "danger_reduce")
            state["last_danger_ts"] = current_time.timestamp()
        else:
            print(f"[AM INFO] Estado DANGER para {machine_id} já accionado recentemente. A aguardar.")
    else:
        print(f"[AM STATUS NORMAL] Máquina {machine_id} com {num_alarms} alarmes.")


def send_command_to_dma(machine_id, action, reason_code=0x01):
    command_payload = {"machine_id": machine_id, "type": "alert", "action": action}
    if action == "stop":
        command_payload["reason_code"] = reason_code
    try:
        udp_sock_to_dma.sendto(
            json.dumps(command_payload).encode('utf-8'),
            (DMA_UDP_IP, DMA_UDP_PORT)
        )
        print(f"[AM->DMA UDP] Comando '{action}' enviado para {machine_id} → {DMA_UDP_IP}:{DMA_UDP_PORT}")
    except Exception as e:
        print(f"[AM ERRO UDP] Falha ao enviar comando para DMA: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global udp_sock_to_dma
    udp_sock_to_dma = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    mqtt_client = Client(CallbackAPIVersion.VERSION2, client_id="AlertManager_MDM_Listener")
    mqtt_client.on_connect = on_connect_mdm_listener
    mqtt_client.on_message = on_message_mdm_command

    print("[INFO AM] Alert Manager a iniciar...")
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print("[INFO AM] Alert Manager pronto.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO AM] A desligar (Ctrl+C)...")
    except Exception as e:
        print(f"[AM ERRO CRÍTICO] {e}")
    finally:
        print("[INFO AM] A limpar recursos...")
        if mqtt_client.is_connected():
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
            print("[INFO AM] Cliente MQTT desconectado.")
        udp_sock_to_dma.close()
        print("[INFO AM] Socket UDP fechado.")
        print("[INFO AM] Alert Manager desligado.")


if __name__ == "__main__":
    main()

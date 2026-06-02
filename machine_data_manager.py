import json
# import base64 # Removido, não é mais necessário aqui
import sys
from paho.mqtt.client import Client, CallbackAPIVersion

if len(sys.argv) != 2:
    print("Uso: python machine_data_manager.py <GroupID>")
    sys.exit(1)

GROUP_ID = sys.argv[1]
BROKER = "127.0.0.1" 
PORT = 1883

MACHINE_HEALTH_CONFIG = {}

try:
    with open("intervals.cfg", "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            
            if "#" in line:
                line = line.split("#", 1)[0].strip()

            parts = line.split()
            
            if len(parts) >= 4: 
                param_name = parts[0]
                try:
                    MACHINE_HEALTH_CONFIG[param_name] = {
                        "low": float(parts[1]),
                        "high": float(parts[2]),
                        "ideal": float(parts[3])
                    }
                except ValueError:
                    print(f"[AVISO] Linha mal formada (valores não numéricos) em intervals.cfg: {line} -> {parts}")
            elif len(parts) > 0: 
                print(f"[AVISO] Linha mal formada (poucas partes) em intervals.cfg: {line}")

    if not MACHINE_HEALTH_CONFIG:
        print("[ERRO CRÍTICO] Nenhuma configuração de saúde foi carregada de intervals.cfg. O ficheiro está vazio ou mal formatado?")
        sys.exit(1)
    else:
        print(f"[INFO] Configuração de saúde carregada de intervals.cfg: {MACHINE_HEALTH_CONFIG}")

except FileNotFoundError:
    print("[ERRO CRÍTICO] Ficheiro intervals.cfg não encontrado! A sair.")
    sys.exit(1)
except Exception as e:
    print(f"[ERRO CRÍTICO] Não foi possível ler intervals.cfg: {e}")
    sys.exit(1)



def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        machine_id = payload["machine"]
        sensors = payload["sensors"]

        print(f"[DEBUG MDM] Recebido de {machine_id} via DMA: {sensors}")

        if sensors.get("status") == "SHUTDOWN":
            print(f"[MDM] Máquina {machine_id} em SHUTDOWN. A ignorar dados de sensores.")
            return

        limites_globais = MACHINE_HEALTH_CONFIG

        for param, value in sensors.items():
            if param not in limites_globais:
                continue

            try:
                value = float(value)
            except ValueError:
                print(f"[ERRO MDM] Valor inválido para {param} da máquina {machine_id}: {value}")
                continue

            min_v = limites_globais[param]["low"]
            max_v = limites_globais[param]["high"]

            adjustment_for_machine = 0
            is_out_of_bounds = False

            if value > max_v:
                raw = max_v - value  # negative
                adjustment_for_machine = int(raw) if raw <= -1 else -1
                is_out_of_bounds = True
            elif value < min_v:
                raw = min_v - value  # positive
                adjustment_for_machine = int(raw) if raw >= 1 else 1
                is_out_of_bounds = True

            adjustment_for_machine = max(-128, min(127, adjustment_for_machine))

            if is_out_of_bounds:
                
                control_topic_dma = f"{GROUP_ID}/control_commands/mdm_to_dma/{machine_id}"
                control_payload_dma = {
                    "action": "adjust_parameter",
                    "parameter": param,
                    "value": adjustment_for_machine 
                }
                client.publish(control_topic_dma, json.dumps(control_payload_dma))
                print(f"[MDM COMANDO->DMA] Máquina {machine_id}: {param}={value:.2f} (limites: {min_v}-{max_v}) -> Solicitar ajuste de {adjustment_for_machine} para DMA em {control_topic_dma}")
            
                

    except Exception as e:
        print(f"[ERRO MDM] Em on_message: {e}")
        import traceback
        traceback.print_exc()

def main():
    mqttc = Client(CallbackAPIVersion.VERSION2)
    mqttc.on_message = on_message
    mqttc.connect(BROKER, PORT, 60)

    for i in range(1, 9):
        internal_topic = f"{GROUP_ID}/internal/M{i}"
        mqttc.subscribe(internal_topic)
        print(f"[MQTT MDM] Subscrito ao tópico interno de dados: {internal_topic}")

    mqttc.loop_forever()


if __name__ == "__main__":
    main()

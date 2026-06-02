import paho.mqtt.client as mqtt
from datetime import datetime

BROKER = "10.6.1.9"  
PORT = 1883
TOPIC = "#"


def on_message(client, userdata, msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        payload = msg.payload.decode("utf-8")
    except UnicodeDecodeError:
        payload = "<BINÁRIO ou NÃO UTF-8>"

    print(f"[{timestamp}]:{msg.topic}:{payload}")


if __name__ == "__main__":
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.subscribe(TOPIC)
    print(f"[Info] Subscrito ao tópico geral: {TOPIC}")
    print(f"[Info] Debugger Ativo em '{TOPIC}'...")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[Info] A desligar...")
        client.disconnect()

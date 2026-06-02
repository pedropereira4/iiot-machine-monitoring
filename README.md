# IIoT Machine Monitoring System

A full-stack **Industrial IoT** solution simulating real-time LoRaWAN machine monitoring, with automated alerting, time-series data storage and a Grafana control dashboard.

---

## Overview

This project simulates an IIoT (Industrial Internet of Things) environment where 8 industrial machines continuously transmit sensor data over a LoRaWAN network. The system processes the data in real time, detects anomalies, issues corrective commands, and escalates to automated shutdowns when machines show critical degradation patterns.

The architecture follows a multi-agent design with clear separation of responsibilities between data ingestion, monitoring, alerting, and visualisation.

---

## Architecture

```
 LoRaWAN Machines (x8)
        │  MQTT uplink
        ▼
  MQTT Broker (Mosquitto)
        │
        ▼
 Data Manager Agent ──────────────────────────────► InfluxDB Cloud
        │   (unit conversion, encoding, storage)          │
        │                                                  │
        ├──── MQTT (internal topic) ────► Machine Data Manager
        │                                      │
        │                                      │ MQTT (control command)
        │                                      ▼
        │◄──────────────── Alert Manager (UDP) ┘
        │
        ▼
  MQTT Machines (downlink commands)           Grafana Dashboard
```

- **Machines** — 8 simulated LoRaWAN devices, each with unique sensor units, publishing to `v3/{GroupID}@ttn/devices/{machine_id}/up`
- **Data Manager Agent** — the central hub: normalises units, encodes binary commands, stores data in InfluxDB, bridges MQTT ↔ UDP
- **Machine Data Manager** — reads `intervals.cfg`, detects out-of-range sensors, sends corrective adjustment commands
- **Alert Manager** — tracks alarm frequency over a sliding time window, escalates to DANGER or CRITICAL (shutdown) via UDP
- **MQTT Debugger** — lightweight console tool that logs every MQTT message in real time

---

## Features

- **Real-time sensor simulation** — RPM, coolant temperature, oil pressure, battery potential and fuel consumption, with realistic random drift and operational limits
- **Multi-unit support** — machines report in different units (psi/bar, °C/°F, V/mV, l/h/gal/h); the Data Manager Agent normalises everything to a standard base unit before processing
- **Binary command protocol** — control and alert messages are byte-encoded and Base64-encoded before transmission, following a LoRaWAN downlink format
- **Two-tier alert system** — DANGER mode (gradual parameter reduction) and CRITICAL mode (full machine shutdown with automatic restart cycle)
- **Sliding window health evaluation** — the Alert Manager tracks alarms within a configurable time window to avoid overreacting to isolated spikes
- **InfluxDB time-series storage** — sensor readings, control events and alert logs are all stored separately for independent analysis
- **Grafana dashboard** — summary and detailed views with real-time and historical data, signal quality metrics (RSSI, SNR) and machine health status

---

## Tech Stack

Python 3 · Paho MQTT · InfluxDB Cloud · Grafana Cloud · Mosquitto MQTT Broker · LoRaWAN (TTN format simulation) · UDP Sockets · Base64 binary encoding

---

## Project Structure

```
├── machine.py               # LoRaWAN machine simulator (8 machine types)
├── data_manager_agent.py    # Central data processing and command encoding agent
├── machine_data_manager.py  # Sensor health monitor and corrective command issuer
├── alert_manager.py         # Long-term health evaluator with DANGER/CRITICAL escalation
├── mqtt_debugger.py         # Real-time MQTT traffic console logger
├── intervals.cfg            # Healthy operating ranges for each sensor parameter
├── .env.example             # Environment variable template
└── requirements.txt         # Python dependencies
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- A running MQTT broker (e.g. [Mosquitto](https://mosquitto.org/))
- An [InfluxDB Cloud](https://www.influxdata.com/) free account
- A [Grafana Cloud](https://grafana.com/) free account

### Installation

```bash
git clone https://github.com/pedropereira4/iiot-machine-monitoring.git
cd iiot-machine-monitoring
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
```

Edit `.env` and fill in your InfluxDB token:

```
INFLUX_TOKEN=your_influxdb_token_here
```

### Running

Open a separate terminal for each component:

```bash
# 1. Start the Data Manager Agent
python data_manager_agent.py <GroupID>

# 2. Start the Machine Data Manager
python machine_data_manager.py <GroupID>

# 3. Start the Alert Manager
python alert_manager.py <GroupID>

# 4. Start the MQTT Debugger (optional)
python mqtt_debugger.py

# 5. Start one or more machine simulators
python machine.py <GroupID> <UpdateIntervalSeconds> <MachineCode>
# Example:
python machine.py 1 5 A23X
python machine.py 1 5 H65P
```

**Available machine codes:** `A23X`, `B47Y`, `C89Z`, `D56W`, `E34V`, `F78T`, `G92Q`, `H65P`

---

## Machine Simulation Details

| Machine | Code | Oil Pressure | Coolant Temp | Battery | Consumption |
|---------|------|-------------|--------------|---------|-------------|
| M1 | A23X | psi | °C | V | l/h |
| M2 | B47Y | bar | °C | V | gal/h |
| M3 | C89Z | psi | °C | V | gal/h |
| M4 | D56W | bar | °C | V | l/h |
| M5 | E34V | psi | °F | V | gal/h |
| M6 | F78T | bar | °F | V | l/h |
| M7 | G92Q | psi | °F | V | l/h |
| M8 | H65P | bar | °F | mV | gal/h |

---

## Command Protocol

Control and alert messages use a compact binary format transmitted as Base64 over MQTT downlinks.

**Control message (4 bytes):**

| Byte | Meaning | Example |
|------|---------|---------|
| 1st | Message type (`0x01` = Control) | `0x01` |
| 2nd | Action (`0x01` = Modify parameter) | `0x01` |
| 3rd | Parameter (`0x01`=RPM, `0x02`=Fuel, `0x03`=Temp, `0x04`=Oil, `0x05`=Battery) | `0x01` |
| 4th | Signed adjustment value | `0xFA` (-6) |

**Alert message (3 bytes):**

| Byte | Meaning | Example |
|------|---------|---------|
| 1st | Message type (`0x02` = Alert) | `0x02` |
| 2nd | Action (`0x01`=Stop, `0x02`=Danger reduce) | `0x01` |
| 3rd | Reason code | `0x01` |

---

## Alert Manager Logic

The Alert Manager monitors the frequency of corrective commands issued by the Machine Data Manager within a **2-minute sliding window**:

- **NORMAL** — fewer than 1 alarm
- **DANGER** — 1–2 alarms → sends a `danger_reduce` command; machine enters a reduced-load mode for `5 × update_interval` seconds
- **CRITICAL** — 3+ alarms → sends a `stop` command via UDP to the Data Manager Agent; machine shuts down and automatically restarts once it cools down

A cooldown mechanism prevents repeated escalations within the same window.

---

## Academic Context

Developed as part of the **Sensing and Actuation Networks and Systems** course at the Department of Informatics Engineering, University of Coimbra (2024–2025).

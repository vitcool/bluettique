# bluettique

Bluettique is a Python-based project designed to manage and control various smart devices, including Bluetti power stations, FingerBot devices, and Tapo smart plugs. The project integrates with these devices using Bluetooth and MQTT protocols, providing a seamless way to automate and monitor their operations.

## Features

- **Bluetti Power Station Control**: Connects to Bluetti power stations via MQTT to monitor and control AC/DC outputs, power status, and battery levels.
- **FingerBot Automation**: Uses Bluetooth to connect and control FingerBot devices, allowing for automated button pressing and device pairing.
- **Tapo Smart Plug Integration**: Manages Tapo smart plugs via the Tapo API, enabling remote control and status monitoring.
- **State Management**: Implements a state handler to manage the different states of the system, ensuring smooth transitions and operations.
- **Logging**: Provides detailed logging for debugging and monitoring purposes.


## Table of Contents

- Installation
- Environment Variables
- Running the Project
- Running with Docker Compose
- Dependencies

## Installation

1. Clone the repository:

   `git clone https://github.com/your-username/your-repo.git`

2. Navigate to the project directory:

   `cd your-repo`

3. Set up a virtual environment:

   - **Linux/macOS**:

     `python3 -m venv venv`

     `source venv/bin/activate`

   - **Windows**:

     `python -m venv venv`

     `venv\Scripts\activate`

4. Install the required dependencies:

   `pip install -r requirements.txt`

## Environment Variables

This project requires some environment variables to be set. These variables are stored in a `.env` file in the root of the project.

Create a `.env` file in the root of the project and add the following variables:

```
FINGERBOT_LOCAL_KEY_MAIN=
FINGERBOT_MAC_MAIN=
FINGERBOT_UUID_MAIN=
FINGERBOT_DEV_ID_MAIN=

FINGERBOT_LOCAL_KEY_ADD=
FINGERBOT_MAC_ADD=
FINGERBOT_UUID_ADD=
FINGERBOT_DEV_ID_ADD=

TAPO_USERNAME=
TAPO_PASSWORD=
TAPO_IP_ADDRESS=

BLUETTI_BROKER_HOST=
BLUETTI_BROKER_INTERVAL=
BLUETTI_MAC_ADDRESS=
BLUETTI_DEVICE_NAME=
BLUETTI_BROKER_CONNECTION_TIMEOUT=

IDLE_INTERVAL=
LONG_IDLE_INTERVAL=

ENV='dev' # 'prod'

SCHEDULE_GROUP_NAME = # group name according to the schedule
```

Make sure to replace the placeholders with your actual credentials and settings.

## Running the Project

1. Activate the virtual environment (if not already activated):

   - **Linux/macOS**: `source venv/bin/activate`
   
   - **Windows**: `venv\Scripts\activate`

2. Run the application:

   `python main.py`

## Quick FingerBot Test (host, no Docker)

Use this to press the main FingerBot directly from the host OS (Bluetooth/gatttool access to `hci0` required):

1. Activate the virtual environment.
2. Ensure the `.env` file has `FINGERBOT_*_MAIN` values populated.
3. Run `python scripts/fingerbot_press.py` to connect and trigger a press.

## Running with Docker Compose

1. Ensure Docker and Docker Compose are installed on your system.

2. Build and start the containers in detached mode:

   `docker-compose up -d --build`

3. To stop the containers:

   `docker-compose down`

## Dependencies

All dependencies are listed in the `requirements.txt` file. To install them, use:

`pip install -r requirements.txt`

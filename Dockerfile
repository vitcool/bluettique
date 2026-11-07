FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    bluez \
    bluetooth \
    libbluetooth-dev \
    dbus \
    sudo \
    tzdata \
    procps \
    mosquitto \
    mosquitto-clients \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python -m venv /venv

ENV PATH="/venv/bin:$PATH"
ENV TZ=Europe/Kyiv

# Install dependencies in a cache-friendly layer.
# This layer is reused as long as requirements.txt does not change.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy app source last so code edits do not invalidate dependency layers.
COPY . /app

CMD ["sh", "-c", "mosquitto -c /app/mosquitto.conf & python main.py & wait"]

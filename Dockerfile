# Use a lightweight Python image
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    bluez \
    bluetooth \
    libbluetooth-dev \
    dbus \
    sudo \
    tzdata

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install virtualenv and create a virtual environment
RUN python -m venv /venv

# Ensure the virtual environment binaries are first on PATH
ENV PATH="/venv/bin:$PATH"

# Set the timezone
ENV TZ=Europe/Kyiv

# Install any dependencies if needed (e.g., if requirements.txt exists)
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main.py"]

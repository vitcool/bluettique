# Use a lightweight Python image
FROM python:3.9-slim

RUN apt-get update && apt-get install -y \
    bluez \
    bluetooth \
    libbluetooth-dev \
    dbus \
    sudo

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install virtualenv and create a virtual environment
RUN python -m venv /venv

# Activate the virtual environment by updating the PATH
ENV PATH="/venv/bin:$PATH"

# Install any dependencies if needed (e.g., if requirements.txt exists)
RUN pip install --no-cache-dir -r requirements.txt

# Run the script
ENV PATH="/opt/venv/bin:$PATH"

# Run the application
CMD ["python", "main.py"]


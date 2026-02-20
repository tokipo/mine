FROM debian:stable

ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies including procps for ps command
RUN apt-get update && \
    apt-get install -y wget gnupg git python3 python3-pip python3-venv unzip curl procps && \
    rm -rf /var/lib/apt/lists/*

# Add Amazon Corretto and install Java 21
RUN wget -O- https://apt.corretto.aws/corretto.key | gpg --dearmor > /usr/share/keyrings/corretto-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/corretto-archive-keyring.gpg] https://apt.corretto.aws stable main" > /etc/apt/sources.list.d/corretto.list && \
    apt-get update && \
    apt-get install -y java-21-amazon-corretto-jdk && \
    rm -rf /var/lib/apt/lists/*

# Install Python packages for the Web UI Panel
RUN pip3 install --no-cache-dir --break-system-packages gdown fastapi uvicorn websockets python-multipart aiofiles

# Set working directory
WORKDIR /app

# Copy application files
COPY . /app

# Set permissions
RUN chmod -R 777 /app && \
    chmod +x /app/start.sh

# Expose Web UI port (Hugging Face standard)
EXPOSE 7860

# Set default command
CMD ["sh", "start.sh"]
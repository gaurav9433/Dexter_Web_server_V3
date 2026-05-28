# =============================================================================
# Dexter HMS Edge Agent — Dockerfile
# Target platform : linux/arm64 (Raspberry Pi 4, 64-bit OS)
#
# Build & push to ECR:
#   docker buildx build --platform linux/arm64 \
#     -t <ECR_URL>/dexter-edge:<version> --push .
#
# Local ARM64 test build (loads into local daemon):
#   docker buildx build --platform linux/arm64 -t dexter-edge:latest --load .
# =============================================================================

FROM python:3.11-slim

# System packages needed to compile native Python extensions
# (netifaces, cryptography, RPi.GPIO, smbus2 all need gcc/headers)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        python3-dev \
        libffi-dev \
        libssl-dev \
        i2c-tools \
        iputils-ping \
        ppp \
    && rm -rf /var/lib/apt/lists/*

# Use the same absolute path as production so all hardcoded DB paths
# in settings.yaml (/home/pi/Test3/...) resolve without changes.
WORKDIR /home/pi/Test3

# Install dependencies first — this layer is cached as long as
# requirements.txt is unchanged, speeding up rebuilds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the full project (see .dockerignore for exclusions)
COPY . .

# Runtime environment — credentials must be supplied via .env file or docker-compose,
# never baked into the image. Only non-sensitive defaults go here.
ENV PYTHONUNBUFFERED=1

# Health check — verifies the panel DB is reachable (process is alive)
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python /home/pi/Test3/docker/health_check.py || exit 1

# Default entry point — overridden per service in docker-compose.yml
CMD ["python", "TLChronosProMAIN_391.py"]
# OTA test build — 2026-05-15
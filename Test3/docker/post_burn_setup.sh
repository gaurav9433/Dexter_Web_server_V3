#!/bin/bash
# Run once on each new Pi after burning the master SD card image.
# Must be run AFTER LCD provisioning sets DEVICE_NAME and portainer_register()
# writes PORTAINER_EDGE_ID / PORTAINER_EDGE_KEY to .env.
#
# Usage:
#   scp docker/post_burn_setup.sh pi@<IP>:/home/pi/Test3/docker/
#   ssh pi@<IP> "bash /home/pi/Test3/docker/post_burn_setup.sh"
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin:$PATH

ECR="901178127457.dkr.ecr.ap-south-1.amazonaws.com"
REGION="ap-south-1"
COMPOSE_DIR="/home/pi/Test3"
SCRIPTS_DIR="$COMPOSE_DIR/docker"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# ── Step 1: stop any containers that auto-started with stale master-image state ─
# docker restart: unless-stopped means containers from the burned image would
# auto-start using the old device's env vars (PORTAINER_EDGE_KEY etc.).
# Bring everything down now — docker compose up at the end starts them clean.
log "Stopping any running containers..."
cd "$COMPOSE_DIR"
docker compose down || true
log "Containers stopped."

# ── Step 3: fix CRLF on all shell scripts (Git on Windows writes \r\n) ────────
log "Fixing line endings on shell scripts..."
for script in "$SCRIPTS_DIR"/*.sh; do
    sed -i 's/\r$//' "$script"
    chmod +x "$script"
done
log "Line endings fixed."

# ── Step 4: verify provisioning was completed ─────────────────────────────────
DEVICE_NAME=$(grep -E '^DEVICE_NAME=.+' "$COMPOSE_DIR/.env" | cut -d= -f2 || true)
if [ -z "$DEVICE_NAME" ]; then
    log "ERROR: DEVICE_NAME is blank in .env — run LCD provisioning first, then re-run this script."
    exit 1
fi
log "Device: $DEVICE_NAME"

# ── Step 5: ECR login (stores token in ~/.docker/config.json for OTA cron) ────
log "Logging in to ECR..."
aws ecr get-login-password --region "$REGION" \
    | docker login --username AWS --password-stdin "$ECR"
log "ECR login successful."

# ── Step 6: pull latest image and start the full stack ────────────────────────
log "Pulling latest image from ECR..."
cd "$COMPOSE_DIR"
docker compose pull dexter-core

log "Starting stack with new .env..."
docker compose up -d --remove-orphans
log "Stack started."

# ── Step 7: verify containers came up ─────────────────────────────────────────
log "Container status:"
docker compose ps --format "table {{.Name}}\t{{.Status}}"

log ""
log "post_burn_setup complete for $DEVICE_NAME."
log "OTA cron will check ECR hourly. ECR token refreshes every 6 h."
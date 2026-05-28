#!/bin/bash
# OTA update: check ECR for a new dexter-edge:latest and restart if changed.
# Runs once daily via cron (3 PM).
# If the 3 PM run fails, a second cron entry at 3 AM calls this script with
# --retry; it re-runs only when the last attempt was recorded as FAILED.
#
# Ethernet mode: pull directly over eth0 — no extra steps.
# GSM mode     : briefly bring up ppp0 (pon c16qs) for the pull, then hold
#                ppp0 up for 90s so Prometheus remote_write can flush its
#                queued metrics to EC2 before poff tears it down.
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin:$PATH

ECR="901178127457.dkr.ecr.ap-south-1.amazonaws.com"
REGION="ap-south-1"
COMPOSE_DIR="/home/pi/Test3"
LOG_TAG="dexter-ota"
OTA_FLAG="/tmp/dexter_ota_lastrun"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; logger -t "$LOG_TAG" "$*"; }

# ── retry guard ───────────────────────────────────────────────────────────────
# When called with --retry (3 AM cron), skip if the last 3 PM run succeeded.
if [[ "${1:-}" == "--retry" ]]; then
    if grep -q "^OK" "$OTA_FLAG" 2>/dev/null; then
        log "Retry check: last run OK — no retry needed."
        exit 0
    fi
    log "Retry check: last run FAILED — retrying OTA now."
fi

# Write FAILED to the flag on any error; overwritten with OK at the end.
trap 'echo "FAILED $(date +%Y-%m-%d\ %H:%M:%S)" > "$OTA_FLAG"; log "OTA failed — flag written for 3 AM retry."' ERR

# ── network setup ─────────────────────────────────────────────────────────────
NETWORK_TYPE=$(python3 -c "
import sqlite3
try:
    c = sqlite3.connect('/home/pi/Test3/modem_config.db')
    r = c.execute('SELECT network_type FROM modem_parameters WHERE id=1').fetchone()
    c.close()
    print((r[0] or 'ethernet').strip().lower())
except Exception:
    print('ethernet')
" 2>/dev/null || echo "ethernet")

log "Starting OTA check (network_type=${NETWORK_TYPE})..."

GSM_MODE=false
if [ "$NETWORK_TYPE" = "gsm" ]; then
    GSM_MODE=true
    log "GSM mode — bringing up ppp0 for OTA + Prometheus metrics flush"
    pon c16qs || { log "pon c16qs failed — aborting OTA"; exit 1; }
    sleep 25  # wait for ppp0 to establish and get IP
fi

# ── ECR login ─────────────────────────────────────────────────────────────────
# Refresh ECR login (token valid 12h)
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$ECR" > /dev/null 2>&1 \
  || { log "ECR login failed"; $GSM_MODE && { poff c16qs || true; }; exit 1; }

# ── docker image pull ─────────────────────────────────────────────────────────
# Pull latest image — outputs "Image is up to date" or "Pull complete"
cd "$COMPOSE_DIR"
PULL_OUT=$(docker compose pull dexter-core 2>&1)

if echo "$PULL_OUT" | grep -q "Pull complete"; then
    log "New image detected — restarting stack..."
    docker compose up -d --remove-orphans
    log "Stack restarted with new image."
    docker image prune -f
    log "Old images pruned."
else
    log "Already up to date. No action taken."
fi

# ── GSM cleanup ───────────────────────────────────────────────────────────────
if $GSM_MODE; then
    log "Holding ppp0 up for 90s — Prometheus remote_write flushing queued metrics to EC2..."
    sleep 90
    log "Bringing ppp0 down"
    poff c16qs || true
    log "GSM OTA + metrics flush complete. SerialCommunication.py will re-open serial automatically."
fi

# ── success flag ──────────────────────────────────────────────────────────────
echo "OK $(date '+%Y-%m-%d %H:%M:%S')" > "$OTA_FLAG"
log "OTA complete — status flag: OK"

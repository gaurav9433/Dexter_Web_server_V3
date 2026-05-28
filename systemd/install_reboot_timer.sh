#!/bin/bash
# install_reboot_timer.sh
# Dexter HMS — Privileged helper: install weekly reboot timer units
#
# Called by seple.py (Flask webserver, user pi) via:
#   sudo /home/pi/Test3/install_reboot_timer.sh
#
# This script is the ONLY privileged action needed for set_reboot_schedule().
# It is listed in /etc/sudoers.d/dexter-webserver with NOPASSWD so the
# webserver user can run it without a password prompt or TTY.
#
# Stages:
#   1. Copy staging files (written by seple.py as pi) to /etc/systemd/system/
#   2. Set correct ownership and permissions
#   3. systemctl daemon-reload
#   4. systemctl enable dexter-weekly-reboot.timer
#   5. systemctl restart dexter-weekly-reboot.timer

set -e

STAGING_DIR="/home/pi/Test3"
SYSTEMD_DIR="/etc/systemd/system"
TIMER_STAGING="${STAGING_DIR}/dexter-weekly-reboot.timer"
SERVICE_STAGING="${STAGING_DIR}/dexter-weekly-reboot.service"
TIMER_DEST="${SYSTEMD_DIR}/dexter-weekly-reboot.timer"
SERVICE_DEST="${SYSTEMD_DIR}/dexter-weekly-reboot.service"

# Validate staging files exist
if [ ! -f "${TIMER_STAGING}" ]; then
    echo "ERROR: Timer staging file not found: ${TIMER_STAGING}" >&2
    exit 1
fi
if [ ! -f "${SERVICE_STAGING}" ]; then
    echo "ERROR: Service staging file not found: ${SERVICE_STAGING}" >&2
    exit 1
fi

# Copy to systemd directory
cp "${SERVICE_STAGING}" "${SERVICE_DEST}"
cp "${TIMER_STAGING}"   "${TIMER_DEST}"

# Set correct ownership and permissions
chown root:root "${SERVICE_DEST}" "${TIMER_DEST}"
chmod 644        "${SERVICE_DEST}" "${TIMER_DEST}"

# Reload systemd, enable and restart the timer
systemctl daemon-reload
systemctl enable dexter-weekly-reboot.timer
systemctl restart dexter-weekly-reboot.timer

echo "OK: dexter-weekly-reboot.timer installed and started"
exit 0

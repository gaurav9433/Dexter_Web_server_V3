#!/bin/bash
# =============================================================================
# dexter_restore.sh — Restore Dexter HMS site-specific files to new SD card
#
# Run this on the NEW SD card Pi AFTER first boot and systemd install.
#
# Usage:
#   sudo bash dexter_restore.sh /path/to/dexter_backup_xxx.tar.gz
# =============================================================================

set -euo pipefail
[[ $EUID -ne 0 ]] && { echo "Run as root: sudo bash dexter_restore.sh <archive>"; exit 1; }
[[ -z "${1:-}" ]]  && { echo "Usage: sudo bash dexter_restore.sh <backup.tar.gz>"; exit 1; }

ARCHIVE="$1"
[[ ! -f "$ARCHIVE" ]] && { echo "File not found: $ARCHIVE"; exit 1; }

echo "=== Dexter HMS Restore ==="
echo "Archive: $ARCHIVE"
echo ""

# Stop services
echo "Stopping Dexter services..."
systemctl stop dexter.target 2>/dev/null || true
sleep 2

# Ensure /etc/dexter exists with correct permissions
mkdir -p /etc/dexter
chmod 755 /etc/dexter

# Extract archive
echo "Extracting files..."
tar -xzf "$ARCHIVE" -C / --same-permissions 2>/dev/null || \
tar -xzf "$ARCHIVE" -C /

# Fix permissions on keys
if [[ -f /etc/dexter/fernet.key ]]; then
    chown root:pi /etc/dexter/fernet.key
    chmod 640     /etc/dexter/fernet.key
    echo "  ✓ /etc/dexter/fernet.key  (permissions restored)"
fi
if [[ -f /etc/dexter/cred_auth.key ]]; then
    chown root:pi /etc/dexter/cred_auth.key
    chmod 640     /etc/dexter/cred_auth.key
    echo "  ✓ /etc/dexter/cred_auth.key  (permissions restored)"
fi

# Fix permissions on DB files
for db in /home/pi/Test3/*.db; do
    [[ -f "$db" ]] || continue
    chown pi:pi "$db"
    chmod 660   "$db"
    echo "  ✓ $(basename $db)"
done

echo ""
echo "=== Restored files ==="
tar -tzf "$ARCHIVE" | while read f; do
    [[ -f "/$f" ]] && echo "  ✓ /$f" || echo "  ✗ MISSING: /$f"
done

echo ""
echo "Starting Dexter services..."
systemctl daemon-reload
systemctl start dexter.target

sleep 3
echo ""
echo "=== Service Status ==="
systemctl list-units 'dexter-*' --no-pager 2>/dev/null | grep -E "active|failed|inactive"

echo ""
echo "=== Restore complete ==="
echo "Verify on LCD — all device credentials and settings should be intact."
echo "Check ThingsBoard — telemetry should resume within 30 seconds."

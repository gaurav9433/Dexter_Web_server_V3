#!/bin/bash
# =============================================================================
# dexter_backup.sh — Backup Dexter HMS site-specific files
#
# Run this on the OLD SD card Pi BEFORE swapping.
# Creates a single tar.gz archive containing all site-specific config.
#
# Usage:
#   sudo bash dexter_backup.sh              # saves to /home/pi/dexter_backup.tar.gz
#   sudo bash dexter_backup.sh /media/pi/USB  # saves to USB drive
#
# Restore on new SD:
#   sudo bash dexter_restore.sh dexter_backup.tar.gz
# =============================================================================

set -euo pipefail
[[ $EUID -ne 0 ]] && { echo "Run as root: sudo bash dexter_backup.sh"; exit 1; }

DEST="${1:-/home/pi}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
HOSTNAME=$(hostname)
ARCHIVE="$DEST/dexter_backup_${HOSTNAME}_${TIMESTAMP}.tar.gz"

echo "=== Dexter HMS Backup ==="
echo "Device:  $HOSTNAME"
echo "Archive: $ARCHIVE"
echo ""

# Files to back up
FILES=(
    # Encryption keys — CRITICAL
    "/etc/dexter/fernet.key"
    "/etc/dexter/cred_auth.key"

    # Site-specific databases
    "/home/pi/Test3/device_config.db"
    "/home/pi/Test3/modem_config.db"
    "/home/pi/Test3/logical_params_active_integration.db"
    "/home/pi/Test3/network_settings.db"
    "/home/pi/Test3/operator_codes.db"
    "/home/pi/Test3/dexterpanel2.db"
    "/home/pi/Test3/parameters.db"
    "/home/pi/Test3/cavliRunningParam.db"
    "/home/pi/Test3/cavliPositionParameter.db"
    "/home/pi/Test3/nvr_dvr_bacs_integration.db"
    "/home/pi/Test3/active_integration.db"
)

# Stop services before backup to avoid partial writes
echo "Stopping Dexter services..."
systemctl stop dexter.target 2>/dev/null || true
sleep 2

# Check which files exist
PRESENT=()
MISSING=()
for f in "${FILES[@]}"; do
    if [[ -f "$f" ]]; then
        PRESENT+=("$f")
        echo "  ✓ $f"
    else
        MISSING+=("$f")
        echo "  ✗ MISSING: $f"
    fi
done

echo ""
echo "Backing up ${#PRESENT[@]} files..."
tar -czf "$ARCHIVE" "${PRESENT[@]}"

# Set permissions so pi user can copy it
chown pi:pi "$ARCHIVE"
chmod 640 "$ARCHIVE"

echo ""
echo "=== Backup complete ==="
echo "Archive: $ARCHIVE"
echo "Size:    $(du -sh "$ARCHIVE" | cut -f1)"
echo ""
echo "Next steps:"
echo "  1. Copy $ARCHIVE to USB drive or laptop"
echo "  2. Flash new SD card with Dexter HMS image"
echo "  3. Boot Pi with new SD card"
echo "  4. Copy archive to /home/pi/ on new Pi"
echo "  5. Run: sudo bash dexter_restore.sh $ARCHIVE"
echo ""

# Restart services
echo "Restarting Dexter services..."
systemctl start dexter.target 2>/dev/null || true
echo "Done."

#!/bin/bash
# =============================================================================
# install_services.sh — Deploy ALL Dexter HMS systemd services
#
# Includes:
#   External (panel):   dexter-main, serial, mqtt, network, webserver
#   NVR/DVR:            hikvision, dahua, cpplus (nvr, sd, rtc, extract)
#   BAS integrations:   texecom-bas, amc-bas
#   Utilities:          rpi-task, ota-restore
#
# Usage:
#   sudo bash install_services.sh              # install + start everything
#   sudo bash install_services.sh --dry-run    # show what would be installed
#
# =============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="/etc/systemd/system"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

[[ $EUID -ne 0 ]] && { echo "Run as root: sudo bash install_services.sh"; exit 1; }

echo "=== Dexter HMS systemd installer ==="
echo "Source: $SCRIPT_DIR"
[[ $DRY_RUN -eq 1 ]] && echo "Mode:   DRY RUN (no changes)"
echo ""

# ── Service lists ─────────────────────────────────────────────────────────────

# Start without network — hardware only
NO_NETWORK_SERVICES=(
    dexter-main
    dexter-serial-comm
    dexter-serial-logger
    dexter-rpi-task
)

# Need network
NETWORK_SERVICES=(
    dexter-mqtt
    dexter-network-info
    dexter-webserver
    dexter-nvr-hikvision
    dexter-nvr-hikvision-field
    dexter-nvr-hikvision-bacs
    dexter-nvr-dahua
    dexter-nvr-cpplus
    dexter-nvr-hik-lite
    dexter-extract-dahua
    dexter-extract-cpplus
    dexter-sd-hikvision
    dexter-sd-dahua
    dexter-sd-cpplus
    dexter-rtc-hikvision
    dexter-rtc-dahua
    dexter-rtc-cpplus
    dexter-ota-restore
    dexter-texecom-bas
    dexter-amc-bas
)

ALL_SERVICES=("${NO_NETWORK_SERVICES[@]}" "${NETWORK_SERVICES[@]}")

TARGETS=(
    dexter.target
    dexter-internal.target
    dexter-external.target
)

# ── Step 1: Copy service and target files ─────────────────────────────────────
echo "Step 1: Copying service and target files..."
for f in "$SCRIPT_DIR"/*.service "$SCRIPT_DIR"/*.target; do
    [[ -f "$f" ]] || continue
    fname="$(basename "$f")"
    if [[ $DRY_RUN -eq 0 ]]; then
        cp "$f" "$SYSTEMD_DIR/$fname"
        chmod 644 "$SYSTEMD_DIR/$fname"
    fi
    echo "  ✓ $fname"
done

# ── Step 2: Create required directories ──────────────────────────────────────
echo ""
echo "Step 2: Creating required directories..."

if [[ $DRY_RUN -eq 0 ]]; then
    # Log directory
    mkdir -p /var/log/dexter
    chown pi:pi /var/log/dexter

    # Credential gate key directory
    mkdir -p /etc/dexter
    chmod 755 /etc/dexter
fi
echo "  ✓ /var/log/dexter"
echo "  ✓ /etc/dexter"

# ── Step 3: Generate credential key (once only) ───────────────────────────────
echo ""
echo "Step 3: Credential gate key..."
if [[ ! -f /etc/dexter/cred_auth.key ]]; then
    if [[ $DRY_RUN -eq 0 ]]; then
        python3 -c "import secrets; print(secrets.token_hex(32))" \
            | tee /etc/dexter/cred_auth.key > /dev/null
        chown root:pi /etc/dexter/cred_auth.key
        chmod 640     /etc/dexter/cred_auth.key
    fi
    echo "  ✓ Generated /etc/dexter/cred_auth.key (root:pi 640)"
    echo ""
    echo "  *** SAVE THIS KEY in response_tool.html for engineer phone ***"
    [[ $DRY_RUN -eq 0 ]] && echo "  Key: $(cat /etc/dexter/cred_auth.key)"
else
    echo "  ✓ Already exists — not overwritten"
fi

# Deploy credential_auth.py
if [[ -f "$SCRIPT_DIR/credential_auth.py" ]]; then
    [[ $DRY_RUN -eq 0 ]] && cp "$SCRIPT_DIR/credential_auth.py" /home/pi/Test3/
    echo "  ✓ credential_auth.py deployed to /home/pi/Test3/"
fi

# ── Step 4: Fernet encryption key (once only) ─────────────────────────────────
echo ""
echo "Step 4: Fernet encryption key..."
if [[ ! -f /etc/dexter/fernet.key ]]; then
    if [[ $DRY_RUN -eq 0 ]]; then
        python3 -c "
from cryptography.fernet import Fernet
key = Fernet.generate_key().decode()
print(key)
" | tee /etc/dexter/fernet.key > /dev/null
        chown root:pi /etc/dexter/fernet.key
        chmod 640     /etc/dexter/fernet.key
    fi
    echo "  ✓ Generated /etc/dexter/fernet.key (root:pi 640)"
else
    echo "  ✓ Already exists — not overwritten"
fi

# ── Step 5: Add DB flags for new integrations ─────────────────────────────────
echo ""
echo "Step 5: Initialising integration flags in DB..."
if [[ $DRY_RUN -eq 0 ]]; then
    python3 << 'PYEOF' 2>/dev/null || echo "  ! DB init skipped (run after Test3 is deployed)"
import sys
sys.path.insert(0, '/home/pi/Test3')
import logical_params_module

flags = [
    ('active_integration_amc_bas', 0),
]
for name, default in flags:
    try:
        existing = logical_params_module.get_parameter(name)
        if existing is None:
            logical_params_module.set_parameter(name, default)
            print(f"  ✓ Added: {name} = {default}")
        else:
            print(f"  ✓ Exists: {name} = {existing}")
    except Exception as e:
        print(f"  ! {name}: {e}")
PYEOF
fi

# ── Step 6: Reload systemd ────────────────────────────────────────────────────
echo ""
echo "Step 6: Reloading systemd daemon..."
[[ $DRY_RUN -eq 0 ]] && systemctl daemon-reload
echo "  ✓ Done"

# ── Step 7: Enable targets and services ──────────────────────────────────────
echo ""
echo "Step 7: Enabling targets..."
for target in "${TARGETS[@]}"; do
    if [[ $DRY_RUN -eq 0 ]]; then
        systemctl enable "$target" 2>/dev/null && echo "  ✓ $target" || echo "  ✗ $target (not found)"
    else
        echo "  ~ $target (dry run)"
    fi
done

echo ""
echo "Step 8: Enabling services..."
for svc in "${ALL_SERVICES[@]}"; do
    if [[ $DRY_RUN -eq 0 ]]; then
        systemctl enable "${svc}.service" 2>/dev/null \
            && echo "  ✓ $svc" \
            || echo "  ✗ $svc (file not found — skipped)"
    else
        echo "  ~ $svc (dry run)"
    fi
done

# ── Step 9: Check for old startup methods ────────────────────────────────────
echo ""
echo "Step 9: Checking for old startup methods..."
OLD_FOUND=0
for f in /etc/rc.local /var/spool/cron/crontabs/pi /var/spool/cron/crontabs/root; do
    if [[ -f "$f" ]] && grep -q "active_integration.sh\|run_scripts.sh" "$f" 2>/dev/null; then
        echo "  WARNING: Old .sh reference in $f — please remove manually"
        OLD_FOUND=1
    fi
done
[[ $OLD_FOUND -eq 0 ]] && echo "  ✓ No old startup methods found"

# ── Step 10: Start services ───────────────────────────────────────────────────
echo ""
echo "Step 10: Starting dexter.target..."
if [[ $DRY_RUN -eq 0 ]]; then
    systemctl start dexter.target 2>/dev/null \
        && echo "  ✓ dexter.target started" \
        || echo "  ! dexter.target had errors — check: journalctl -u dexter-main -n 20"
fi

# ── Status summary ────────────────────────────────────────────────────────────
echo ""
echo "=== Service Status ==="
if [[ $DRY_RUN -eq 0 ]]; then
    for svc in "${ALL_SERVICES[@]}"; do
        status=$(systemctl is-active "${svc}.service" 2>/dev/null || echo "unknown")
        icon="✓"; [[ "$status" != "active" ]] && icon="✗"
        printf "  %s %-38s %s\n" "$icon" "$svc" "$status"
    done
else
    echo "  (dry run — no services started)"
fi

# ── Step: Install helper script + sudoers rule for webserver reboot scheduler ─
echo ""
echo "Step: Installing reboot-timer helper script and sudoers rule..."

HELPER="/home/pi/Test3/install_reboot_timer.sh"
SUDOERS_FILE="/etc/sudoers.d/dexter-webserver"

if [[ $DRY_RUN -eq 0 ]]; then
    # Copy helper script if present alongside this installer
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [[ -f "${SCRIPT_DIR}/install_reboot_timer.sh" ]]; then
        cp "${SCRIPT_DIR}/install_reboot_timer.sh" "${HELPER}"
        chown root:pi "${HELPER}"
        chmod 750     "${HELPER}"
        echo "  ✓ Helper script installed: ${HELPER}"
    else
        echo "  ✗ install_reboot_timer.sh not found next to install_services.sh — skipping"
    fi

    # Add NOPASSWD sudoers rule for the helper script
    # Allows user pi (webserver) to run the helper without a password or TTY
    cat > "${SUDOERS_FILE}" <<'SUDOERS'
# Dexter HMS — allow webserver (pi) to install the weekly reboot timer
# without a password prompt. Only this specific script is permitted.
pi ALL=(root) NOPASSWD: /home/pi/Test3/install_reboot_timer.sh
SUDOERS
    chmod 440 "${SUDOERS_FILE}"
    # Validate the sudoers file before leaving it in place
    if visudo -cf "${SUDOERS_FILE}" > /dev/null 2>&1; then
        echo "  ✓ Sudoers rule installed: ${SUDOERS_FILE}"
    else
        rm -f "${SUDOERS_FILE}"
        echo "  ✗ Sudoers validation failed — rule not installed"
    fi
else
    echo "  ~ Helper + sudoers rule (dry run)"
fi

echo ""
echo "=== Done ==="
echo ""
echo "Useful commands:"
echo "  sudo systemctl status dexter.target          # all services summary"
echo "  sudo journalctl -u dexter-main -f            # main panel live logs"
echo "  sudo journalctl -u dexter-amc-bas -f         # AMC integration logs"
echo "  sudo journalctl -u dexter-texecom-bas -f     # Texecom integration logs"
echo "  sudo journalctl -u dexter-webserver -f       # webserver logs"
echo "  sudo journalctl -u 'dexter-*' -f             # all Dexter logs"
echo "  sudo systemctl stop dexter.target            # stop everything"
echo "  sudo systemctl restart dexter-main           # restart one service"

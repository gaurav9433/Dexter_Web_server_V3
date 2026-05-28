#!/usr/bin/env bash
# =============================================================================
# dexter_boot_diagnose.sh — Dexter HMS Boot Diagnosis Script
# Seple Novaedge Pvt. Ltd.
#
# Called by autorun4.py → boot_diagnosis()
# Location: /home/pi/systemd_final/dexter_boot_diagnose.sh
# Usage:    sudo bash /home/pi/systemd_final/dexter_boot_diagnose.sh
# =============================================================================

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN="\033[92m"
RED="\033[91m"
YELLOW="\033[93m"
CYAN="\033[96m"
BOLD="\033[1m"
DIM="\033[2m"
RESET="\033[0m"

ok()   { echo -e "${GREEN}  ✓ $1${RESET}"; }
fail() { echo -e "${RED}  ✗ $1${RESET}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${RESET}"; }
info() { echo -e "${CYAN}  → $1${RESET}"; }
hdr()  { echo -e "\n${BOLD}${CYAN}$1${RESET}"; echo "  $(printf '─%.0s' {1..54})"; }

PASS=0
FAIL=0

check() {
    # check "label" "command"
    local label="$1"
    local cmd="$2"
    if eval "$cmd" &>/dev/null; then
        ok "$label"
        ((PASS++))
    else
        fail "$label"
        ((FAIL++))
    fi
}

# =============================================================================
echo -e "\n${BOLD}============================================================"
echo "  DEXTER HMS — BOOT DIAGNOSIS"
echo -e "============================================================${RESET}"
echo "  Host     : $(hostname)"
echo "  Date     : $(date '+%d %b %Y  %H:%M:%S')"
echo "  Kernel   : $(uname -r)"
echo "  Uptime   : $(uptime -p)"

# ── 1. dexter.target ──────────────────────────────────────────────────────────
hdr "1. dexter.target"
check "dexter.target is active" "systemctl is-active --quiet dexter.target"
check "dexter.target enabled at boot" "systemctl is-enabled --quiet dexter.target"

# ── 2. Core Services ─────────────────────────────────────────────────────────
hdr "2. Core Services"
CORE_SVCS=(
    "dexter-main:Main Panel Controller (TLChronosProMAIN_391.py)"
    "dexter-serial-comm:Serial RS-232/485 Controller (SerialCommunication.py)"
    "dexter-serial-logger:Serial Data Logger (serial_data_logger.py)"
    "dexter-mqtt:ThingsBoard MQTT Publisher (thingsboard_mqtt_publisher.py)"
    "dexter-webserver:Flask Engineer Webserver (seple.py port 5001)"
    "dexter-rpi-task:RPi Health Monitor (RPi_Task_Manager.py)"
    "dexter-ota-restore:OTA Restore Pipeline (ota_main_restore.py)"
)
for entry in "${CORE_SVCS[@]}"; do
    svc="${entry%%:*}"
    desc="${entry#*:}"
    state=$(systemctl is-active "$svc" 2>/dev/null)
    if [ "$state" = "active" ]; then
        ok "$svc  —  $desc"
        ((PASS++))
    elif [ "$state" = "inactive" ]; then
        warn "$svc  INACTIVE  —  $desc"
        ((FAIL++))
    else
        fail "$svc  $state  —  $desc"
        ((FAIL++))
    fi
done

# ── 3. BAS Integrations ───────────────────────────────────────────────────────
hdr "3. BAS Integrations (Active)"
BAS_SVCS=(
    "dexter-hik-bas:Hikvision BAS (hikvision_bas_integration.py)"
    "dexter-texecom-bas:Texecom BAS Integration"
    "dexter-amc-bas:AMC X412B BAS (amc_integration.py)"
    "dexter-nvr-hikvision:Hikvision NVR Poller (xml_parsing3.py)"
    "dexter-nvr-hikvision-field:Hikvision Alert Stream (xml_parsing_field_log.py)"
    "dexter-nvr-hikvision-bacs:Hikvision Biometric BACS (hikvision1_biometric_14.py)"
    "dexter-nvr-dahua:Dahua NVR Poller (dahua_nvr_dvr_information.py)"
    "dexter-nvr-cpplus:CP Plus NVR Poller (cp_plus_nvr_dvr_information.py)"
    "dexter-exporter:Prometheus Debug Exporter (dexter_debug_exporter.py)"
)
for entry in "${BAS_SVCS[@]}"; do
    svc="${entry%%:*}"
    desc="${entry#*:}"
    state=$(systemctl is-active "$svc" 2>/dev/null)
    if [ "$state" = "active" ]; then
        ok "$svc  —  $desc"
        ((PASS++))
    elif [ "$state" = "inactive" ]; then
        warn "$svc  INACTIVE  (disabled or not configured)"
        # inactive BAS is not a failure — depends on site config
    else
        fail "$svc  $state  —  $desc"
        ((FAIL++))
    fi
done

# ── 4. Key Files & Databases ─────────────────────────────────────────────────
hdr "4. Key Files & Databases"
FILES=(
    "/home/pi/Test3/device_config.db:device_config.db (credentials)"
    "/home/pi/Test3/payloads.db:payloads.db (TB queue)"
    "/home/pi/Test3/logical_params_active_integration.db:active_integration.db"
    "/home/pi/Test3/TLChronosProMAIN_391.py:TLChronosProMAIN_391.py"
    "/home/pi/Test3/hikvision_bas_integration.py:hikvision_bas_integration.py"
    "/home/pi/Test3/location_manager.py:location_manager.py"
    "/home/pi/Test3/imei_manager.py:imei_manager.py"
    "/home/pi/Test3/auto_ip_scanner.py:auto_ip_scanner.py"
    "/home/pi/Test3/webserver/seple.py:seple.py (webserver)"
    "/home/pi/Test3/webserver/templates/integrationSettings.html:integrationSettings.html"
    "/etc/dexter/fernet.key:fernet.key (encryption key)"
    "/home/pi/Test3/scan_status.json:scan_status.json (auto-created on first scan)"
)
for entry in "${FILES[@]}"; do
    path="${entry%%:*}"
    label="${entry#*:}"
    if [ -f "$path" ]; then
        size=$(du -h "$path" 2>/dev/null | cut -f1)
        ok "$label  ($size)"
        ((PASS++))
    else
        # scan_status.json is created at runtime — just warn
        if [[ "$path" == *"scan_status.json"* ]]; then
            warn "$label  not yet created (normal — created on first scan)"
        else
            fail "$label  MISSING at $path"
            ((FAIL++))
        fi
    fi
done

# ── 5. Network ────────────────────────────────────────────────────────────────
hdr "5. Network"
# wlan0 / eth0 IP
ETH_IP=$(ip addr show eth0 2>/dev/null | grep "inet " | awk '{print $2}' | cut -d/ -f1)
WLAN_IP=$(ip addr show wlan0 2>/dev/null | grep "inet " | awk '{print $2}' | cut -d/ -f1)

if [ -n "$ETH_IP" ]; then
    ok "eth0  IP: $ETH_IP"
    ((PASS++))
else
    warn "eth0  No IP assigned"
fi

if [ -n "$WLAN_IP" ]; then
    ok "wlan0 IP: $WLAN_IP"
    ((PASS++))
else
    warn "wlan0 No IP assigned"
fi

# Webserver port 5001
if ss -tlnp 2>/dev/null | grep -q ":5001"; then
    ok "Port 5001 listening (webserver)"
    ((PASS++))
else
    fail "Port 5001 NOT listening — webserver may be down"
    ((FAIL++))
fi

# ThingsBoard connectivity (non-fatal)
if ping -c 1 -W 3 thingsboard.cloud &>/dev/null; then
    ok "ThingsBoard cloud reachable"
    ((PASS++))
else
    warn "ThingsBoard cloud unreachable (check SIM/WiFi/LAN)"
fi

# ── 6. Storage ────────────────────────────────────────────────────────────────
hdr "6. Storage"
DISK_USE=$(df -h / 2>/dev/null | awk 'NR==2{print $5}' | tr -d '%')
DISK_AVAIL=$(df -h / 2>/dev/null | awk 'NR==2{print $4}')
if [ -n "$DISK_USE" ] && [ "$DISK_USE" -lt 85 ]; then
    ok "Root disk: ${DISK_USE}% used  (${DISK_AVAIL} free)"
    ((PASS++))
elif [ -n "$DISK_USE" ]; then
    warn "Root disk: ${DISK_USE}% used  (${DISK_AVAIL} free) — getting full"
    ((FAIL++))
fi

# payloads.db size check — if >50MB something is stuck
PAYLOAD_SIZE=$(du -m /home/pi/Test3/payloads.db 2>/dev/null | cut -f1)
if [ -n "$PAYLOAD_SIZE" ]; then
    if [ "$PAYLOAD_SIZE" -lt 50 ]; then
        ok "payloads.db: ${PAYLOAD_SIZE} MB"
        ((PASS++))
    else
        warn "payloads.db: ${PAYLOAD_SIZE} MB — large, MQTT publisher may be stuck"
        ((FAIL++))
    fi
fi

# ── 7. CPU & RAM ──────────────────────────────────────────────────────────────
hdr "7. CPU & RAM"
CPU_TEMP=$(vcgencmd measure_temp 2>/dev/null | cut -d= -f2)
CPU_LOAD=$(top -bn1 2>/dev/null | grep "Cpu(s)" | awk '{print $2}' | cut -d. -f1)
MEM_USE=$(free | awk '/Mem/{printf "%.0f", $3/$2*100}')
MEM_AVAIL=$(free -h | awk '/Mem/{print $7}')

[ -n "$CPU_TEMP" ] && info "CPU temp: $CPU_TEMP"
[ -n "$CPU_LOAD" ] && info "CPU load: ~${CPU_LOAD}%"
[ -n "$MEM_USE"  ] && info "RAM used: ${MEM_USE}%  (${MEM_AVAIL} available)"

if [ -n "$CPU_TEMP" ]; then
    TEMP_VAL=$(echo "$CPU_TEMP" | tr -d "'C°")
    if (( $(echo "$TEMP_VAL > 75" | bc -l 2>/dev/null || echo 0) )); then
        warn "CPU temperature high: $CPU_TEMP"
    fi
fi

# ── 8. Recent Errors (last boot) ─────────────────────────────────────────────
hdr "8. Recent Service Errors (since last boot)"
ERR_COUNT=$(journalctl -b --priority=err --no-pager -q 2>/dev/null | \
    grep -c "dexter-" 2>/dev/null || echo 0)
if [ "$ERR_COUNT" -eq 0 ]; then
    ok "No dexter-* errors since last boot"
    ((PASS++))
else
    warn "$ERR_COUNT error(s) in dexter-* services since boot — check with autorun4.py logs"
    ((FAIL++))
    # Show last 5 errors
    echo ""
    journalctl -b --priority=err --no-pager -q 2>/dev/null | \
        grep "dexter-" | tail -5 | while read line; do
        echo -e "    ${DIM}$line${RESET}"
    done
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}============================================================"
echo "  DIAGNOSIS SUMMARY"
echo -e "============================================================${RESET}"
echo -e "  ${GREEN}Passed : $PASS${RESET}"
if [ "$FAIL" -gt 0 ]; then
    echo -e "  ${RED}Failed : $FAIL${RESET}"
    echo ""
    echo -e "  ${YELLOW}Action: Run autorun4.py and check failed services.${RESET}"
else
    echo -e "  ${GREEN}Failed : 0  —  All checks passed ✓${RESET}"
fi
echo ""

#!/bin/bash
# gen_device_cert.sh — Generate X.509 client certificate for one Dexter Pi
#
# Usage (run on development machine, NOT on Pi):
#   ./docker/gen_device_cert.sh <DEVICE_NAME> [CA_DIR]
#
#   DEVICE_NAME : must match exactly the device_name in modem_config.db
#                 (e.g. SEPL-DX2, SEPL-DX4)
#   CA_DIR      : directory containing fleet-ca.key + fleet-ca.crt
#                 default: ./certs-ca  (output of gen_fleet_ca.sh)
#
# Output (in ./certs-out/<DEVICE_NAME>/):
#   device.key  — device private key  (scp to Pi → /home/pi/Test3/certs/)
#   device.crt  — device client cert  (scp to Pi → /home/pi/Test3/certs/)
#
# Also copies the server CA cert (ca.crt) from the repo root to the output
# so you can scp the whole directory to the Pi in one command.
#
# Deployment to Pi:
#   scp -r ./certs-out/<DEVICE_NAME>/. pi@<PI_IP>:/home/pi/Test3/certs/
#   ssh pi@<PI_IP> "chmod 600 /home/pi/Test3/certs/device.key"
#   ssh pi@<PI_IP> "docker restart dexter-mqtt"
#
# ThingsBoard activation (once fleet-ca.crt is registered as trusted CA):
#   Automatic — ThingsBoard auto-provisions the device on first mTLS connect
#   if the device name (CN) matches an existing device in ThingsBoard.
#   If device doesn't exist yet, ThingsBoard creates it automatically.
#
# WARNING: Do NOT change ThingsBoard device credential type to "X.509 Certificate"
# until SerialCommunication.py (C16QS AT+MQTTSCONN path) also supports client
# cert loading. Until then, dexter-mqtt uses X.509 when certs are present, but
# the C16QS MQTT path stays on MQTT Basic — so keep ThingsBoard on MQTT Basic.
# See bottom of this file for the final activation checklist.

set -euo pipefail

DEVICE_NAME="${1:-}"
CA_DIR="${2:-./certs-ca}"
DAYS=1825  # 5 years

if [ -z "$DEVICE_NAME" ]; then
    echo "Usage: $0 <DEVICE_NAME> [CA_DIR]"
    echo "  DEVICE_NAME must match device_name in modem_config.db exactly."
    exit 1
fi

CA_KEY="$CA_DIR/fleet-ca.key"
CA_CRT="$CA_DIR/fleet-ca.crt"

if [ ! -f "$CA_KEY" ] || [ ! -f "$CA_CRT" ]; then
    echo "ERROR: Fleet CA not found in $CA_DIR"
    echo "       Run docker/gen_fleet_ca.sh first."
    exit 1
fi

OUTDIR="./certs-out/$DEVICE_NAME"
mkdir -p "$OUTDIR"
chmod 700 "$OUTDIR"

echo "Generating device certificate for: $DEVICE_NAME"

# Device private key (2048-bit RSA — balance of security and modem compatibility)
openssl genrsa -out "$OUTDIR/device.key" 2048
chmod 600 "$OUTDIR/device.key"

# Certificate Signing Request — CN must match ThingsBoard device name
openssl req -new \
    -key "$OUTDIR/device.key" \
    -out "$OUTDIR/device.csr" \
    -subj "/C=IN/ST=Maharashtra/L=Mumbai/O=SEPLE/OU=Dexter HMS/CN=$DEVICE_NAME"

# Sign with fleet CA
EXTFILE="$OUTDIR/device.ext"
printf "subjectAltName=DNS:%s\nextendedKeyUsage=clientAuth" "$DEVICE_NAME" > "$EXTFILE"
openssl x509 -req \
    -in "$OUTDIR/device.csr" \
    -CA "$CA_CRT" \
    -CAkey "$CA_KEY" \
    -CAcreateserial \
    -out "$OUTDIR/device.crt" \
    -days $DAYS \
    -sha256 \
    -extfile "$EXTFILE"
rm -f "$EXTFILE"

# Clean up CSR — not needed after signing
rm -f "$OUTDIR/device.csr"

echo ""
echo "Device certificate generated:"
openssl x509 -in "$OUTDIR/device.crt" -text -noout | grep -E "Subject:|Not Before:|Not After :|Issuer:"
echo ""
echo "Files in $OUTDIR (only device.crt + device.key needed on Pi):"
ls -la "$OUTDIR/"
echo ""
echo "Deploy to Pi:"
echo "  ssh pi@<PI_IP> 'mkdir -p /home/pi/Test3/certs'"
echo "  scp $OUTDIR/device.crt $OUTDIR/device.key pi@<PI_IP>:/home/pi/Test3/certs/"
echo "  ssh pi@<PI_IP> \"chmod 600 /home/pi/Test3/certs/device.key\""
echo "  ssh pi@<PI_IP> \"docker restart dexter-mqtt\""
echo ""
echo "──────────────────────────────────────────────────────────────────"
echo "ACTIVATION CHECKLIST (when C16QS client cert support is confirmed):"
echo "  1. [ ] C16QS AT commands confirmed for client cert loading"
echo "  2. [ ] SerialCommunication.py updated to load device.crt + device.key"
echo "  3. [ ] fleet-ca.crt registered in ThingsBoard as trusted CA"
echo "  4. [ ] ThingsBoard device credential type changed to 'X.509 Certificate'"
echo "  5. [ ] Both dexter-mqtt and dexter-serial-comm restarted on Pi"
echo "  6. [ ] Verified data flow on both Ethernet and GSM paths"
echo "──────────────────────────────────────────────────────────────────"
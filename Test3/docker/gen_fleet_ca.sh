#!/bin/bash
# gen_fleet_ca.sh — Generate Dexter Fleet CA (run ONCE, keep key offline)
#
# Output (in ./certs-ca/):
#   fleet-ca.key  — CA private key. KEEP OFFLINE. Never push to git / ECR.
#   fleet-ca.crt  — CA certificate. Upload to ThingsBoard as trusted CA.
#
# ThingsBoard setup (done once, not per device):
#   1. In ThingsBoard UI → Device Profiles → select your profile
#      → "Device provisioning" tab → set "Allow create new devices by …"
#      → upload fleet-ca.crt as the trusted CA certificate.
#   2. For each device: run gen_device_cert.sh — ThingsBoard auto-provisions
#      the device on first connection by matching cert CN to device name.
#
# DO NOT run this again after fleet devices are provisioned — the fleet-ca.crt
# registered in ThingsBoard would become invalid, breaking all devices.

set -euo pipefail

OUTDIR="./certs-ca"
CA_KEY="$OUTDIR/fleet-ca.key"
CA_CRT="$OUTDIR/fleet-ca.crt"
DAYS=3650  # 10 years

mkdir -p "$OUTDIR"
chmod 700 "$OUTDIR"

if [ -f "$CA_KEY" ]; then
    echo "ERROR: $CA_KEY already exists. Fleet CA already generated."
    echo "       To regenerate (breaks all existing device certs), delete $OUTDIR first."
    exit 1
fi

echo "Generating Dexter Fleet CA..."

# Generate 4096-bit RSA CA key
openssl genrsa -out "$CA_KEY" 4096
chmod 600 "$CA_KEY"

# Self-signed CA certificate
openssl req -new -x509 \
    -key "$CA_KEY" \
    -out "$CA_CRT" \
    -days $DAYS \
    -subj "/C=IN/ST=Maharashtra/L=Mumbai/O=SEPLE/OU=Dexter Fleet/CN=Dexter Fleet CA" \
    -extensions v3_ca \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash"

echo ""
echo "Fleet CA generated:"
echo "  Key : $CA_KEY   ← KEEP OFFLINE. Never commit. Never copy to Pi."
echo "  Cert: $CA_CRT   ← Upload to ThingsBoard as trusted CA cert."
echo ""
openssl x509 -in "$CA_CRT" -text -noout | grep -E "Subject:|Not Before:|Not After :"
echo ""
echo "Next: run docker/gen_device_cert.sh <DEVICE_NAME> to create per-device certs."
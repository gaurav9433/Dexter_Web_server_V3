#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
provision_device_x509.py — Dexter HMS
Configure ThingsBoard device credentials for X.509 mTLS authentication.

For each device listed:
  1. Reads the device certificate from certs-out/<DEVICE_NAME>/device.crt
  2. Computes its SHA-256 fingerprint (ThingsBoard's credential ID)
  3. Switches the device's ThingsBoard credential type to X509_CERTIFICATE

Usage (run from the Test3/ directory or docker/ directory):
    python3 docker/provision_device_x509.py \
        --email admin@seple.in \
        --password <your_password> \
        --devices SEPL-DX2 SEPL-DX4

    # Dry run (no writes):
    python3 docker/provision_device_x509.py \
        --email admin@seple.in \
        --password <your_password> \
        --dry-run

    # Self-hosted ThingsBoard:
    python3 docker/provision_device_x509.py \
        --url http://192.168.1.100:8080 \
        --email tenant@example.com \
        --password secret \
        --devices SEPL-DX2 SEPL-DX4

After this script succeeds, two manual steps remain:
  1. Upload certs-ca/fleet-ca.crt to ThingsBoard as a trusted CA certificate
     (ThingsBoard UI → Security → Settings → Certificate Authority or
      Device Profiles → <profile> → Device provisioning → Certificate)
  2. Deploy device certs to each Pi, then restart the MQTT service
     (see docker/gen_device_cert.sh deployment section for exact commands)

Dependencies (already in requirements.txt): requests, cryptography
"""

import sys
import json
import argparse
import logging
from pathlib import Path

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Resolve certs-out/ relative to this script's location (docker/ → Test3/certs-out/)
_SCRIPT_DIR  = Path(__file__).resolve().parent
_CERTS_OUT   = _SCRIPT_DIR.parent / "certs-out"
_FLEET_CA    = _SCRIPT_DIR.parent / "certs-ca" / "fleet-ca.crt"

_DEFAULT_URL      = "https://www.dexterhms.com"
_DEFAULT_DEVICES  = ["SEPL-DX2", "SEPL-DX4"]
_TIMEOUT          = 20  # seconds for each HTTP call


# ── ThingsBoard REST helpers ───────────────────────────────────────────────────

def tb_login(base_url: str, email: str, password: str) -> str:
    """Authenticate and return a JWT bearer token."""
    resp = requests.post(
        f"{base_url}/api/auth/login",
        json={"username": email, "password": password},
        timeout=_TIMEOUT,
    )
    _raise_for_status(resp, "login")
    token = resp.json()["token"]
    log.info("Authenticated to ThingsBoard at %s", base_url)
    return token


def tb_get_device(base_url: str, hdrs: dict, device_name: str) -> dict:
    """Return the ThingsBoard device object for the given name, or raise."""
    resp = requests.get(
        f"{base_url}/api/tenant/devices",
        params={"pageSize": 20, "page": 0, "deviceName": device_name},
        headers=hdrs,
        timeout=_TIMEOUT,
    )
    _raise_for_status(resp, f"get device '{device_name}'")

    matches = resp.json().get("data", [])
    device  = next((d for d in matches if d["name"] == device_name), None)
    if device is None:
        names = [d["name"] for d in matches]
        raise ValueError(
            f"Device '{device_name}' not found in ThingsBoard "
            f"(search returned: {names or 'nothing'})"
        )
    log.info("[%s] found — device id: %s", device_name, device["id"]["id"])
    return device


def tb_get_credentials(base_url: str, hdrs: dict, device_id: str) -> dict:
    """Return the current credential object for a device."""
    resp = requests.get(
        f"{base_url}/api/device/{device_id}/credentials",
        headers=hdrs,
        timeout=_TIMEOUT,
    )
    _raise_for_status(resp, f"get credentials for device {device_id}")
    return resp.json()


def tb_update_credentials_x509(
    base_url: str,
    hdrs: dict,
    current_creds: dict,
    fingerprint: str,
    cert_pem: str,
    dry_run: bool,
) -> None:
    """
    Update device credentials to X509_CERTIFICATE.

    credentialsId  — SHA-256 fingerprint of device.crt (hex, 64 chars).
                     This is what ThingsBoard computes from the presented cert
                     during the TLS handshake to look up the device.
    credentialsValue — full cert PEM stored for display in the ThingsBoard UI.
    """
    payload = {
        "id":              current_creds.get("id"),
        "deviceId":        current_creds.get("deviceId"),
        "credentialsType": "X509_CERTIFICATE",
        "credentialsId":   fingerprint,
        "credentialsValue": cert_pem.strip(),
    }

    if dry_run:
        log.info("[dry-run] would POST /api/device/credentials:\n%s",
                 json.dumps(payload, indent=2))
        return

    resp = requests.post(
        f"{base_url}/api/device/credentials",
        json=payload,
        headers=hdrs,
        timeout=_TIMEOUT,
    )
    _raise_for_status(resp, "update credentials")
    log.info("Credentials updated to X509_CERTIFICATE")


def _raise_for_status(resp: requests.Response, context: str) -> None:
    if not resp.ok:
        raise RuntimeError(
            f"ThingsBoard API error during '{context}': "
            f"HTTP {resp.status_code} — {resp.text[:300]}"
        )


# ── Certificate helpers ────────────────────────────────────────────────────────

def cert_sha256_fingerprint(pem: str) -> str:
    """
    Return the SHA-256 fingerprint of a PEM certificate as a 64-char lowercase
    hex string (no colons/spaces). This is the credentialsId format ThingsBoard
    uses internally when matching a client certificate to a device.
    """
    cert = x509.load_pem_x509_certificate(pem.encode())
    raw  = cert.fingerprint(hashes.SHA256())
    return raw.hex()


def cert_subject_cn(pem: str) -> str:
    """Return the CN of the certificate's subject."""
    cert = x509.load_pem_x509_certificate(pem.encode())
    attrs = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
    return attrs[0].value if attrs else "(no CN)"


# ── Per-device configuration ───────────────────────────────────────────────────

def configure_device(
    base_url: str,
    hdrs: dict,
    device_name: str,
    dry_run: bool,
) -> bool:
    """
    Load this device's cert, compute its fingerprint, and update ThingsBoard.
    Returns True on success, False on any error.
    """
    cert_path = _CERTS_OUT / device_name / "device.crt"
    if not cert_path.exists():
        log.error(
            "[%s] device.crt not found at %s\n"
            "         Run docker/gen_device_cert.sh %s first.",
            device_name, cert_path, device_name,
        )
        return False

    cert_pem    = cert_path.read_text()
    fingerprint = cert_sha256_fingerprint(cert_pem)
    cn          = cert_subject_cn(cert_pem)

    log.info("[%s] cert CN            : %s", device_name, cn)
    log.info("[%s] SHA-256 fingerprint: %s", device_name, fingerprint)

    if cn != device_name:
        log.warning(
            "[%s] cert CN '%s' does not match device name — "
            "ThingsBoard will not auto-provision by CN match",
            device_name, cn,
        )

    try:
        device       = tb_get_device(base_url, hdrs, device_name)
        device_id    = device["id"]["id"]
        current_creds = tb_get_credentials(base_url, hdrs, device_id)

        current_type = current_creds.get("credentialsType", "unknown")
        log.info("[%s] current credential type: %s", device_name, current_type)

        if current_type == "X509_CERTIFICATE":
            current_fp = current_creds.get("credentialsId", "")
            if current_fp == fingerprint:
                log.info("[%s] already up to date — no change needed", device_name)
                return True
            log.info("[%s] updating fingerprint (was %s...)", device_name, current_fp[:16])

        tb_update_credentials_x509(
            base_url, hdrs, current_creds, fingerprint, cert_pem, dry_run
        )
        log.info("[%s] DONE", device_name)
        return True

    except Exception as exc:
        log.error("[%s] FAILED: %s", device_name, exc)
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Switch Dexter device credentials in ThingsBoard to X.509 Certificate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--url",
        default=_DEFAULT_URL,
        help=f"ThingsBoard base URL (default: {_DEFAULT_URL})",
    )
    parser.add_argument("--email",    required=True, help="ThingsBoard account email")
    parser.add_argument("--password", required=True, help="ThingsBoard account password")
    parser.add_argument(
        "--devices",
        nargs="+",
        default=_DEFAULT_DEVICES,
        metavar="DEVICE_NAME",
        help=f"Device names to configure (default: {' '.join(_DEFAULT_DEVICES)})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read-only mode: print what would be sent but do not update ThingsBoard",
    )
    args = parser.parse_args()

    if args.dry_run:
        log.info("DRY RUN — no changes will be made to ThingsBoard")

    # ── Preflight: cert file check ───────────────────────────────────────────
    missing = [d for d in args.devices if not (_CERTS_OUT / d / "device.crt").exists()]
    if missing:
        log.error(
            "Missing device certs for: %s\n"
            "  Run:  docker/gen_device_cert.sh <DEVICE_NAME>  for each missing device",
            ", ".join(missing),
        )
        sys.exit(1)

    # ── Authenticate ─────────────────────────────────────────────────────────
    try:
        token = tb_login(args.url, args.email, args.password)
    except Exception as exc:
        log.error("Login failed: %s", exc)
        sys.exit(1)

    hdrs = {
        "X-Authorization": f"Bearer {token}",
        "Content-Type":    "application/json",
    }

    # ── Configure each device ────────────────────────────────────────────────
    results: dict[str, bool] = {}
    for device_name in args.devices:
        print()
        log.info("── %s ──────────────────────────────────", device_name)
        results[device_name] = configure_device(args.url, hdrs, device_name, args.dry_run)

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print("─" * 52)
    print("Summary")
    print("─" * 52)
    for name, ok in results.items():
        mark = "OK    " if ok else "FAILED"
        print(f"  {mark}  {name}")

    print()
    print("─" * 52)
    print("Next steps")
    print("─" * 52)
    print()
    print("  1. Upload fleet-ca.crt to ThingsBoard (manual — UI only):")
    print(f"       File: {_FLEET_CA}")
    print("       ThingsBoard UI path:")
    print("         → Security → Settings → Certificate → Upload CA certificate")
    print("         or Device Profiles → <profile> → Device Provisioning → CA Certificate")
    print()
    print("  2. For each Pi (replace <DEVICE> and <PI_IP>):")
    print("       ssh pi@<PI_IP> 'mkdir -p /home/pi/Test3/certs'")
    print("       scp certs-out/<DEVICE>/device.crt certs-out/<DEVICE>/device.key \\")
    print("           pi@<PI_IP>:/home/pi/Test3/certs/")
    print("       ssh pi@<PI_IP> 'chmod 600 /home/pi/Test3/certs/device.key'")
    print()
    print("  3. Flip _X509_CONN_ENABLED = True in SerialCommunication.py")
    print()
    print("  4. Restart services on each Pi:")
    print("       ssh pi@<PI_IP> 'sudo systemctl restart dexter-mqtt dexter-serial-comm'")

    failed = [n for n, ok in results.items() if not ok]
    if failed:
        print(f"\nFailed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
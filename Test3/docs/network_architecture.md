# Dexter HMS — Network & Data Architecture

---

## Two Network Modes (user-controlled via LCD/webserver)

---

## Mode A — GSM Primary (`network_type = 'gsm'` in DB)

> Used when Pi has static broadband ethernet but user deliberately chooses c16qs for data.

| Component | Behaviour |
|---|---|
| **SerialCommunication.py** (dexter-serial-comm) | ALWAYS running. Sends telemetry to ThingsBoard via AT+MQTTPUBLM (Cavli C16QS modem, MQTT Basic auth: `client_id` / `user_name` / `password`) |
| **dexter-mqtt** | Reads `'gsm'` from DB on startup → exits(0) cleanly. Not restarted (restart policy: on-failure; clean exit is not a failure). |
| **Failover monitor** | NOT started. Only started when DB = `'ethernet'`. |
| **OTA (2 AM daily)** | Reads `network_type='gsm'` → pon c16qs → docker pull → 90s Prometheus remote_write flush → poff c16qs → serial re-opens → AT+MQTT resumes automatically. |

No automatic failover to ethernet — user chose GSM intentionally.

---

## Mode B — Ethernet Primary (`network_type = 'ethernet'` in DB)

> Used when Pi has dynamic broadband (DHCP) and user wants broadband as primary.

| Component | Behaviour |
|---|---|
| **dexter-mqtt** | Running. Sends telemetry via paho-mqtt over eth0 to `thingsboard.cloud:8883`. Auth: X.509 mTLS (see below). |
| **SerialCommunication.py** (dexter-serial-comm) | ALWAYS running in parallel. Always sending via AT+MQTTPUBLM (MQTT Basic). Acts as permanent background data path regardless of ethernet state. |
| **Failover monitor** | Running. Checks eth0 connectivity every 30 seconds. |
| **OTA (2 AM daily)** | Reads `network_type='ethernet'` → pulls over eth0 directly. No pon/poff needed. |

No pon/poff in the automatic failover path — ppp0 is never brought up during failover; AT+MQTT works uninterrupted throughout.

---

### Failover Events (Mode B)

| Event | What happens |
|---|---|
| **eth0 loses internet** | Monitor detects ping failure → sets DB `'gsm'` + `_failover_gsm_active=True` → inserts `network_event{status:"over_gsm"}` telemetry. dexter-mqtt's next publish fails → `_reset_connection()` → container exits(0) (on-failure policy does not restart a clean exit). SerialCommunication.py (always running, always connected to C16QS modem) becomes sole ThingsBoard sender via AT+MQTTPUBLM. |
| **eth0 restored** | Monitor detects ping success + `_failover_gsm_active=True` → sets DB `'ethernet'` + `_failover_gsm_active=False` → inserts `network_event{status:"over_ethernet"}` telemetry → restarts dexter-mqtt via Docker socket API (`/containers/dexter-mqtt/restart?t=5`). dexter-mqtt reads `'ethernet'` from DB → connects to ThingsBoard. |

**Telemetry during changeover** — both failover directions insert a `network_event` payload into `payloads.db` immediately at the moment of the switch, so the changeover timestamp is sent to ThingsBoard via the active path (GSM on failover, ethernet on restore).

---

### Failover Monitor — How It Works

`_run_failover_monitor()` in `TLChronosProMAIN_391.py` (line 21185). Runs as a daemon thread, started only when `network_type == 'ethernet'` at dexter-core startup (line 22200).

**Detection method — `_eth0_has_connectivity()`:**
1. Checks `ip addr show eth0` (via `nsenter -t 1 -m -n`) — if no `inet` address, returns False immediately.
2. Pings `8.8.8.8` with `-I eth0 -c 1 -W 3` (host network namespace) — returns True only if ping succeeds.

This checks **actual internet reachability**, not just whether eth0 has an IP. Static vs DHCP makes no difference — the monitor only cares whether 8.8.8.8 is reachable.

**Poll interval:** 30 seconds.

**State variable:** `_failover_gsm_active` (module-level bool). Prevents repeated DB writes on consecutive failures.

---

### Static vs Dynamic Ethernet — Behaviour Matrix

The `static_or_dynamic` setting (stored in `network_settings.db`) controls how eth0 gets its IP. It has **no direct effect on the data path** — the failover monitor uses `_eth0_has_connectivity()` (real ping) to decide, not the IP assignment method.

| eth0 config | Internet on eth0? | Data path | Failover behaviour |
|---|---|---|---|
| Dynamic (DHCP) | Yes | dexter-mqtt (ethernet) | Monitor idle; GSM is hot standby |
| Dynamic (DHCP) | No | SerialCommunication.py (GSM) | Monitor detects → GSM; restores to ethernet when ping succeeds |
| Static | Yes | dexter-mqtt (ethernet) | Same as Dynamic+internet — failover to GSM and back works identically |
| Static | No | SerialCommunication.py (GSM) | Monitor detects → GSM; ping never succeeds → stays GSM permanently; no restore to ethernet |

---

## Authentication — ThingsBoard

| Path | Transport | Auth method | Status |
|---|---|---|---|
| dexter-mqtt (Ethernet) | paho-mqtt → TCP/TLS → `thingsboard.cloud:8883` | **X.509 mTLS** (client cert) | Active when certs deployed |
| SerialCommunication.py (GSM) | Cavli C16QS AT+MQTTPUBLM → cellular | **MQTT Basic** (`client_id` / `user_name` / `password`) | Always active |
| SerialCommunication.py X.509 | — | — | **BLOCKED** — C16QS firmware has no client cert AT commands. Awaiting Cavli Wireless support. |

> `access_token` is retained in `thingsboard_mqtt_publisher.py` code for future use but is not part of the active production flow.

---

## X.509 mTLS — How It Works

`thingsboard_mqtt_publisher.py` auto-detects certs on startup:

- If `/home/pi/Test3/certs/device.crt` + `device.key` are present → connects via TLS with client cert (mTLS)
- No separate CA file needed — `thingsboard.cloud` is Let's Encrypt signed; Pi system trust store handles server cert verification

ThingsBoard device credential type must be set to **X.509** (not Access Token) for mTLS to be accepted.

---

## X.509 — Activation Steps (per device, post fleet rollout)

> **Note:** On Windows, always run cert scripts with `MSYS_NO_PATHCONV=1` to prevent Git Bash from mangling the OpenSSL subject string.

### Step 1 — Generate fleet CA (one-time, already done 2026-05-22)

```bash
MSYS_NO_PATHCONV=1 bash docker/gen_fleet_ca.sh
```

| Output | Location | Action |
|---|---|---|
| `fleet-ca.key` | `certs-ca/fleet-ca.key` | Keep offline. Never commit. Never copy to Pi. |
| `fleet-ca.crt` | `certs-ca/fleet-ca.crt` | Upload to ThingsBoard as trusted CA (once, when activating). |

**Status: DONE** — generated 2026-05-22, valid until 2036-05-19.

---

### Step 2 — Generate device cert per Pi (already done 2026-05-22)

```bash
MSYS_NO_PATHCONV=1 bash docker/gen_device_cert.sh SEPL-DX2
MSYS_NO_PATHCONV=1 bash docker/gen_device_cert.sh SEPL-DX4
```

| Device | cert | key | Valid until |
|---|---|---|---|
| SEPL-DX2 | `certs-out/SEPL-DX2/device.crt` | `certs-out/SEPL-DX2/device.key` | 2031-05-21 |
| SEPL-DX4 | `certs-out/SEPL-DX4/device.crt` | `certs-out/SEPL-DX4/device.key` | 2031-05-21 |

**Status: DONE** — generated 2026-05-22. Stored locally. Not yet deployed to Pis.

---

### Step 3 — Deploy certs to Pi (PENDING — blocked on C16QS)

```bash
# Per Pi — run when C16QS X.509 support is confirmed
ssh pi@PI_IP "mkdir -p /home/pi/Test3/certs"
scp certs-out/DEVICE_NAME/device.crt certs-out/DEVICE_NAME/device.key pi@PI_IP:/home/pi/Test3/certs/
ssh pi@PI_IP "chmod 600 /home/pi/Test3/certs/device.key"
ssh pi@PI_IP "docker restart dexter-mqtt"
```

---

### Step 4 — ThingsBoard activation (PENDING — blocked on C16QS)

**Do NOT activate until all checklist items are complete:**

- [ ] C16QS AT commands confirmed for client cert loading (awaiting Cavli Wireless)
- [ ] `SerialCommunication.py` updated to load `device.crt` + `device.key` via AT commands
- [ ] `fleet-ca.crt` registered in ThingsBoard as trusted CA
- [ ] ThingsBoard device credential type changed to **X.509 Certificate** (for both DX2 and DX4)
- [ ] Both `dexter-mqtt` and `dexter-serial-comm` restarted on each Pi
- [ ] Verified data flow on both Ethernet (X.509) and GSM paths

---

## ppp0 (pon c16qs) Usage — Explicit List

ppp0 is brought up **only** in two places:

1. **`ota_update.sh`** when `network_type='gsm'` (daily, 2 AM) — brief window for docker pull + Prometheus remote_write flush
2. **`check_and_send()`** in `SerialCommunication.py` — brief window for config sync when `network_type='gsm'`

ppp0 is **never** brought up in:
- The automatic failover monitor
- dexter-mqtt startup or shutdown
- Any LCD/webserver action

---

## Data Flow Summary

```
                      ┌──────────────────────────────────────────┐
                      │              ThingsBoard Cloud            │
                      │           thingsboard.cloud:8883         │
                      └────────────────┬─────────────────────────┘
                                       │
              ┌────────────────────────┴──────────────────────┐
              │                                               │
   X.509 mTLS (eth0)                             MQTT Basic (cellular)
   paho-mqtt TCP/TLS                             AT+MQTTPUBLM via C16QS
              │                                               │
     ┌────────┴──────────┐                       ┌───────────┴───────────┐
     │   dexter-mqtt     │                       │  SerialCommunication  │
     │  (Ethernet mode   │                       │  (always running,     │
     │   only; exits(0)  │                       │   both modes)         │
     │   in GSM mode)    │                       │                       │
     └───────────────────┘                       └───────────────────────┘
              │                                               │
         eth0 / broadband                          Cavli C16QS modem
                                                      cellular
```

---

*Last updated: 2026-05-22 (failover logic + static/dynamic matrix added)*

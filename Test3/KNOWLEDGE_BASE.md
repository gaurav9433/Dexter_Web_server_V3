# Dexter HMS Edge Agent — Knowledge Base

> **Auto-updated on every push to `main`.**
> Last section "Recent Changes" is maintained automatically by CI.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Repository Structure](#2-repository-structure)
3. [Architecture Overview](#3-architecture-overview)
4. [Docker Microservices](#4-docker-microservices)
5. [Core Python Modules](#5-core-python-modules)
6. [Integration Modules](#6-integration-modules)
7. [Webserver](#7-webserver)
8. [Database Schema](#8-database-schema)
9. [Configuration & Secrets](#9-configuration--secrets)
10. [CI/CD Pipeline](#10-cicd-pipeline)
11. [Infrastructure](#11-infrastructure)
12. [Security Hardening](#12-security-hardening)
13. [Deployment Workflow](#13-deployment-workflow)
14. [Observability](#14-observability)
15. [Recent Changes](#15-recent-changes)

---

## 1. Project Overview

**Dexter HMS** (Hardware Management System) is an edge computing platform running on Raspberry Pi 4 (ARM64) deployed at bank branch locations. Each Pi manages:

- Security intrusion panel monitoring (alarms, zones, partitions)
- NVR/DVR device integration (Hikvision, Dahua, CP Plus)
- BAS panel integration (AMC X412V, Texecom, DSC Neo, Hikvision BAS)
- Cellular modem management (Cavli GSM)
- Cloud telemetry to ThingsBoard via MQTT/TLS
- Fleet management via Portainer Edge Agent
- VPN access via Tailscale

**Scale:** 100 live bank branches. One bad OTA breaks all — hence the Docker-based microservices architecture with watchdogs, WAL databases, backoff logic, and fleet management.

**Stack:** Python 3.11 · SQLite (WAL) · Docker Compose · ThingsBoard Cloud · AWS ECR · Portainer CE · Tailscale · Flask HTTPS

---

## 2. Repository Structure

```
Test3/
├── TLChronosProMAIN_391.py     # Core HMS controller (GPIO, LCD, serial, panel state)
├── SerialCommunication.py      # Cavli GSM modem controller (AT commands, OTA)
├── serial_data_logger.py       # Analog sensor logger (panel current, battery voltage)
├── RPi_Task_Manager.py         # System health monitor (CPU, RAM, disk, temp)
├── thingsboard_mqtt_publisher.py # MQTT/TLS cloud publisher
├── dexter_debug_exporter.py    # Prometheus metrics exporter (port 8000)
├── db_connection.py            # Central SQLite factory (WAL, PRAGMAs, all DB paths)
├── secrets_manager.py          # /etc/dexter/.env loader + Fernet encryption
├── buffer_manager.py           # Bounded telemetry queue (50k rows, 7d TTL)
├── payload_manager.py          # MQTT backlog anti-flood (startup purge, offline cap)
├── database_handler.py         # Payload queue manager (payloads.db)
├── watchdog_manager.py         # Software watchdog (timeout → os.execl restart)
├── logical_params_module.py    # Integration feature flags (8 boolean params)
├── dexter_config.py            # settings.yaml loader + local overrides merge
├── settings.yaml               # All timeouts, poll intervals, DB paths, MQTT config
├── DeviceProvisioning_Module.py # First-run setup (network, MQTT, Portainer register)
├── Configure_Network_7.py      # Static IP configuration
├── reset_to_dhcp.py            # DHCP reset
├── tailscale_setup.py          # Tailscale VPN provisioning
├── credential_auth.py          # ThingsBoard RPC challenge-response auth
├── refreshcode.py              # Camera credential refresh / dexter_config publisher
├── Lan_setting.py              # Network init + portainer_register() auto-registration
├── auto_ip_scanner.py          # IP scanner for NVR/camera discovery
├── updatecode.py               # OTA code unpack + restart
├── ota_main_restore.py         # OTA failure rollback container
├── SDL_DS1307.py               # DS1307 I2C RTC chip driver
├── shiftRegister.py            # 74HC595 shift register driver (keypad/buzzer GPIO)
├── Adafruit_CharLCD.py         # 16x2 LCD driver (HD44780)
├── syslog_file_logger.py       # Dual-target logger (syslog + rotating file)
├── imei_manager.py             # IMEI reporting to ThingsBoard
├── location_manager.py         # GPS lat/lon reporting
├── docker-compose.yml          # 27-container microservices orchestration
├── Dockerfile                  # ARM64 multi-stage image build
├── requirements.txt            # Python dependencies (fully pinned)
├── .env.example                # Environment variable template
├── settings.yaml               # Centralised config (timeouts, intervals, paths)
├── qodana.yaml                 # JetBrains code quality scanning config
├── webserver/                  # Flask HTTPS web UI
│   ├── seple.py                # Main Flask app (port 5001, HTTPS)
│   ├── requirements.txt        # Webserver-specific deps
│   ├── cert.pem / key.pem      # TLS certificate (self-signed)
│   └── templates/              # HTML5 Jinja2 templates
├── .github/workflows/
│   ├── build-push-ecr.yml      # ARM64 Docker build + ECR push + security scans
│   ├── qodana_code_quality.yml # JetBrains Qodana static analysis
│   └── update-knowledge-base.yml # Auto-update this file on every push
└── daily_reports/              # Timestamped HTML/Markdown daily job reports
```

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Raspberry Pi 4 (ARM64)                       │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Docker Compose (27 containers)               │   │
│  │                                                          │   │
│  │  dexter-core ──────── GPIO, LCD, Serial, Panel state     │   │
│  │  dexter-webserver ─── Flask HTTPS :5001                  │   │
│  │  dexter-serial-comm ─ Cavli GSM modem / OTA              │   │
│  │  dexter-serial-logger  Analog sensors (current/voltage)  │   │
│  │  dexter-rpi-task ───── CPU/RAM/disk/temp monitor         │   │
│  │  dexter-exporter ───── Prometheus metrics :8000          │   │
│  │  dexter-mqtt ──────── MQTT/TLS → ThingsBoard :8883       │   │
│  │  dexter-ota-restore ── OTA rollback watchdog             │   │
│  │  portainer-agent ───── Fleet mgmt → 3.111.214.115:8000   │   │
│  │                                                          │   │
│  │  ── NVR INTEGRATIONS (restart: on-failure) ──            │   │
│  │  dexter-nvr-hikvision  dexter-nvr-dahua                  │   │
│  │  dexter-nvr-cpplus     dexter-hik-bas                    │   │
│  │  + 11 more NVR/BAS/RTC/SD containers                    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Shared volumes: /home/pi/Test3 (SQLite DBs + config)           │
│  Network: dexter-net bridge                                      │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
  ThingsBoard Cloud    Portainer Server     Tailscale VPN
  (MQTT/TLS :8883)   (EC2 :9443/:9000)   (Remote access)
                      3.111.214.115
```

**Key design decisions:**
- Single Docker image (`dexter-edge:latest`), multiple entry points — one build for all 27 services
- `restart: unless-stopped` for core services, `restart: on-failure` for integrations (exits cleanly with code 0 if disabled via feature flag)
- All containers share `/home/pi/Test3` via bind mount — SQLite databases persist across restarts
- WAL mode on all databases — readers never block writers
- Software watchdog in every long-running module — deadlocks trigger `os.execl()` restart

---

## 4. Docker Microservices

### Core Services (`restart: unless-stopped`)

| Container | Entry Point | Role |
|-----------|------------|------|
| `dexter-core` | `TLChronosProMAIN_391.py` | GPIO, LCD, I2C RTC, serial port, panel state machine |
| `dexter-webserver` | `seple.py` | Flask HTTPS web UI, provisioning, container control |
| `dexter-serial-comm` | `SerialCommunication.py` | Cavli GSM modem, OTA updates, SMS |
| `dexter-serial-logger` | `serial_data_logger.py` | Analog sensor reader (current, voltage) |
| `dexter-rpi-task` | `RPi_Task_Manager.py` | System health metrics + alerts |
| `dexter-exporter` | `dexter_debug_exporter.py` | Prometheus metrics on port 8000 |
| `dexter-mqtt` | `thingsboard_mqtt_publisher.py` | MQTT/TLS cloud telemetry publisher |
| `dexter-ota-restore` | `ota_main_restore.py` | OTA failure rollback |
| `portainer-agent` | `portainer/agent:2.39.2` | Portainer Edge fleet agent |

### Integration Services (`restart: on-failure`)

**Hikvision (7 containers):** `dexter-hik-bas`, `dexter-nvr-hikvision`, `dexter-nvr-hikvision-field`, `dexter-nvr-hikvision-bacs`, `dexter-rtc-hikvision`, `dexter-sd-hikvision`, `dexter-nvr-hik-lite`

**Dahua (4 containers):** `dexter-nvr-dahua`, `dexter-extract-dahua`, `dexter-rtc-dahua`, `dexter-sd-dahua`, `dexter-rec-dahua`

**CP Plus (5 containers):** `dexter-nvr-cpplus`, `dexter-extract-cpplus`, `dexter-rtc-cpplus`, `dexter-sd-cpplus`, `dexter-rec-cpplus`

**BAS (3 containers):** `dexter-amc`, `dexter-texecom-bas`, `dexter-rtc-hik-bas`

### Dockerfile

```dockerfile
FROM python:3.11-slim   # ARM64 (linux/arm64)
# Build tools: gcc, python3-dev, libffi-dev, libssl-dev
# System tools: i2c-tools (DS1307 RTC), iputils-ping
WORKDIR /home/pi/Test3  # Matches production RPi path (hardcoded DB paths)
HEALTHCHECK: dexterpanel2.db readable every 60s
ENV PYTHONUNBUFFERED=1
```

---

## 5. Core Python Modules

### `db_connection.py` — SQLite Factory
Central connection factory. All modules call `get_connection(DB_*)`.

**16 database paths defined:**

| Constant | File | Contents |
|----------|------|----------|
| `DB_BUFFER` | `buffer.db` | Bounded telemetry queue (50k rows, 7d TTL) |
| `DB_PAYLOADS` | `payloads.db` | MQTT outbound queue |
| `DB_MODEM_CONFIG` | `modem_config.db` | Network type, MQTT credentials (Fernet-encrypted) |
| `DB_PANEL` | `dexterpanel2.db` | Panel zones, partitions, events |
| `DB_LOGICAL_PARAMS` | `logical_params_active_integration.db` | Integration feature flags |
| `DB_TASK_MANAGER` | `task_manager.db` | CPU/RAM/disk/temp time-series |
| `DB_CONTROLLER_PARAMS` | `parameters.db` | Analog sensor values |
| `DB_TAILSCALE` | `tailscale_info.db` | Tailscale VPN connection info |

**PRAGMAs on every connection:** WAL mode · FK enforcement · synchronous=NORMAL · 8 MB cache · 64 MB mmap · 5s busy timeout · wal_autocheckpoint=1000

### `secrets_manager.py` — Credential Vault
- Reads from `/etc/dexter/.env` (not in repo, 0600 permissions)
- Fernet key at `/etc/dexter/fernet.key`
- `get_secret(name)` · `encrypt_value(plaintext)` · `decrypt_value(ciphertext)`

### `buffer_manager.py` — Telemetry Queue
- Hard cap: 50,000 rows (oldest purged on overflow)
- Warning at 40,000 rows
- TTL: 7 days auto-delete
- `get_stats()` → exposes fill % to ThingsBoard

### `payload_manager.py` — MQTT Anti-Flood
Three protections against post-reconnect data floods:
1. **Startup purge** — delete all heartbeat rows on publisher boot
2. **Offline cap** — max 500 rows while disconnected
3. **Reconnect rate** — max 60 publishes/min after reconnect

### `watchdog_manager.py` — Deadlock Recovery
- `SoftwareWatchdog(timeout)` daemon thread
- Calls `reset()` to keep alive; times out → `logging.shutdown()` + `os.execl()` restart
- Logs `watchdog_log` event to buffer before restarting
- Timeouts: 1 hour (integrations), 30 min (serial/alert stream)

### `logical_params_module.py` — Feature Flags
8 binary integration flags in `logical_params_active_integration.db`:
`active_integration_hikvision_nvr` · `active_integration_hikvision_biometric` · `active_integration_dahua_nvr` · `active_integration_cp_plus_nvr` · `active_integration_texecom_bas` · `active_integration_amc_bas` · `active_integration_dsc_neo_bas` · `active_integration_hik_bas`

Each integration container checks its flag at startup and exits cleanly (code 0) if disabled.

---

## 6. Integration Modules

### Pattern shared by all integrations

```python
# 1. Feature flag guard
if not logical_params_module.get_param("active_integration_xxx"):
    sys.exit(0)  # Clean exit → no restart loop

# 2. Main loop
while True:
    watchdog.reset()                    # Keep watchdog alive
    poll_device()                       # HTTP/socket call to NVR/BAS
    payload_manager.insert_with_cap()   # Respects offline cap
    time.sleep(settings.nvr.interval)
```

### Hikvision

| Module | Protocol | Role |
|--------|----------|------|
| `hikvision_bas_integration.py` | ISAPI/SecurityCP | Active BAS — arm/disarm/bypass, live alert stream, supervision |
| `xml_parsing3.py` | ISAPI | Device info, HDD status, heartbeat polling |
| `xml_parsing_field_log.py` | ISAPI | Persistent alert stream listener |
| `hikvision1_biometric_14.py` | ISAPI | Face recognition / access control events |
| `hik_RTC_sync.py` | ISAPI | Date/time sync |
| `Hik_SD_Card.py` | ISAPI | SD/HDD recording status |

**Notable:** `hikvision_bas_integration.py` deduplicates `cidEvent` bursts — panels send 7–10 events/sec for a single alarm; burst filter collapses to 1 event per 3 seconds.

### Dahua / CP Plus
Same polling pattern: device info + HDD status + event logs + recording status + RTC sync. HTTPBasicAuth with Fernet-decrypted credentials.

### BAS Panels

| Module | Protocol | Panel |
|--------|----------|-------|
| `amc_integration.py` | SIA-DCS + ADM-CID (TCP/IP) | AMC X412V / X412B |
| `texecomConnect.py` | SIA-DCS (TCP/IP) | Texecom |
| `dsc_neo_integration.py` | RPC | DSC Neo |

---

## 7. Webserver

**`webserver/seple.py`** — Flask app, HTTPS port 5001, session auth

### Routes

| Route | Function |
|-------|----------|
| `/provision` | Device provisioning (network type, MQTT token, device name) |
| `/status` | Live system status (CPU, RAM, disk, temp) |
| `/integrations` | Enable/disable integration feature flags |
| `/reboot` | Host reboot via `nsenter` into PID 1 |
| `/datetime` | Set date/time (DS1307 RTC + hwclock) |
| `/containers` | Docker container start/stop (via docker SDK) |
| `/network` | Static IP or DHCP reset |
| `/ota` | Trigger OTA update |
| `/backup` | Download config backup as `.tar.gz` |

### Key Flows

**Device Provisioning:**
`form_basic()` → writes to `modem_config.db` + `/etc/dexter/.env` → Tailscale setup → `portainer_register()` → Pi appears in Portainer automatically

**`portainer_register()` in `Lan_setting.py`:**
- Calls Portainer API `POST /api/endpoints` to create Edge environment named after `device_name`
- Writes `PORTAINER_EDGE_ID` + `PORTAINER_EDGE_KEY` back to `.env`
- Restarts `portainer_edge_agent` container

---

## 8. Database Schema

### `buffer.db`
```sql
CREATE TABLE json_data (
    id INTEGER PRIMARY KEY,
    json_payload TEXT NOT NULL,
    status TEXT CHECK(status IN ('pending','sent','failed')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP,
    retry_count INTEGER DEFAULT 0
);
CREATE INDEX idx_status_created ON json_data(status, created_at);
```

### `modem_config.db`
```sql
CREATE TABLE modem_parameters (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE,
    value TEXT
);
-- Keys: network_type, device_name, access_token (Fernet),
--       client_id, user_name, password (Fernet), thingsboard_host
```

### `logical_params_active_integration.db`
```sql
CREATE TABLE parameters (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE,
    value INTEGER CHECK(value IN (0,1))
);
```

### `dexterpanel2.db`
```sql
-- zones, partitions, events tables
-- zone_id, zone_name, alarm_state (open|closed|alarm), partition_id
-- event_id, timestamp, zone_id, event_type (alarm|restore|fault)
```

### `task_manager.db`
```sql
CREATE TABLE system_stats (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    cpu_percent REAL, memory_percent REAL,
    disk_percent REAL, temperature REAL, cpu_freq_mhz REAL
);
-- Auto-purged after 60 days
```

---

## 9. Configuration & Secrets

### `settings.yaml` — Central Config

```yaml
mqtt:
  broker: thingsboard.cloud
  port: 8883          # TLS only
  keepalive: 60
  backoff_min: 1      # seconds
  backoff_max: 300

buffer:
  max_rows: 50000
  ttl_days: 7
  warn_rows: 40000
  cleanup_days: 60

watchdog:
  default_timeout: 3600     # 1 hour
  serial_timeout: 1800      # 30 min
  alert_stream_timeout: 1800

nvr:
  hikvision_heartbeat_interval: 300   # seconds
  dahua_heartbeat_interval: 120
  rtc_sync_interval: 600
```

### `.env` (never committed, gitignored)

```bash
DEVICE_NAME=BRANCH_001
MQTT_BROKER=thingsboard.cloud
MQTT_TOKEN=...               # Ethernet/Wi-Fi auth
MQTT_CLIENT_ID=...           # GSM auth
MQTT_USER_NAME=...
MQTT_PASSWORD=...
PORTAINER_SERVER=https://3.111.214.115:9443
PORTAINER_API_TOKEN=...      # Rotated: 2026-05-14
PORTAINER_EDGE_ID=...        # Written by portainer_register()
PORTAINER_EDGE_KEY=...       # Written by portainer_register()
DEXTER_IMAGE=901178127457.dkr.ecr.ap-south-1.amazonaws.com/dexter-edge:latest
```

### Secret storage locations

| Secret | Location | Rotation date |
|--------|----------|---------------|
| AWS IAM keys (`ecr-pi-deploy`) | GitHub Secrets + `~/.aws/` | 2026-05-14 |
| Portainer API token | SEPL-DX2 `.env` | 2026-05-14 |
| GitHub PAT | `gh` CLI keyring + Credential Manager | 2026-05-14 |

---

## 10. CI/CD Pipeline

### `.github/workflows/build-push-ecr.yml`

**Triggers:** push to `main` · `v*.*.*` tags · PRs to `main` · manual dispatch

**Jobs (parallel):**

```
secret-scan       → Gitleaks (full git history scan for leaked credentials)
security-scan     → pip-audit (requirements.txt + webserver/requirements.txt)
                    Ignores: CVE-2026-44405 (paramiko, no fix, not imported)
build-push        → QEMU + Buildx → linux/arm64 → ECR push
```

**Tags pushed:**
- Every main push: `:latest` + `:sha-XXXXXXX`
- `v1.2.3` tag push: `:1.2.3` + `:1.2` + `:1`
- Manual: `:custom_tag`

**ECR registry:** `901178127457.dkr.ecr.ap-south-1.amazonaws.com/dexter-edge`  
**Build cache:** `:buildcache` tag in ECR

### `.github/workflows/qodana_code_quality.yml`
JetBrains Qodana static analysis. Baseline in `baseline.sarif.json`. Comments on PRs.

---

## 11. Infrastructure

### AWS

| Resource | Value |
|----------|-------|
| Account ID | 901178127457 |
| Region | ap-south-1 (Mumbai) |
| ECR repo | `dexter-edge` |
| IAM user | `ecr-pi-deploy` (ECR push only) |
| Credentials | `C:\Users\Acer\.aws\` |

### Portainer Server (EC2)

| Item | Value |
|------|-------|
| Public IP | 3.111.214.115 |
| Instance | t3.micro, Amazon Linux 2023, ap-south-1 |
| HTTPS URL | https://3.111.214.115:9443 |
| HTTP URL | http://3.111.214.115:9000 *(mobile-friendly)* |
| Edge tunnel port | 8000 |
| Admin credentials | `admin` / `NovaEdge@2025` |
| EC2 key | `D:\AWS\ECR-PI-DEPLOY\dexter-portainer-key.pem` |
| Security group | `sg-04a51e8c8e5761070` (`dexter-portainer`) |
| **Open ports** | 8000, 9000, 9443 |

### SEPL-DX2 (Master Pi)

| Item | Value |
|------|-------|
| IP | 192.168.0.200 |
| SSH | `ssh pi@192.168.0.200` |
| Files path | `/home/pi/Test3/` |
| Portainer env name | `SEPL-DX2` (Environment ID: 4) |
| Edge ID | `bf68bb89-47cc-4b9c-b3bc-13ba91cefd25` |

### Auto-Registration Flow (new Pi → Portainer)
```
device_provisioning()
  └── form_basic() sets device_name
        └── portainer_register()
              ├── POST /api/endpoints → creates Edge environment
              ├── Writes PORTAINER_EDGE_ID + PORTAINER_EDGE_KEY to .env
              └── Restarts portainer-agent container
                    └── Pi appears in Portainer dashboard automatically
```

---

## 12. Security Hardening

### Implemented (as of 2026-05-14)

| Control | Status |
|---------|--------|
| `.env` in `.gitignore` | ✅ |
| All secrets in `/etc/dexter/.env` (0600) | ✅ |
| Fernet encryption for DB-stored credentials | ✅ |
| MQTT TLS-only (port 8883) | ✅ |
| Webserver HTTPS (cert + key) | ✅ |
| pip-audit in CI (both requirements files) | ✅ |
| Gitleaks secret scan in CI | ✅ |
| Dependabot alerts + auto-fixes | ✅ |
| Parameterized SQL queries throughout | ✅ |
| AWS IAM: ECR-only permissions | ✅ |
| 54/55 pip CVEs resolved | ✅ |

### Known accepted risks

| Risk | Reason | Tracking |
|------|--------|---------|
| `paramiko` CVE-2026-44405 (SHA-1 in RSA) | No upstream fix; paramiko not imported | Dismissed in Dependabot #4, #8 |
| Portainer HTTP on port 9000 | Internal fleet tool, engineer-only access | Acceptable |
| Portainer self-signed cert on 9443 | Internal use | Acceptable |

### GitHub Advanced Security
Not enabled (private repo on personal plan). Covered by:
- Gitleaks (secret scanning equivalent)
- pip-audit (dependency scanning)
- Dependabot (vulnerability alerts)

GHAS available via GitHub Enterprise Cloud ($21/user/month).

---

## 13. Deployment Workflow

### Build & Push (CI/CD — automatic)
1. Push to `main` → GitHub Actions triggers
2. Gitleaks + pip-audit scans run in parallel
3. `docker buildx build --platform linux/arm64` on `ubuntu-latest` (QEMU emulation)
4. Push to ECR: `:latest` + `:sha-XXXXXXX`
5. Build cache stored as `:buildcache` tag

### Deploy to Pi (manual scp — not git)
```bash
scp -r ./files/* pi@192.168.0.200:/home/pi/Test3/
ssh pi@192.168.0.200 "cd /home/pi/Test3 && docker compose pull && docker compose up -d"
```

### OTA Update (from webserver UI)
1. Engineer clicks "Update" in webserver → `SerialCommunication` fetches Python files
2. Backup existing code → unpack new files → kill services → `docker compose restart`
3. `dexter-ota-restore` container monitors → rolls back on failure

---

## 14. Observability

### Logs
```bash
docker compose logs -f dexter-core        # Panel controller
docker compose logs -f dexter-mqtt        # MQTT publisher
journalctl -u dexter-docker.service -f    # Host systemd
```

### Prometheus Metrics (port 8000)
Exposed by `dexter_debug_exporter.py`:

| Metric | Description |
|--------|-------------|
| `dexter_rpi_cpu_percent` | CPU utilisation |
| `dexter_rpi_memory_percent` | RAM utilisation |
| `dexter_rpi_disk_percent` | Disk usage |
| `dexter_rpi_temperature_celsius` | CPU temperature |
| `dexter_buffer_pending` | Queued telemetry events |
| `dexter_buffer_fill_pct` | Buffer fill % (warn at 80%) |
| `dexter_mqtt_queue_pending` | Unsent MQTT payloads |
| `dexter_active_integration` | Integration online/offline |
| `dexter_process_running` | Per-container health (0/1) |

### Daily Reports
`daily_reports/YYYY-MM-DD.md` — auto-generated commit-activity reports including commits, files changed, standup summary.

### ThingsBoard Cloud
Real-time dashboards at `thingsboard.cloud`. Alarms: high CPU, low disk, integration failures, MQTT queue overflow.

---

## 15. Recent Changes

<!-- AUTO-UPDATED by .github/workflows/update-knowledge-base.yml -->
<!-- DO NOT EDIT THIS SECTION MANUALLY -->

| Date | Commit | Change |
|------|--------|--------|
| 2026-05-25 | `e799164` | Merge pull request #43 from gaurav9433/dev |
| 2026-05-25 | `202650e` | Merge pull request #42 from gaurav9433/dev |
| 2026-05-25 | `b661c80` | Merge pull request #41 from gaurav9433/dev |
| 2026-05-25 | `a4a7314` | fix: GSM send path correctly handles over_ethernet on failback |
| 2026-05-23 | `d74ef7f` | fix: throttle paho-mqtt reconnect to prevent ThingsBoard rate-limit loop |
| 2026-05-23 | `6bdf661` | fix: network_event telemetry written to payloads.db for ethernet publisher (#38) |
| 2026-05-23 | `b8aeb5a` | Merge pull request #37 from gaurav9433/dev |
| 2026-05-23 | `b2dfe94` | Merge pull request #36 from gaurav9433/dev |
| 2026-05-22 | `bf8a88e` | Merge pull request #35 from gaurav9433/dev |
| 2026-05-22 | `a130716` | Merge pull request #34 from gaurav9433/dev |
| 2026-05-22 | `232b8cb` | Merge pull request #33 from gaurav9433/dev |
| 2026-05-22 | `a0d8836` | fix: network_type DB persistence across container restarts (#32) |
| 2026-05-22 | `081a47a` | Merge pull request #31 from gaurav9433/dev |
| 2026-05-22 | `725c18f` | fix: MQTT reconnect cascade + X.509 cert guard (GSM + Ethernet paths) (#30) |
| 2026-05-22 | `734c815` | Merge pull request #29 from gaurav9433/dev |
| 2026-05-22 | `8c71817` | Merge pull request #28 from gaurav9433/dev |
| 2026-05-21 | `c96dad3` | Merge pull request #27 from gaurav9433/dev |
| 2026-05-21 | `c4f3773` | Merge pull request #26 from gaurav9433/dev |
| 2026-05-21 | `9815711` | Merge pull request #25 from gaurav9433/dev |
| 2026-05-21 | `bbf34aa` | Merge pull request #24 from gaurav9433/dev |
| 2026-05-20 | `d03ff41` | Merge remote-tracking branch 'origin/main' |
| 2026-05-20 | `1dea361` | fix: resolve 2 Qodana warnings in _get_network_status() |
| 2026-05-20 | `0c52afd` | Merge remote-tracking branch 'origin/main' |
| 2026-05-20 | `1f9b2e0` | Merge remote-tracking branch 'origin/main' into dev |
| 2026-05-20 | `cdedda7` | Merge remote-tracking branch 'origin/main' |
| 2026-05-20 | `02edac9` | Merge remote-tracking branch 'origin/main' |
| 2026-05-20 | `cfdd0f6` | Merge remote-tracking branch 'origin/main' |
| 2026-05-20 | `3d51dcc` | Merge remote-tracking branch 'origin/main' |
| 2026-05-19 | `efbe13b` | fix: prevent auto-reboot when scrolling through Network Settings menu |
| 2026-05-19 | `4e08eb8` | feat: full auto-provisioning — all 4 services create on LCD Device Provisioning |
| 2026-05-19 | `3ee942a` | fix: skip pon/poff on ethernet devices during provisioning |
| 2026-05-19 | `088da20` | fix: remove sudo from pon/poff/reboot calls — not installed in Docker container |
| 2026-05-19 | `c79c027` | fix: mount docker.sock on dexter-core and restart dexter-mqtt after provisioning |
| 2026-05-19 | `12ab374` | fix: catch FileNotFoundError in stop_autorun() when pgrep not in container |
| 2026-05-19 | `1762660` | fix: use nsenter for host reboot so Pi actually reboots on static→DHCP switch |
| 2026-05-15 | `1059f00` | fix: stop stale containers before provisioning in post_burn_setup.sh |
| 2026-05-15 | `19c3f3b` | feat: add post_burn_setup.sh for fleet Pi provisioning |
| 2026-05-15 | `ef7dfe9` | Merge pull request #22 from gaurav9433/dev |
| 2026-05-15 | `d9b362e` | Merge branch 'main' of https://github.com/gaurav9433/Dexter-HMS-V3- |
| 2026-05-15 | `ca87c70` | Merge pull request #21 from gaurav9433/dev |
| 2026-05-15 | `a104378` | Merge pull request #20 from gaurav9433/dev |
| 2026-05-15 | `6316b32` | Merge pull request #19 from gaurav9433/dev |
| 2026-05-14 | `45b2358` | Merge pull request #18 from gaurav9433/dev |
| 2026-05-14 | `1f4fd82` | Merge pull request #17 from gaurav9433/dev |
| 2026-05-14 | `add9751` | Merge pull request #16 from gaurav9433/dev |
| 2026-05-14 | `e63fe98` | Merge pull request #15 from gaurav9433/dev |
| 2026-05-14 | `b0b70eb` | Merge pull request #14 from gaurav9433/dev |
| 2026-05-14 | `79505aa` | Merge pull request #13 from gaurav9433/dev |
| 2026-05-14 | `7c5826d` | ci: bump all GitHub Actions to Node.js 24-compatible versions |
| 2026-05-14 | `1cb3fc0` | chore: gitignore .claude/ and HTML reports; add daily reports 2026-05-08–13 |
| 2026-05-14 | `51ad538` | ci: add workflow_dispatch trigger to update-knowledge-base workflow |
| 2026-05-14 | `1560390` | Remove unused SQLAlchemy/Flask-SQLAlchemy/greenlet from webserver deps |
| 2026-05-14 | `fe03303` | Remove cffi/pycparser (not needed by cryptography 42+) |
| 2026-05-14 | `4231c68` | Replace non-existent Flask-PyMPyMuPDF with PyMuPDF |
| 2026-05-14 | `340a2ca` | Add no-deps to pip-audit (skip C-library resolution in CI) |
| 2026-05-14 | `1be32c3` | Ignore CVE-2026-44405 in pip-audit CI |
| 2026-05-14 | `4c2c4c9` | Replace non-existent socket-action with pypa/gh-action-pip-audit |
| 2026-05-14 | `d9230f3` | Add Gitleaks secret scanning to CI |
| 2026-05-14 | `b811990` | Fix 3 Dependabot CVEs in webserver/requirements.txt |
| 2026-05-14 | `ac4956c` | Resolve 54/55 pip-audit CVEs (Mini Shai-Hulud response) |
| 2026-05-14 | `8eb5b01` | Gitignore .env files + add Socket supply-chain scan to CI |

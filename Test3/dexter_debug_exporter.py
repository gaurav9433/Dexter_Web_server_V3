# -*- coding: utf-8 -*-
"""
dexter_debug_exporter.py — Local Prometheus exporter for Dexter HMS debugging

Runs directly on the Raspberry Pi. Reads local SQLite databases and
exposes /metrics on port 8000 so Prometheus on your laptop can scrape it.

No ThingsBoard, no internet, no MQTT needed — purely local DB reads.

Metrics exposed
---------------
  dexter_rpi_cpu_percent          — CPU usage %
  dexter_rpi_memory_percent       — RAM usage %
  dexter_rpi_disk_percent         — Disk usage %
  dexter_rpi_temperature_celsius  — CPU temperature
  dexter_rpi_cpu_freq_mhz         — CPU clock speed
  dexter_rpi_net_sent_mb          — Network bytes sent (total, MB)
  dexter_rpi_net_recv_mb          — Network bytes received (total, MB)

  dexter_buffer_pending           — Messages in buffer.db waiting to send
  dexter_buffer_sent              — Messages in buffer.db already sent
  dexter_buffer_oldest_age_hours  — Age of oldest pending message in hours
  dexter_buffer_fill_pct          — Buffer fullness % (max 50,000 rows)

  dexter_mqtt_queue_pending       — Messages in payloads.db waiting to publish
  dexter_mqtt_queue_sent          — Messages in payloads.db already published

  dexter_active_integration       — Global integration flag (0=off, 1=on)
  dexter_bacs_integration         — BACS-specific integration flag (0/1)
  dexter_hikvision_nvr_intg       — Hikvision NVR integration flag (0/1)
  dexter_dahua_nvr_intg           — Dahua NVR integration flag (0/1)
  dexter_cp_plus_nvr_intg         — CP Plus NVR integration flag (0/1)
  dexter_texecom_bas_intg         — Texecom BAS integration flag (0/1)
  dexter_amc_bas_intg             — AMC BAS integration flag (0/1)
  dexter_hik_bas_intg             — Hikvision BAS integration flag (0/1)

  dexter_process_running          — 1 if the named process is running, 0 if not
    label: process = main | hik_nvr | dahua_nvr | cp_plus | bacs | field_log | task_manager

Usage
-----
  # On the RPi:
  pip install prometheus-client --break-system-packages
  python3 dexter_debug_exporter.py

  # On your laptop — prometheus.yml:
  scrape_configs:
    - job_name: dexter_debug
      static_configs:
        - targets: ['<RPi_IP>:8000']
      scrape_interval: 15s

  # Grafana: add Prometheus as data source, create panels using metric names above.

Author: Seple Novaedge Pvt. Ltd.
"""

import os
import sqlite3
import subprocess
import time
import logging

from prometheus_client import start_http_server, Gauge

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s — %(message)s'
)
log = logging.getLogger('dexter_debug_exporter')

# ── DB paths ──────────────────────────────────────────────────────────────────
BASE = '/home/pi/Test3'
DB_TASK_MANAGER  = f'{BASE}/task_manager.db'
DB_BUFFER        = f'{BASE}/buffer.db'
DB_PAYLOADS      = f'{BASE}/payloads.db'
DB_ACTIVE_INTG   = f'{BASE}/active_integration.db'
DB_LOGICAL_PARAMS= f'{BASE}/logical_params_active_integration.db'

PORT             = 8000
SCRAPE_INTERVAL  = 15   # seconds between DB reads

# ── Process names to monitor ──────────────────────────────────────────────────
PROCESSES = {
    'main':         'TLChronosProMAIN',
    'hik_nvr':      'xml_parsing3',
    'dahua_nvr':    'xml_parsing_field_log',
    'cp_plus':      'cp_plus_nvr_dvr',
    'bacs':         'hikvision1_biometric',
    'texecom_bas':  'texecomConnect',
    'hik_bas':      'hikvision_bas_integration',
    'amc_bas':      'amc_integration',
    'task_manager': 'RPi_Task_Manager',
    'publisher':    'thingsboard_mqtt_publisher',
}

# ── Metric definitions ────────────────────────────────────────────────────────

# RPi health
g_cpu   = Gauge('dexter_rpi_cpu_percent',         'RPi CPU usage %')
g_ram   = Gauge('dexter_rpi_memory_percent',       'RPi RAM usage %')
g_disk  = Gauge('dexter_rpi_disk_percent',         'RPi disk usage %')
g_temp  = Gauge('dexter_rpi_temperature_celsius',  'RPi CPU temperature °C')
g_freq  = Gauge('dexter_rpi_cpu_freq_mhz',         'RPi CPU clock speed MHz')
g_netsent = Gauge('dexter_rpi_net_sent_mb',        'Network sent MB (cumulative)')
g_netrecv = Gauge('dexter_rpi_net_recv_mb',        'Network received MB (cumulative)')

# Buffer backlog
g_buf_pending  = Gauge('dexter_buffer_pending',           'buffer.db pending messages')
g_buf_sent     = Gauge('dexter_buffer_sent',              'buffer.db sent messages')
g_buf_age      = Gauge('dexter_buffer_oldest_age_hours',  'Oldest pending message age in hours')
g_buf_fill     = Gauge('dexter_buffer_fill_pct',          'buffer.db fullness % (cap=50000)')

# MQTT publisher queue
g_mqtt_pending = Gauge('dexter_mqtt_queue_pending',  'payloads.db pending rows')
g_mqtt_sent    = Gauge('dexter_mqtt_queue_sent',     'payloads.db sent rows')

# Integration flags
g_active_intg      = Gauge('dexter_active_integration',    'Global integration on/off (0/1)')
g_bacs_intg        = Gauge('dexter_bacs_integration',      'BACS integration flag (0/1)')
g_hik_nvr_intg     = Gauge('dexter_hikvision_nvr_intg',    'Hikvision NVR integration flag (0/1)')
g_dah_nvr_intg     = Gauge('dexter_dahua_nvr_intg',        'Dahua NVR integration flag (0/1)')
g_cp_intg          = Gauge('dexter_cp_plus_nvr_intg',      'CP Plus NVR integration flag (0/1)')
g_texecom_bas_intg = Gauge('dexter_texecom_bas_intg',      'Texecom BAS integration flag (0/1)')
g_amc_bas_intg     = Gauge('dexter_amc_bas_intg',          'AMC BAS integration flag (0/1)')
g_hik_bas_intg     = Gauge('dexter_hik_bas_intg',          'Hikvision BAS integration flag (0/1)')

# Process health
g_proc = Gauge('dexter_process_running',
               '1 if process is running, 0 if not',
               ['process'])


# ── DB helpers ────────────────────────────────────────────────────────────────

def _read(db_path, query, default=None):
    """Run a scalar query on a local SQLite DB. Returns default on any error."""
    try:
        conn = sqlite3.connect(db_path, timeout=3)
        row  = conn.execute(query).fetchone()
        conn.close()
        return row[0] if row else default
    except Exception as exc:
        log.debug('DB read error %s: %s', db_path, exc)
        return default


def _read_row(db_path, query, default=None):
    """Run a row query on a local SQLite DB. Returns row tuple or default."""
    try:
        conn = sqlite3.connect(db_path, timeout=3)
        row  = conn.execute(query).fetchone()
        conn.close()
        return row if row else default
    except Exception as exc:
        log.debug('DB read error %s: %s', db_path, exc)
        return default


# ── Collectors ────────────────────────────────────────────────────────────────

def collect_rpi_health():
    """Read latest row from task_manager.db (written every 60s by RPi_Task_Manager.py)."""
    row = _read_row(
        DB_TASK_MANAGER,
        'SELECT cpu_percent, memory_percent, disk_percent, cpu_freq, '
        'cpu_temp, net_sent, net_recv '
        'FROM system_stats ORDER BY timestamp DESC LIMIT 1'
    )
    if row is None:
        log.debug('task_manager.db: no rows yet')
        return

    cpu, ram, disk, freq, temp, net_sent, net_recv = row
    if cpu       is not None: g_cpu.set(cpu)
    if ram       is not None: g_ram.set(ram)
    if disk      is not None: g_disk.set(disk)
    if freq      is not None: g_freq.set(freq)
    if temp      is not None: g_temp.set(temp)
    if net_sent  is not None: g_netsent.set(net_sent)
    if net_recv  is not None: g_netrecv.set(net_recv)


def collect_buffer_stats():
    """Read buffer.db stats — how many messages are queued vs sent."""
    pending = _read(DB_BUFFER,
        "SELECT COUNT(*) FROM buffer WHERE status='pending'", 0)
    sent    = _read(DB_BUFFER,
        "SELECT COUNT(*) FROM buffer WHERE status='sent'", 0)
    oldest  = _read(DB_BUFFER,
        "SELECT MIN(created_at) FROM buffer WHERE status='pending'")
    total   = _read(DB_BUFFER, 'SELECT COUNT(*) FROM buffer', 0)

    g_buf_pending.set(pending)
    g_buf_sent.set(sent)
    g_buf_fill.set(round(total / 50000 * 100, 1) if total else 0)

    if oldest:
        age_hours = round((time.time() - oldest) / 3600, 2)
        g_buf_age.set(age_hours)
    else:
        g_buf_age.set(0)


def collect_mqtt_queue():
    """Read payloads.db — how many messages are waiting to be published."""
    pending = _read(DB_PAYLOADS,
        "SELECT COUNT(*) FROM json_data WHERE status='pending'", 0)
    sent    = _read(DB_PAYLOADS,
        "SELECT COUNT(*) FROM json_data WHERE status='sent'", 0)
    g_mqtt_pending.set(pending)
    g_mqtt_sent.set(sent)


def collect_integration_flags():
    """Read integration on/off state from both integration DBs."""
    # Global flag
    val = _read(DB_ACTIVE_INTG,
        'SELECT active_integration_on_off_bit '
        'FROM active_integration_external_device WHERE id=1', 0)
    g_active_intg.set(val if val is not None else 0)

    # Per-device flags from logical_params
    def _flag(name):
        return _read(DB_LOGICAL_PARAMS,
            f"SELECT value FROM parameters WHERE name='{name}'", 0) or 0

    g_bacs_intg.set(_flag('active_integration_hikvision_biometric'))
    g_hik_nvr_intg.set(_flag('active_integration_hikvision_nvr'))
    g_dah_nvr_intg.set(_flag('active_integration_dahua_nvr'))
    g_cp_intg.set(_flag('active_integration_cp_plus_nvr'))
    g_texecom_bas_intg.set(_flag('active_integration_texecom_bas'))
    g_amc_bas_intg.set(_flag('active_integration_amc_bas'))
    g_hik_bas_intg.set(_flag('active_integration_hik_bas'))


def collect_process_health():
    """Check if each service process is currently running using pgrep."""
    for label, keyword in PROCESSES.items():
        try:
            result = subprocess.run(
                ['pgrep', '-f', keyword],
                capture_output=True, timeout=3
            )
            running = 1 if result.returncode == 0 else 0
        except Exception:
            running = 0
        g_proc.labels(process=label).set(running)


# ── Main loop ─────────────────────────────────────────────────────────────────

def collect_all():
    collect_rpi_health()
    collect_buffer_stats()
    collect_mqtt_queue()
    collect_integration_flags()
    collect_process_health()
    log.debug('Metrics updated')


if __name__ == '__main__':
    log.info('Starting Dexter debug exporter on port %d', PORT)
    log.info('Scraping local DBs every %ds', SCRAPE_INTERVAL)
    log.info('Add this to prometheus.yml on your laptop:')
    log.info('  - job_name: dexter_debug')
    log.info('    static_configs:')
    log.info('      - targets: ["%s:%d"]', '<RPi_IP>', PORT)

    start_http_server(PORT)

    while True:
        try:
            collect_all()
        except Exception as exc:
            log.error('collect_all error: %s', exc)
        time.sleep(SCRAPE_INTERVAL)

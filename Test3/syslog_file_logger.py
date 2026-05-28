import logging
import logging.handlers
import os
from datetime import datetime, timedelta

LOG_FILE       = "/home/pi/Test3/update.log"
RETENTION_DAYS = 90

# ── Fix 2: cleanup runs once per process, not once per get_dual_logger() call ──
_cleanup_done = False


def cleanup_old_logs(log_file: str, retention_days: int) -> None:
    """Remove log entries older than retention_days while keeping recent ones.

    SFL-FIX-1: os.replace(tmp, log_file) raised FileNotFoundError when the
    .tmp write was interrupted (disk full, permission error, stale .tmp from
    previous crash). Fix: clean up stale .tmp first, wrap write+replace in
    try/except, only call os.replace if .tmp was actually written successfully.
    """
    if not os.path.exists(log_file):
        return

    cutoff    = datetime.now() - timedelta(days=retention_days)
    temp_file = log_file + ".tmp"

    # Remove any stale .tmp left by a previous failed run
    try:
        if os.path.exists(temp_file):
            os.remove(temp_file)
    except OSError:
        pass

    try:
        with open(log_file, "r") as infile, open(temp_file, "w") as outfile:
            for line in infile:
                try:
                    date_str = line.split("|")[0].strip()
                    log_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                    if log_date >= cutoff:
                        outfile.write(line)
                except ValueError:
                    # Line has no parseable date prefix — keep it
                    outfile.write(line)

        # Only replace if tmp was fully written
        if os.path.exists(temp_file):
            os.replace(temp_file, log_file)

    except OSError:
        # Write or replace failed — remove partial tmp, leave original intact
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except OSError:
            pass


def get_dual_logger(name: str) -> 'logging.Logger':
    """
    Return a named logger that writes to both syslog and the local rotating file.

    Fix 1 — Root logger configuration:
        Handlers are added to the ROOT logger (logging.getLogger()) so that any
        module using the standard logging.getLogger(__name__) pattern (e.g.
        buffer_manager.py) automatically inherits both the syslog and file
        handlers via Python's propagation chain — without needing to import
        syslog_file_logger directly.

    Fix 2 — One-shot cleanup:
        cleanup_old_logs() is guarded by a module-level flag so it runs exactly
        once per process, not once per module that calls get_dual_logger().
    """
    global _cleanup_done
    if not _cleanup_done:
        cleanup_old_logs(LOG_FILE, RETENTION_DAYS)
        _cleanup_done = True

    # ── Attach handlers to root logger once ─────────────────────────────────
    # Root is the parent of ALL loggers. Any logger created anywhere in the
    # process with logging.getLogger(anything) will propagate up to root and
    # reach these handlers — no per-module import of syslog_file_logger needed.
    root = logging.getLogger()

    if not root.handlers:
        root.setLevel(logging.INFO)

        # ---- Syslog Handler ----
        syslog_handler = logging.handlers.SysLogHandler(address='/dev/log')
        syslog_handler.setFormatter(
            logging.Formatter('%(name)s: %(levelname)s %(message)s')
        )
        root.addHandler(syslog_handler)

        # ---- File Handler ----
        file_handler = logging.FileHandler(LOG_FILE, mode='a')
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        root.addHandler(file_handler)

    # ── Named logger for the caller ──────────────────────────────────────────
    # No handlers needed here — propagate=True (default) sends everything to
    # root. We still return a named logger so the module name appears correctly
    # in log output (%(name)s = 'buffer_manager', 'TL_maincode', etc.)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    return logger

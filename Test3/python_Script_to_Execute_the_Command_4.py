# -*- coding: utf-8 -*-
# !/usr/local/bin/python
#
# python_Script_to_Execute_the_Command_4.py
# Subprocess launcher — applies network configuration by executing
# Configure_Network_7.py via a privileged subprocess.
#
# Database fixes assessment:
#   This module contains no SQLite database access, no buffer inserts,
#   and no device-parameter reads. DB-01 through DB-06 do not apply here.
#   Importing run_all_migrations() or BoundedBufferManager into a subprocess
#   launcher with no database operations would add meaningless overhead.
#
# Changes applied vs original:
#   SEC   — subprocess.Popen()+communicate() replaced with subprocess.run()
#             (modern API: timeout enforced, no risk of indefinite hang)
#   SEC   — bare except Exception replaced with typed handlers:
#             FileNotFoundError (sudo/python3 not found),
#             subprocess.TimeoutExpired (script hangs beyond timeout),
#             subprocess.SubprocessError (other subprocess failures),
#             OSError (kernel-level process spawn failure)
#   BUG   — stdout/stderr were bytes (Popen default) — printing them produced
#             b'...' output. Fixed by text=True in subprocess.run()
#   CODE  — All logic was at module level with no function wrapper and no
#             __main__ guard — importing this file would immediately trigger
#             a network configuration change. Wrapped in configureNetwork()
#             function and if __name__ == "__main__" guard.
#   LOG   — log.info() replaced with log.*() via get_dual_logger()


"""
python_Script_to_Execute_the_Command_4.py
Dexter HMS — Subprocess launcher: static IP configuration

Responsibilities:
  - Executes Configure_Network_7.py as a privileged subprocess with sudo
  - subprocess.run() with timeout enforced — cannot hang indefinitely
  - Note: prefer calling Configure_Network_7.main() via direct import
    where possible; this launcher exists for cases requiring a subprocess boundary

Key functions:
  - configureNetwork() — execute Configure_Network_7.py via subprocess

Dependencies:
  - Configure_Network_7.py (external script)
Author: Seple Novaedge Pvt. Ltd.
"""

import subprocess

from syslog_file_logger import get_dual_logger
log = get_dual_logger(__name__)

# Timeout (seconds) for the network configuration script.
# Configure_Network_7.py can write to dhcpcd.conf and restart networking
# services — 120 s gives enough time for service restarts to complete.
_CONFIGURE_TIMEOUT_SEC = 120


def configureNetwork() -> bool:
    """
    Execute Configure_Network_7.py with elevated privileges via sudo.
    Returns True if the script exited with code 0, False otherwise.

    SEC: subprocess.run() with timeout enforced — cannot hang indefinitely.
    SEC: text=True — stdout/stderr decoded to str, not raw bytes.
    SEC: Typed exception handlers replace bare except Exception.
    BUG fix: original log.debug(stdout) printed raw bytes b'...'; now decoded.
    CODE fix: original had no function wrapper — all logic ran at module import.
    """
    command = [
        'sudo',
        '/usr/bin/python3',
        '/home/pi/Test3/Configure_Network_7.py'
    ]

    log.info("[configureNetwork] Executing: %s", ' '.join(command))

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,                          # decode bytes → str
            timeout=_CONFIGURE_TIMEOUT_SEC
        )

        if result.returncode == 0:
            log.info("[configureNetwork] Completed successfully")
            if result.stdout.strip():
                log.info("[configureNetwork] Output: %s", result.stdout.strip())
            return True
        else:
            log.error("[configureNetwork] Script exited with code %d",
                      result.returncode)
            if result.stderr.strip():
                log.error("[configureNetwork] Stderr: %s", result.stderr.strip())
            return False

    except FileNotFoundError as exc:
        # sudo or /usr/bin/python3 not found on the system
        log.error("[configureNetwork] Command not found: %s", exc)
    except subprocess.TimeoutExpired:
        log.error("[configureNetwork] Script timed out after %d s — process killed",
                  _CONFIGURE_TIMEOUT_SEC)
    except subprocess.SubprocessError as exc:
        log.error("[configureNetwork] Subprocess error: %s", exc)
    except OSError as exc:
        log.error("[configureNetwork] OS error spawning process: %s", exc)

    return False


# CODE fix: original had all logic at module level with no __main__ guard.
# Any import of this file would immediately trigger a network configuration
# change. Now only runs when executed directly.
if __name__ == "__main__":
    success = configureNetwork()
    if not success:
        log.warning("[configureNetwork] Network configuration did not complete "
                    "successfully")
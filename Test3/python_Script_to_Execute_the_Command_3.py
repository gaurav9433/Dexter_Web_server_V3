# -*- coding: utf-8 -*-
# !/usr/local/bin/python
#
# python_Script_to_Execute_the_Command_3.py
# Subprocess launcher — resets the RPi network interface to DHCP
# by executing reset_to_dhcp.py via a privileged subprocess.
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
#   CODE  — resetDHCP() call moved inside if __name__ == "__main__" guard;
#             calling it at module level meant any import of this file would
#             immediately trigger a DHCP reset
#   LOG   — log.info() replaced with log.*() via get_dual_logger()


"""
python_Script_to_Execute_the_Command_3.py
Dexter HMS — Subprocess launcher: DHCP reset

Responsibilities:
  - Executes reset_to_dhcp.py as a privileged subprocess with sudo
  - subprocess.run() with timeout enforced — cannot hang indefinitely
  - Note: prefer calling reset_to_dhcp.reset_dhcp() via direct import
    where possible; this launcher exists for cases requiring a subprocess boundary

Key functions:
  - resetDHCP() — execute reset_to_dhcp.py via subprocess

Dependencies:
  - reset_to_dhcp.py (external script)
Author: Seple Novaedge Pvt. Ltd.
"""

import subprocess

from syslog_file_logger import get_dual_logger
log = get_dual_logger(__name__)

# Timeout (seconds) for the DHCP reset script.
# If reset_to_dhcp.py hangs beyond this limit, the process is killed
# and a TimeoutExpired exception is raised — preventing an indefinite hang.
_RESET_TIMEOUT_SEC = 60


def resetDHCP() -> bool:
    """
    Execute reset_to_dhcp.py with elevated privileges via sudo.
    Returns True if the script exited with code 0, False otherwise.

    SEC: subprocess.run() with timeout enforced — cannot hang indefinitely.
    SEC: text=True — stdout/stderr decoded to str, not raw bytes.
    SEC: Typed exception handlers replace bare except Exception.
    BUG fix: original log.debug(stdout) printed raw bytes b'...'; now decoded.
    """
    command = [
        'sudo',
        '/usr/bin/python3',
        '/home/pi/Test3/reset_to_dhcp.py'
    ]

    log.info("[resetDHCP] Executing: %s", ' '.join(command))

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,                          # decode bytes → str
            timeout=_RESET_TIMEOUT_SEC
        )

        if result.returncode == 0:
            log.info("[resetDHCP] Completed successfully")
            if result.stdout.strip():
                log.info("[resetDHCP] Output: %s", result.stdout.strip())
            return True
        else:
            log.error("[resetDHCP] Script exited with code %d", result.returncode)
            if result.stderr.strip():
                log.error("[resetDHCP] Stderr: %s", result.stderr.strip())
            return False

    except FileNotFoundError as exc:
        # sudo or /usr/bin/python3 not found on the system
        log.error("[resetDHCP] Command not found: %s", exc)
    except subprocess.TimeoutExpired:
        log.error("[resetDHCP] Script timed out after %d s — process killed",
                  _RESET_TIMEOUT_SEC)
    except subprocess.SubprocessError as exc:
        log.error("[resetDHCP] Subprocess error: %s", exc)
    except OSError as exc:
        log.error("[resetDHCP] OS error spawning process: %s", exc)

    return False


# CODE fix: original called resetDHCP() at module level — any import of this
# file would immediately trigger a DHCP reset. Moved inside __main__ guard.
if __name__ == "__main__":
    success = resetDHCP()
    if not success:
        log.warning("[resetDHCP] DHCP reset did not complete successfully")

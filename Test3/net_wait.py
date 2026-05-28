import socket
import time

# net_wait.py
# Dexter HMS — Network Readiness Check
#
# Changes from previous version:
#   NET-FIX-1: socket.gethostbyname() only tested DNS — replaced with
#              socket.create_connection() which tests actual TCP connectivity
#              using the same getaddrinfo() path as paho and requests.
#   NET-FIX-2: Port is now a parameter (default 443 HTTPS, use 8883 for MQTT).
#   NET-FIX-3: Double-confirm — after the first TCP success, wait 2s and
#              confirm once more. systemd-resolved briefly invalidates its
#              DNS cache when PPP comes up. A single success can be followed
#              by an immediate failure (both in the same second). Two
#              consecutive successes 2s apart means the resolver has settled.


def wait_for_network(host="thingsboard.cloud", timeout=30, port=443):
    """
    Wait until two consecutive TCP connections to host:port succeed.

    Two consecutive successes 2 seconds apart confirms systemd-resolved
    has fully settled after a PPP interface change.

    Args:
        host    : hostname to test (default: thingsboard.cloud)
        timeout : total seconds to keep trying (default: 30)
        port    : TCP port to probe (default: 443; use 8883 for MQTT)
    """
    start = time.time()
    consecutive = 0          # count consecutive successes

    while time.time() - start < timeout:
        try:
            sock = socket.create_connection((host, port), timeout=5)
            sock.close()
            consecutive += 1
            if consecutive >= 2:
                # Two successes in a row — resolver is stable
                print(f"DNS OK: {host} resolved")
                return True
            # Wait before confirming again
            time.sleep(2)
        except OSError:
            consecutive = 0  # reset on any failure
            print("DNS not ready, retrying...")
            time.sleep(2)

    return False

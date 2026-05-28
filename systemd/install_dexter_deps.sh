#!/bin/bash
# install_dexter_deps.sh — Install all Dexter HMS Python dependencies
# Run once on the Pi: sudo bash install_dexter_deps.sh

echo "=== Installing Dexter HMS Python dependencies ==="

sudo pip install \
    paho-mqtt \
    schedule \
    netifaces \
    prometheus-client \
    smbus2 \
    pad4pi \
    rpi-lgpio \
    requests \
    flask \
    cryptography \
    psutil \
    hexdump \
    --break-system-packages

echo ""
echo "=== Verifying ==="
python3 -c "
modules = [
    ('paho.mqtt',         'paho-mqtt'),
    ('schedule',          'schedule'),
    ('netifaces',         'netifaces'),
    ('prometheus_client', 'prometheus-client'),
    ('smbus2',            'smbus2'),
    ('pad4pi',            'pad4pi'),
    ('requests',          'requests'),
    ('flask',             'flask'),
    ('cryptography',      'cryptography'),
    ('psutil',            'psutil'),
    ('hexdump',           'hexdump'),
]
all_ok = True
for mod, pkg in modules:
    try:
        __import__(mod)
        print(f'  OK  {pkg}')
    except ImportError:
        print(f'  MISSING  {pkg}')
        all_ok = False
print()
print('All dependencies OK' if all_ok else 'Some dependencies missing — re-run script')
"

echo ""
echo "=== Done ==="

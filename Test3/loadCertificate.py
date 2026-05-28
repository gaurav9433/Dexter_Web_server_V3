import serial
import time
import sys

# Set your serial port and baudrate
SERIAL_PORT = '/dev/ttyS0'
BAUDRATE = 115200
CERT_PATH = 'ca.crt'

ser = None
try:
    # Open serial connection
    ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=2)
    time.sleep(0.5)  # Allow time for serial to settle

    # Reset input buffer to avoid old responses
    ser.reset_input_buffer()

    # === Test serial communication ===
    print("Testing serial communication with AT command...")
    ser.write(b'AT\r')
    time.sleep(0.5)

    test_response = b""
    timeout = time.time() + 3
    while time.time() < timeout:
        if ser.in_waiting:
            test_response += ser.read(ser.in_waiting)
        if test_response:
            break
        time.sleep(0.1)

    if test_response:
        print("Received response:")
        print(test_response.decode(errors='ignore'))
    else:
        print("No response received. Serial communication might be failing.")
        ser.close()
        sys.exit(1)

    # === Begin certificate upload ===
    # Load certificate from file (binary mode)
    with open(CERT_PATH, 'rb') as f:
        cert_data = f.read()

    # Send AT command to initiate CA cert upload
    ser.write(b'AT+MQTTSLOAD=1,1\r')
    time.sleep(0.5)

    # Wait for '>' prompt from module (up to 10 seconds)
    timeout = time.time() + 10
    response = b""
    prompt_received = False

    while time.time() < timeout:
        if ser.in_waiting:
            response += ser.read(ser.in_waiting)
            if b'>' in response:
                prompt_received = True
                print("Ready to send certificate...")
                break
            else:
                print("Unexpected response:", response.decode(errors='ignore'))
        time.sleep(0.1)

    print("Module response:")
    print(response.decode(errors='ignore'))

    if not prompt_received:
        print("Timed out waiting for '>' prompt from module.")
        ser.close()
        sys.exit(1)

    # Send certificate content
    ser.write(cert_data)
    time.sleep(0.2)  # Short delay before ending with CTRL+Z
    ser.write(bytes([0x1A]))  # Send CTRL+Z to finish upload

    # Wait for module response
    time.sleep(1)
    response = ser.read(1024).decode(errors='ignore')
    print("Response after cert upload:")
    print(response)

except FileNotFoundError:
    print(f"Certificate file '{CERT_PATH}' not found.")
except serial.SerialException as e:
    print(f"Serial error: {e}")
finally:
    if ser and ser.is_open:
        ser.close()



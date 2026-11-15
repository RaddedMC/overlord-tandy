import sys, time, serial

path, port = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "/dev/ttyUSB0"
data = open(path, "rb").read()
addr, length, entry = (int.from_bytes(data[i : i + 2], "little") for i in (0, 2, 4))
assert length == len(data) - 6, "header length doesn't match file size"

ser = serial.Serial(port, 1200, 8, "N", 1, xonxoff=False)
input(
    f"Load addr {addr:#06x}, {length} bytes. Start the BASIC program, enter the name, then press Enter..."
)

for b in data:
    ser.write(f"{b:02X}".encode())
    ser.flush()
    time.sleep(0.1)
print("done")

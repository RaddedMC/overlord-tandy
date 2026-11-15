"""
on the Tandy 200

setup for emulator
- sudo socat pty,raw,echo=0,link=/dev/ttyUSB9 pty,raw,echo=0,link=/dev/ttyV1
- sudo chmod 666 /dev/ttyUSB9

1. open Telcom
2. type `Stat 88N1ENN`
3. use F4(`Term`)
4. then F2('Down')
5. type the filename ('DWN.DO')
    - beware of 8 character filename limit

6. run this script
    - `python updo.py dwn.do /dev/ttyV1` (emulator)
    - `python updo.py dwn.do /dev/ttyUSB0` (hardware)
"""

import sys, time, serial

path, port = sys.argv[1], sys.argv[2]
ser = serial.Serial(port, 9600, 8, "N", 1, xonxoff=True)
text = open(path, "rb").read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
for b in text:
    ser.write(bytes([b]))
    ser.flush()
    time.sleep(0.01)
print("done")

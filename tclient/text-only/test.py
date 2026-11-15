#!/usr/bin/env python3
"""Minimal terminal for the Tandy 200 chat program.
Usage: python chat200_term.py COM3      (or /dev/ttyUSB0)
Requires: pip install pyserial
"""

import sys
import threading
import serial

port = sys.argv[1] if len(sys.argv) > 1 else "COM3"
ser = serial.Serial(port, 9600, bytesize=8, parity="N", stopbits=1, timeout=0.1)


def reader():
    while True:
        data = ser.read(256)
        if data:
            print(data.decode("ascii", errors="replace"), end="", flush=True)


threading.Thread(target=reader, daemon=True).start()

try:
    while True:
        line = input()
        ser.write((line + "\r\n").encode("ascii", errors="replace"))
except (KeyboardInterrupt, EOFError):
    ser.close()

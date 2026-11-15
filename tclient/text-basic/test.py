#!/usr/bin/env python3
"""Serial bridge between a Tandy 200 and a chatbot on the PC.

Lines typed on the Tandy arrive here and are passed to handle_input().
Anything the chatbot wants to say goes back through send_response().

Usage: python tandy_bridge.py /dev/ttyUSB0
Requires: pip install pyserial
"""

import sys
import textwrap
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
WIDTH = 39  # the Tandy program keeps at most 39 chars per received line
LINE_DELAY = 0.2  # seconds between lines, so the BASIC program can keep up

ser = serial.Serial(
    PORT, 9600, bytesize=8, parity="N", stopbits=1, timeout=0.1, xonxoff=True
)


def send_response(text):
    """Send text to the Tandy, wrapped to its screen width."""
    for para in text.splitlines() or [""]:
        for line in textwrap.wrap(para, WIDTH) or [""]:
            ser.write((line + "\r\n").encode("ascii", errors="replace"))
            ser.flush()
            time.sleep(LINE_DELAY)


def handle_input(text):
    """Chatbot hook: called with each line typed on the Tandy.

    Call send_response(...) with the reply (once or several times).
    """
    # Placeholder: a person types the reply at the PC terminal.
    reply = input("Reply> ")
    if reply:
        send_response(reply)


def main():
    buf = bytearray()
    print(f"Listening on {PORT}")
    while True:
        for b in ser.read(256):
            if b == 13:  # CR ends the line
                text = buf.decode("ascii", errors="replace").strip()
                buf.clear()
                if text:
                    print(f"Tandy: {text}")
                    handle_input(text)
            elif b != 10:  # ignore LF
                buf.append(b)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        ser.close()

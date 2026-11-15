#!/usr/bin/env python3
"""Turn a Tandy .CO file into a self-unpacking BASIC .DO file.

Usage: python co2do.py TXT.CO [OUT.DO]

On the Tandy:  LOAD "TXT.DO"  (or RUN "TXT.DO"), then RUN.
It POKEs the code into memory and SAVEMs it as a .CO file.
"""

import os
import sys

src = sys.argv[1]
dst = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + ".DO"

data = open(src, "rb").read()
addr, length, entry = (int.from_bytes(data[i : i + 2], "little") for i in (0, 2, 4))
code = data[6:]
assert length == len(code), "header length doesn't match file size"

name = os.path.splitext(os.path.basename(src))[0].upper()[:6]
checksum = sum(code)

lines = [
    f"10 CLEAR 256,{addr}",
    f"20 A={addr}:L={length}:E={entry}:S=0",
    "30 FOR I=0 TO L-1:READ B:POKE A+I,B:S=S+B:NEXT",
    f'40 IF S<>{checksum} THEN PRINT "Checksum error":END',
    f'50 SAVEM "{name}",A,A+L-1,E',
    f'60 PRINT "Saved {name}.CO":END',
]
n = 100
for i in range(0, len(code), 16):
    chunk = ",".join(str(b) for b in code[i : i + 16])
    lines.append(f"{n} DATA {chunk}")
    n += 10

with open(dst, "wb") as f:
    f.write(("\r\n".join(lines) + "\r\n").encode("ascii"))
    f.write(b"\x1a")  # Tandy end-of-file marker

print(f"Wrote {dst}: {len(lines)} lines, {length} bytes, load {addr:#06x}")

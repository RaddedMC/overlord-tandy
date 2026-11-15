import sys, struct

src, dst, addr = sys.argv[1], sys.argv[2], int(sys.argv[3], 16)
code = open(src, "rb").read()
open(dst, "wb").write(struct.pack("<HHH", addr, len(code), addr) + code)

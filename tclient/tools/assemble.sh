#/bin/bash

asl -L -o hello/hello.p hello/hello.asm
p2bin -r \$-\$ hello/hello.p hello/hello.bin
mkco hello/hello.bin hello/HELLO.CO 

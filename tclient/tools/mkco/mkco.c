#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int convert(const char* restrict in, const char* restrict out, uint16_t addr) {
    FILE* inf;
    FILE* ouf;

    inf = fopen(in, "rb");
    ouf = fopen(out, "wb");

    if (inf == NULL || ouf == NULL) {
        fprintf(stderr, "files couldn't be opened");
        return 1;
    }

    fseek(inf, 0, SEEK_END);
    long n = ftell(inf);
    rewind(inf);
    if (n < 0 || n > 0xFFFF) {
        fprintf(stderr, "file too large for 16-bit length\n");
        fclose(inf);
        fclose(ouf);
        return 1;
    }

    uint16_t len = (uint16_t)n;
    uint8_t header[6] = {addr & 0xFF, addr >> 8, len & 0xFF, len >> 8, addr & 0xFF, addr >> 8};

    fwrite(header, sizeof(uint8_t), 6, ouf);

    size_t bytes = 1;
    char buffer[4096];
    while (bytes != 0) {
        bytes = fread(buffer, sizeof(char), 4096, inf);
        fwrite(buffer, sizeof(char), bytes, ouf);
    }

    fclose(inf);
    fclose(ouf);
    return 0;
}

int main(int argc, char** argv) {
    if (argc > 1 && strcmp(argv[1], "--help") == 0) {
        fprintf(stdout, "usage: %s <prog_address> <input> [output]\n", argv[0]);
        fprintf(stdout, "%s 0xEC00 test\n", argv[0]);
        fprintf(stdout, "%s 0xEC00 test out.co\n", argv[0]);
        return 0;
    }

    if (!(argc >= 3 && argc <= 4)) {
        fprintf(stderr, "usage: %s <prog_address> <input> [output]\n", argv[0]);
        return 1;
    }

    const char* addrstr = argv[1];
    char* end;
    unsigned long v = strtoul(argv[1], &end, 16);
    if (*end != '\0' || end == argv[1] || strlen(addrstr) != 6) {
        fprintf(stderr, "program address should be a 4 digit hex");
        return 1;
    }

    const char* in = argv[2];
    char* out_buf = NULL;
    const char* out = argv[3 < argc ? 3 : 0];

    if (argc == 3) {
        const char* slash = strrchr(in, '/');
        const char* dot = strrchr(in, '.');
        size_t stem = (dot && (!slash || dot > slash)) ? (size_t)(dot - in) : strlen(in);
        out_buf = (char*)malloc((stem + sizeof(".co")) * sizeof(char));

        memcpy(out_buf, in, stem);
        strcpy(out_buf + stem, ".co");
        out = out_buf;
    }

    if (strcmp(in, out) == 0) {
        fprintf(stderr, "input file already has the co extension\n");
        return 1;
    }

    int exit = convert(in, out, (uint16_t)v);

    if (argc == 3) {
        free(out_buf);
    }
    return exit;
}

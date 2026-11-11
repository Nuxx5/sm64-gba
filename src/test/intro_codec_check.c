#include <stdio.h>
#include <string.h>
#include "intro_codec.h"

#define CHECK(x) do { if (!(x)) { printf("FAIL line %d: %s\n", __LINE__, #x); return 1; } } while (0)

int main(void) {
    unsigned short page[10], old[10];
    unsigned short valid[] = {2, 11, 22, 0x4003, 33, 0x8003, 0};
    unsigned short expected[] = {0x5555, 11, 22, 33, 33, 33, 0xAAAA, 0xAAAA, 0xAAAA, 0x5555};
    unsigned short reserved[] = {0xC008, 0};
    unsigned short overflow[] = {0x8009, 0};
    unsigned short empty_run[] = {0x4000, 1, 0};
    unsigned short early_end[] = {0};
    unsigned short trailing[] = {0x8008, 0, 9};
    unsigned i;
    for (i = 0; i < 10; i++) page[i] = 0xAAAA;
    page[0] = page[9] = 0x5555;
    CHECK(intro_decode(valid, sizeof(valid)/2, page+1, 8));
    CHECK(memcmp(page, expected, sizeof(page)) == 0);
    memcpy(old, page, sizeof(page));
    CHECK(!intro_decode(reserved, sizeof(reserved)/2, page+1, 8));
    CHECK(!intro_decode(overflow, sizeof(overflow)/2, page+1, 8));
    CHECK(!intro_decode(empty_run, sizeof(empty_run)/2, page+1, 8));
    CHECK(!intro_decode(early_end, sizeof(early_end)/2, page+1, 8));
    CHECK(!intro_decode(trailing, sizeof(trailing)/2, page+1, 8));
    CHECK(memcmp(old, page, sizeof(page)) == 0);
    for (i = 0; i < sizeof(valid)/2; i++) {
        CHECK(!intro_decode(valid, i, page+1, 8));
        CHECK(page[0] == 0x5555 && page[9] == 0x5555);
    }
    puts("PASS: intro literal/repeat/skip, truncated/invalid streams and destination bounds");
    return 0;
}

/* Save tests use the real byte writer with a power cut after each write. */
#include <stdio.h>
#include <string.h>
#include "save.h"

static unsigned char ram[2 * SAVE_SLOT_STRIDE], original[sizeof(ram)];
static int writes, budget;
static int interrupted(void *context, unsigned at, unsigned char value) {
    (void) context;
    if (writes++ >= budget) return 0;
    ram[at] = value;
    return 1;
}

#define CHECK(x) do { if (!(x)) { printf("FAIL line %d: %s\n", __LINE__, #x); return 1; } } while (0)

int main(void) {
    struct SaveData old, changed, loaded;
    struct SaveStorage store = {ram, NULL, NULL};
    int cut, i;
    memset(ram, 0xFF, sizeof(ram));
    CHECK(!save_load(&store, &loaded));
    CHECK(loaded.level == 0 && loaded.lives == 4);
    save_new(&old);
    old.coins[0][0] = 3;
    old.bestCoins[0] = 2;
    old.stars = 1;
    CHECK(save_commit(&store, &old));
    CHECK(save_load(&store, &loaded));
    CHECK(loaded.coins[0][0] == 3 && loaded.bestCoins[0] == 2 && loaded.stars == 1);
    memcpy(original, ram, sizeof(ram));
    changed = old;
    changed.level = 2;
    changed.lives = 3;
    changed.visited = 7;
    changed.stars = 5;
    changed.coins[2][11] = 128;
    store.write_byte = interrupted;
    for (cut = 0; cut <= SAVE_SLOT_BYTES + 4; cut++) {
        memcpy(ram, original, sizeof(ram));
        writes = 0; budget = cut;
        save_commit(&store, &changed);
        CHECK(save_load(&store, &loaded));
        CHECK(loaded.level == (cut == SAVE_SLOT_BYTES + 4 ? 2 : 0));
        CHECK(loaded.coins[0][0] == 3);
        CHECK(loaded.stars == (cut == SAVE_SLOT_BYTES + 4 ? 5 : 1));
    }
    store.write_byte = NULL;
    changed.level = 3;
    CHECK(save_commit(&store, &changed));
    /* Every individual byte corruption must leave the older record usable. */
    memcpy(original, ram, sizeof(ram));
    for (i = 0; i < SAVE_SLOT_BYTES; i++) {
        memcpy(ram, original, sizeof(ram));
        ram[i] ^= 1; /* newest record is slot zero after the extra commit */
        CHECK(save_load(&store, &loaded));
        CHECK(loaded.level == 2);
    }
    memset(ram, 0, sizeof(ram));
    CHECK(!save_load(&store, &loaded));
    changed.level = 4;
    CHECK(!save_commit(&store, &changed));
    changed.level = 0;
    changed.stars = 16;
    CHECK(!save_commit(&store, &changed));
    puts("PASS: save round trip, 101 interrupted writes, corruption fallback and invalid data");
    return 0;
}

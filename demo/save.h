#ifndef DEMO_SAVE_H
#define DEMO_SAVE_H

#define SAVE_LEVELS 4
#define SAVE_COIN_BYTES 12
#define SAVE_SLOT_BYTES 96
#define SAVE_SLOT_STRIDE 128
#define SAVE_RAM_OFFSET 4096

struct SaveData {
    unsigned char level, lives, visited;
    unsigned char coins[SAVE_LEVELS][SAVE_COIN_BYTES];
    unsigned short bestCoins[SAVE_LEVELS];
};

/* The optional byte writer lets tests interrupt actual writes at every byte.
 * Production uses direct, byte-wide cartridge SRAM accesses. */
struct SaveStorage {
    volatile unsigned char *bytes;
    int (*write_byte)(void *context, unsigned offset, unsigned char value);
    void *context;
};

void save_new(struct SaveData *data);
int save_load(const struct SaveStorage *storage, struct SaveData *data);
int save_commit(const struct SaveStorage *storage, const struct SaveData *data);

#endif

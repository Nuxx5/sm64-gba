/* Versioned 32KB SRAM save. Two checked records, with the magic committed
 * last, protect the previous checkpoint against interrupted writes. */
#include "save.h"

__attribute__((used, aligned(4))) static const char kSaveType[] = "SRAM_V113";

static unsigned get32(const unsigned char *p) {
    return (unsigned) p[0] | ((unsigned) p[1] << 8) | ((unsigned) p[2] << 16) | ((unsigned) p[3] << 24);
}

static void put32(unsigned char *p, unsigned value) {
    int i;
    for (i = 0; i < 4; i++) p[i] = (unsigned char) (value >> (8 * i));
}

static unsigned crc32(const unsigned char *data, unsigned count) {
    unsigned crc = ~0u, i, bit;
    for (i = 0; i < count; i++) {
        crc ^= data[i];
        for (bit = 0; bit < 8; bit++) crc = (crc >> 1) ^ ((0u - (crc & 1)) & 0xEDB88320u);
    }
    return ~crc;
}

void save_new(struct SaveData *data) {
    unsigned i, j;
    data->level = 0;
    data->lives = 4;
    data->visited = 1;
    data->stars = 0;
    for (i = 0; i < SAVE_LEVELS; i++) {
        data->bestCoins[i] = 0;
        for (j = 0; j < SAVE_COIN_BYTES; j++) data->coins[i][j] = 0;
    }
}

static int read_slot(const struct SaveStorage *storage, unsigned slot, unsigned char *record) {
    unsigned i, at = slot * SAVE_SLOT_STRIDE;
    for (i = 0; i < SAVE_SLOT_BYTES; i++) record[i] = storage->bytes[at + i];
    if (record[0] != 'S' || record[1] != 'M' || record[2] != 'G' || record[3] != 'B'
        || record[4] != 1 || record[5] != 0 || record[6] != 0 || record[7] != 0
        || record[12] >= SAVE_LEVELS || record[13] > 99 || record[14] > 15 || record[15] > 15) return 0;
    return crc32(record + 4, SAVE_SLOT_BYTES - 8) == get32(record + SAVE_SLOT_BYTES - 4);
}

static int newest_slot(const struct SaveStorage *storage, unsigned *sequence) {
    unsigned char record[SAVE_SLOT_BYTES];
    unsigned a = 0, b = 0;
    int va = read_slot(storage, 0, record), vb;
    if (va) a = get32(record + 8);
    vb = read_slot(storage, 1, record);
    if (vb) b = get32(record + 8);
    if (!va && !vb) return -1;
    if (vb && (!va || (b != a && (b - a) < 0x80000000u))) {
        *sequence = b;
        return 1;
    }
    *sequence = a;
    return 0;
}

int save_load(const struct SaveStorage *storage, struct SaveData *data) {
    unsigned sequence, i, j;
    unsigned char record[SAVE_SLOT_BYTES];
    int slot = newest_slot(storage, &sequence);
    if (slot < 0) {
        save_new(data);
        return 0;
    }
    read_slot(storage, (unsigned) slot, record);
    data->level = record[12];
    data->lives = record[13];
    data->visited = record[14];
    data->stars = record[15];
    for (i = 0; i < SAVE_LEVELS; i++) {
        for (j = 0; j < SAVE_COIN_BYTES; j++) data->coins[i][j] = record[16 + i * SAVE_COIN_BYTES + j];
        data->bestCoins[i] = (unsigned short) (record[64 + i * 2] | (record[65 + i * 2] << 8));
    }
    return 1;
}

static int write_byte(const struct SaveStorage *storage, unsigned at, unsigned char value) {
    if (storage->write_byte) return storage->write_byte(storage->context, at, value);
    storage->bytes[at] = value;
    return 1;
}

int save_commit(const struct SaveStorage *storage, const struct SaveData *data) {
    unsigned sequence = 0, i, j, at;
    unsigned char record[SAVE_SLOT_BYTES];
    int previous;
    if (data->level >= SAVE_LEVELS || data->lives > 99 || data->visited > 15 || data->stars > 15) return 0;
    previous = newest_slot(storage, &sequence);
    at = (previous == 0 ? 1u : 0u) * SAVE_SLOT_STRIDE;
    for (i = 0; i < SAVE_SLOT_BYTES; i++) record[i] = 0;
    record[0] = 'S'; record[1] = 'M'; record[2] = 'G'; record[3] = 'B';
    record[4] = 1;
    put32(record + 8, sequence + 1);
    record[12] = data->level;
    record[13] = data->lives;
    record[14] = data->visited;
    record[15] = data->stars;
    for (i = 0; i < SAVE_LEVELS; i++) {
        for (j = 0; j < SAVE_COIN_BYTES; j++) record[16 + i * SAVE_COIN_BYTES + j] = data->coins[i][j];
        record[64 + 2 * i] = (unsigned char) data->bestCoins[i];
        record[65 + 2 * i] = (unsigned char) (data->bestCoins[i] >> 8);
    }
    put32(record + SAVE_SLOT_BYTES - 4, crc32(record + 4, SAVE_SLOT_BYTES - 8));
    for (i = 0; i < 4; i++) if (!write_byte(storage, at + i, 0)) return 0;
    for (i = 4; i < SAVE_SLOT_BYTES; i++) if (!write_byte(storage, at + i, record[i])) return 0;
    for (i = 0; i < 4; i++) if (!write_byte(storage, at + i, record[i])) return 0;
    return read_slot(storage, at / SAVE_SLOT_STRIDE, record);
}

#include "gba.h"
#include "intro.h"

#ifdef DEMO_INTRO
#include "intro_codec.h"
#include "intro_data.h"

extern volatile u32 gVBlankCount;
extern void (*volatile gVBlankHook)(void);
extern void fill_words(u32 *destination, u32 value, s32 count);

static void wait_blank(void) {
    u32 frame = gVBlankCount;
    while (gVBlankCount == frame) {}
}

static void audio_stop(void) {
    REG16(0x04000102) = 0; /* timer 0 */
    REG16(0x040000C6) = 0; /* DMA 1 */
    REG16(0x04000082) = 0x0802; /* Direct Sound off, FIFO A reset */
}

static void audio_start(void) {
    audio_stop();
    REG16(0x04000084) = 0x0080; /* sound master */
    REG16(0x04000082) = 0x0B06; /* A 100%, both sides, timer 0 */
    REG32(0x040000BC) = (u32) gIntroAudio;
    REG32(0x040000C0) = 0x040000A0;
    REG16(0x040000C6) = 0xB640; /* FIFO timing, word, repeat, fixed dest */
    /* Exactly 224 samples per GBA frame: 1254 * 224 = 280896 cycles. */
    REG16(0x04000100) = (u16) (65536 - 1254);
    REG16(0x04000102) = 0x0080;
}

static void hex8(char *text, u32 value) {
    s32 i;
    for (i = 7; i >= 0; i--) {
        text[i] = "0123456789ABCDEF"[value & 15];
        value >>= 4;
    }
}

static void report(void (*logger)(const char *), u32 frame, u32 tick, u32 late) {
    char text[] = "intro frame 00000000 tick 00000000 late 00000000";
    if (!logger) return;
    hex8(text + 12, frame);
    hex8(text + 26, tick);
    hex8(text + 40, late);
    logger(text);
}

void intro_run(void (*logger)(const char *)) {
    void (*hook)(void) = gVBlankHook;
    u32 i, previous, start, frame, late = 0;
    int skipped = 0, failed = 0;
    gVBlankHook = 0; /* chip and PCM level music must not touch movie audio */
    audio_stop();
    REG_DISPCNT = 0x0080;
    for (i = 0; i < 128; i++) OAM[i * 4] = 0x0200;
    REG_BG2PA = REG_BG2PD = 256;
    REG_BG2PB = REG_BG2PC = 0;
    REG_BG2X = REG_BG2Y = 0;
    fill_words((u32 *) 0x06000000, 0, 2 * 0xA000 / 4);
    for (i = 0; i < 256; i++) PAL_BG[i] = gIntroPalette[i];
    /* The title's Start press selects New Game; only a fresh press skips. */
    do {
        wait_blank();
        previous = ~REG_KEYINPUT & 0x3FF;
    } while (previous & KEY_START);
    if (!intro_decode(gIntroVideo, gIntroOffsets[1], VRAM, INTRO_WORDS)) {
        failed = 1;
        goto cleanup;
    }
    wait_blank();
    REG_DISPCNT = DCNT_MODE4 | DCNT_BG2;
    start = gVBlankCount;
    audio_start();
    if (logger) logger("intro ready");
    report(logger, 0, 0, 0);
    for (frame = 1; frame <= INTRO_FRAMES; frame++) {
        u32 deadline = frame * INTRO_PERIOD;
        if (frame < INTRO_FRAMES) {
            volatile u16 *back = (volatile u16 *) ((frame & 1) ? 0x0600A000 : 0x06000000);
            u32 offset = gIntroOffsets[frame];
            if (!intro_decode(gIntroVideo + offset, gIntroOffsets[frame+1] - offset, back, INTRO_WORDS)) {
                failed = 1;
                break;
            }
        }
        if (gVBlankCount - start > deadline) late++;
        do {
            u32 keys = ~REG_KEYINPUT & 0x3FF;
            if ((keys & ~previous) & KEY_START) {
                skipped = 1;
                goto cleanup;
            }
            previous = keys;
            if (gVBlankCount - start >= deadline) break;
            wait_blank();
        } while (1);
        if (frame < INTRO_FRAMES) {
            REG_DISPCNT = DCNT_MODE4 | DCNT_BG2 | ((frame & 1) ? DCNT_PAGE : 0);
            report(logger, frame, gVBlankCount - start, late);
        }
    }
cleanup:
    audio_stop();
    REG_DISPCNT = 0x0080;
    gVBlankHook = hook;
    if (logger) logger(failed ? "intro error" : skipped ? "intro skipped" : "intro done");
}
#else
void intro_run(void (*logger)(const char *)) { (void) logger; }
#endif

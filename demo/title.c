#include "gba.h"
#include "hud.h"
#include "title.h"

extern volatile u32 gVBlankCount;
#ifdef DEMO_TITLE_ART
extern const u16 gImpTitlePalette[256];
extern const u16 gImpTitleFrames[][19200];
extern const u16 gImpTitleFrameCount;
#endif

static void wait_blank(void) {
    u32 frame = gVBlankCount;
    while (gVBlankCount == frame) {}
}

int title_run(int haveSave, void (*logger)(const char *)) {
    u32 previous, frame = 0, i;
    s32 confirm = 0;
    REG_DISPCNT = 0x0080;
    for (i = 0; i < 128; i++) OAM[i * 4] = 0x0200;
    REG_BG2PA = REG_BG2PD = 256;
    REG_BG2PB = REG_BG2PC = 0;
    REG_BG2X = REG_BG2Y = 0;
#ifdef DEMO_TITLE_ART
    for (i = 0; i < 256; i++) PAL_BG[i] = gImpTitlePalette[i];
#else
    PAL_BG[0] = 0;
#endif
    for (i = 0; i < 19200; i++) VRAM[i] = 0;
    REG_DISPCNT = DCNT_MODE4 | DCNT_BG2 | DCNT_OBJ | DCNT_OBJ_1D;
    /* Returning with L+R+Start held must not immediately choose New Game. */
    do {
        wait_blank();
        previous = ~REG_KEYINPUT & 0x3FF;
    } while (previous);
    if (logger) logger("title ready");
    for (;;) {
        volatile u16 *back = (volatile u16 *) ((REG_DISPCNT & DCNT_PAGE) ? 0x06000000 : 0x0600A000);
        u32 keys = ~REG_KEYINPUT & 0x3FF, pressed = keys & ~previous;
        previous = keys;
#ifdef DEMO_TITLE_ART
        /* Replay native title frames forward/backward for a continuous
         * idle loop. All image data was generated locally from the ROM. */
        u32 count = gImpTitleFrameCount, at = count > 1 ? frame % (count * 2 - 2) : 0;
        if (at >= count) at = count * 2 - 2 - at;
        for (i = 0; i < 19200; i++) back[i] = gImpTitleFrames[at][i];
#else
        for (i = 0; i < 19200; i++) back[i] = 0;
#endif
        hud_clear();
#ifndef DEMO_TITLE_ART
        hud_text(78, 52, "SUPER MARIO 64");
        hud_text(84, 138, "PRESS START");
#endif
        if (confirm) {
            for (i = 128 * 120; i < 160 * 120; i++) back[i] = 0;
            PAL_BG[0] = 0;
            hud_text(70, 134, "REPLACE SAVE?");
            hud_text(70, 146, "A YES  B BACK");
            if (pressed & KEY_B) confirm = 0;
            if (pressed & KEY_A) return 1;
        } else {
            if (haveSave) hud_text(92, 152, "A CONTINUE");
            if (haveSave && (pressed & KEY_A)) return 2;
            if (pressed & KEY_START) {
                if (!haveSave) return 1;
                confirm = 1;
                if (logger) logger("title confirm");
            }
        }
        wait_blank();
        REG_DISPCNT ^= DCNT_PAGE;
        hud_commit();
        wait_blank();
        frame++;
    }
}

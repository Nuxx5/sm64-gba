/*
 * Performance HUD: text drawn with hardware sprites (8x8, 4bpp) so it costs
 * the renderer nothing. 3x5 pixel glyphs with a dark drop shadow.
 */
#include "gba.h"
#include "hud.h"

#define HUD_TILE_BASE 512 /* first OBJ tile usable in bitmap modes */
#define HUD_MAX_SPRITES 35 /* OAM 0..34; 35: the health meter; the rest: demo/actors.c, coins.c, mannequin.c */

static const char kGlyphChars[] = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ%/:.- ";
/* 5 rows of 3 pixels per glyph, '#' = set */
static const char *const kGlyphs[] = {
    "###", "#.#", "#.#", "#.#", "###", /* 0 */
    ".#.", "##.", ".#.", ".#.", "###", /* 1 */
    "###", "..#", "###", "#..", "###", /* 2 */
    "###", "..#", ".##", "..#", "###", /* 3 */
    "#.#", "#.#", "###", "..#", "..#", /* 4 */
    "###", "#..", "###", "..#", "###", /* 5 */
    "###", "#..", "###", "#.#", "###", /* 6 */
    "###", "..#", "..#", ".#.", ".#.", /* 7 */
    "###", "#.#", "###", "#.#", "###", /* 8 */
    "###", "#.#", "###", "..#", "###", /* 9 */
    ".#.", "#.#", "###", "#.#", "#.#", /* A */
    "##.", "#.#", "##.", "#.#", "##.", /* B */
    ".##", "#..", "#..", "#..", ".##", /* C */
    "##.", "#.#", "#.#", "#.#", "##.", /* D */
    "###", "#..", "##.", "#..", "###", /* E */
    "###", "#..", "##.", "#..", "#..", /* F */
    ".##", "#..", "#.#", "#.#", ".##", /* G */
    "#.#", "#.#", "###", "#.#", "#.#", /* H */
    "###", ".#.", ".#.", ".#.", "###", /* I */
    "..#", "..#", "..#", "#.#", ".#.", /* J */
    "#.#", "#.#", "##.", "#.#", "#.#", /* K */
    "#..", "#..", "#..", "#..", "###", /* L */
    "#.#", "###", "###", "#.#", "#.#", /* M */
    "##.", "#.#", "#.#", "#.#", "#.#", /* N */
    ".#.", "#.#", "#.#", "#.#", ".#.", /* O */
    "##.", "#.#", "##.", "#..", "#..", /* P */
    ".#.", "#.#", "#.#", "##.", ".##", /* Q */
    "##.", "#.#", "##.", "#.#", "#.#", /* R */
    ".##", "#..", ".#.", "..#", "##.", /* S */
    "###", ".#.", ".#.", ".#.", ".#.", /* T */
    "#.#", "#.#", "#.#", "#.#", "###", /* U */
    "#.#", "#.#", "#.#", "#.#", ".#.", /* V */
    "#.#", "#.#", "###", "###", "#.#", /* W */
    "#.#", "#.#", ".#.", "#.#", "#.#", /* X */
    "#.#", "#.#", ".#.", ".#.", ".#.", /* Y */
    "###", "..#", ".#.", "#..", "###", /* Z */
    "#.#", "..#", ".#.", "#..", "#.#", /* % */
    "..#", "..#", ".#.", "#..", "#..", /* / */
    "...", ".#.", "...", ".#.", "...", /* : */
    "...", "...", "...", "...", ".#.", /* . */
    "...", "...", "###", "...", "...", /* - */
    "...", "...", "...", "...", "...", /* space */
};

static s32 glyph_index(char c) {
    s32 i;
    if (c >= 'a' && c <= 'z') c = (char) (c - 'a' + 'A');
    for (i = 0; kGlyphChars[i]; i++) {
        if (kGlyphChars[i] == c) return i;
    }
    return (s32) sizeof(kGlyphChars) - 2; /* space */
}

static u16 sOamShadow[HUD_MAX_SPRITES * 4];
static s32 sUsed;

void hud_init(void) {
    s32 g, row, col, i;
    volatile u16 *tiles = OBJ_VRAM_BITMAP;
    /* 4bpp tile: 8 rows of 4 bytes, low nibble = left pixel. Glyph at (2,1),
     * shadow one pixel down-right. Color 1 = text, 2 = shadow. */
    for (g = 0; kGlyphChars[g]; g++) {
        u8 pix[8][8];
        for (row = 0; row < 8; row++)
            for (col = 0; col < 8; col++) pix[row][col] = 0;
        for (row = 0; row < 5; row++)
            for (col = 0; col < 3; col++)
                if (kGlyphs[g * 5 + row][col] == '#') pix[row + 2][col + 3] = 2;
        for (row = 0; row < 5; row++)
            for (col = 0; col < 3; col++)
                if (kGlyphs[g * 5 + row][col] == '#') pix[row + 1][col + 2] = 1;
        for (row = 0; row < 8; row++) {
            for (i = 0; i < 2; i++) {
                u16 v = (u16) (pix[row][i * 4] | (pix[row][i * 4 + 1] << 4) | (pix[row][i * 4 + 2] << 8)
                               | (pix[row][i * 4 + 3] << 12));
                tiles[g * 16 + row * 2 + i] = v;
            }
        }
    }
    PAL_OBJ[1] = RGB15(255, 255, 240);
    PAL_OBJ[2] = RGB15(16, 16, 24);
    hud_clear();
    hud_commit();
}

void hud_clear(void) {
    s32 i;
    for (i = 0; i < HUD_MAX_SPRITES; i++) {
        sOamShadow[i * 4 + 0] = 0x0200; /* hidden */
        sOamShadow[i * 4 + 1] = 0;
        sOamShadow[i * 4 + 2] = 0;
    }
    sUsed = 0;
}

void hud_text(s32 x, s32 y, const char *s) {
    for (; *s; s++, x += 5) {
        if (*s == ' ') continue;
        if (sUsed >= HUD_MAX_SPRITES) return;
        sOamShadow[sUsed * 4 + 0] = (u16) (y & 0xFF);          /* square, 4bpp */
        sOamShadow[sUsed * 4 + 1] = (u16) (x & 0x1FF);         /* 8x8 */
        sOamShadow[sUsed * 4 + 2] = (u16) (HUD_TILE_BASE + glyph_index(*s));
        sUsed++;
    }
}

/* Copy to OAM: call during VBlank. */
void hud_commit(void) {
    s32 i;
    for (i = 0; i < HUD_MAX_SPRITES * 4; i++) {
        if ((i & 3) == 3) continue; /* affine slots */
        OAM[i] = sOamShadow[i];
    }
}

/* Small integer formatting without libc. */
char *hud_fmt_int(char *out, s32 v, s32 width) {
    char tmp[12];
    s32 n = 0, neg = v < 0;
    u32 u = neg ? (u32) (-v) : (u32) v;
    do {
        tmp[n++] = (char) ('0' + u % 10);
        u /= 10;
    } while (u && n < 11);
    if (neg) tmp[n++] = '-';
    while (n < width) tmp[n++] = ' ';
    while (n > 0) *out++ = tmp[--n];
    *out = 0;
    return out;
}

/* ---------- health meter ----------
 * SM64's power meter: 8 wedges, one per unit of health (health >> 8), drawn
 * clockwise from the top into one 32x32 sprite whose tiles are redrawn when
 * the count changes. Like the game's, it shows while health isn't full and
 * for a moment after it fills up again. */
#define METER_OAM 35
#define METER_TILE 1002     /* 16 tiles, after the trees' (832..1001) */
#define METER_BANK 14
static s32 sMeterWedges = -1, sMeterShowTimer;
static u16 sMeterOam[3] = { 0x0200, 0, 0 };

static s32 octant(s32 dx, s32 dy) { /* 0..7, clockwise from 12 o'clock */
    s32 ax = dx < 0 ? -dx : dx, ay = dy < 0 ? -dy : dy;
    if (dx >= 0 && dy < 0) return ax < ay ? 0 : 1;
    if (dx >= 0) return ax >= ay ? 2 : 3;
    if (dy > 0) return ax < ay ? 4 : 5;
    return ax >= ay ? 6 : 7;
}

#ifdef DEMO_SPRITE_ART
/* the game's power meter, from your ROM (build/import/sprite_art.c) */
extern const u16 gImpMeterPal[15];
extern const u8 gImpMeterArt[9][32 * 32];

static void meter_draw(s32 wedges) {
    volatile u16 *tiles = OBJ_VRAM_BITMAP + (METER_TILE - 512) * 16;
    const u8 *art = gImpMeterArt[wedges];
    s32 x, y;
    for (y = 0; y < 32; y++) {
        for (x = 0; x < 32; x += 4) {
            const u8 *p = &art[y * 32 + x];
            tiles[((y >> 3) * 4 + (x >> 3)) * 16 + (y & 7) * 2 + ((x & 4) >> 2)] =
                (u16) (p[0] | (p[1] << 4) | (p[2] << 8) | (p[3] << 12));
        }
    }
}
#else
static void meter_draw(s32 wedges) {
    volatile u16 *tiles = OBJ_VRAM_BITMAP + (METER_TILE - 512) * 16;
    s32 x, y, i;
    /* color by what's left: blue, green, yellow, red */
    s32 fill = wedges >= 7 ? 6 : wedges >= 5 ? 5 : wedges >= 3 ? 4 : 3;
    for (y = 0; y < 32; y++) {
        for (x = 0; x < 32; x += 4) {
            u16 v = 0;
            for (i = 0; i < 4; i++) {
                s32 dx = 2 * (x + i) - 31, dy = 2 * y - 31, dd = dx * dx + dy * dy, c = 0;
                if (dd <= 30 * 30) {
                    if (dd > 26 * 26 || dd < 7 * 7) c = 1;              /* rim, hub */
                    else c = octant(dx, dy) < wedges ? fill : 2;         /* wedge */
                    if (c > 2 && dx < -6 && dy < -6 && dd < 18 * 18) c = 7; /* shine */
                }
                v |= (u16) (c << (i * 4));
            }
            tiles[((y >> 3) * 4 + (x >> 3)) * 16 + (y & 7) * 2 + ((x & 4) >> 2)] = v;
        }
    }
}
#endif

void hud_meter_init(void) {
#ifdef DEMO_SPRITE_ART
    s32 i;
    for (i = 0; i < 15; i++) PAL_OBJ[METER_BANK * 16 + 1 + i] = gImpMeterPal[i];
    sMeterWedges = -1;
    return;
#endif
    PAL_OBJ[METER_BANK * 16 + 1] = RGB15(24, 24, 32);   /* rim */
    PAL_OBJ[METER_BANK * 16 + 2] = RGB15(90, 90, 100);  /* empty wedge */
    PAL_OBJ[METER_BANK * 16 + 3] = RGB15(232, 40, 32);  /* red */
    PAL_OBJ[METER_BANK * 16 + 4] = RGB15(248, 216, 32); /* yellow */
    PAL_OBJ[METER_BANK * 16 + 5] = RGB15(64, 200, 64);  /* green */
    PAL_OBJ[METER_BANK * 16 + 6] = RGB15(56, 120, 248); /* blue */
    PAL_OBJ[METER_BANK * 16 + 7] = RGB15(240, 240, 248);
    sMeterWedges = -1;
}

/* Once per game frame, with Mario's health (0x880 = full). */
void hud_meter_update(s32 health) {
    s32 wedges = health >> 8;
    if (wedges < 0) wedges = 0;
    if (wedges > 8) wedges = 8;
    if (wedges != sMeterWedges) {
        meter_draw(wedges);
        if (sMeterWedges >= 0) sMeterShowTimer = 60; /* not on a level load */
        sMeterWedges = wedges;
    }
    if (sMeterShowTimer > 0) sMeterShowTimer--;
    if (wedges < 8 || sMeterShowTimer > 0) {
        sMeterOam[0] = (u16) (2 & 0xFF);                       /* y 2, square */
        sMeterOam[1] = (u16) ((120 - 16) | (2 << 14));         /* x, 32x32 */
        sMeterOam[2] = (u16) (METER_TILE | (METER_BANK << 12));
    } else {
        sMeterOam[0] = 0x0200;
    }
}

void hud_meter_hide(void) {
    sMeterOam[0] = 0x0200;
    sMeterShowTimer = 0;
}

/* During VBlank. */
void hud_meter_commit(void) {
    OAM[METER_OAM * 4 + 0] = sMeterOam[0];
    OAM[METER_OAM * 4 + 1] = sMeterOam[1];
    OAM[METER_OAM * 4 + 2] = sMeterOam[2];
}

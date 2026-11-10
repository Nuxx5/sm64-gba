/*
 * Coins: the first objects in the demo. Placement comes straight from the
 * level's macro object list in the decomp (levels/<level>/areas/1/macro.inc.c),
 * decoded the way the game's spawn_macro_objects() does, and the coin
 * formations (lines, rings) are expanded with the offsets of
 * spawn_coin_in_formation() and bhv_coin_formation_spawn_loop()'s floor snap.
 *
 * With `make import ROM=...` they use the game's own coin art, from your ROM
 * (build/import/coin_art.c: the 4 spin textures, pre-scaled); without it, a
 * drawn stand-in that spins the same way.
 *
 * Coins don't touch Mario's physics (in the game a coin only heals him), so
 * the parity checks are unaffected. They are drawn as scaled hardware
 * sprites; like the mannequin, they aren't depth tested against the scene.
 */
#include <PR/ultratypes.h>
#include "sm64.h"
#include "types.h"
#include "macro_presets.h"
#include "level_misc_macros.h"
#include "dialog_ids.h"
#include "engine/surface_collision.h"
#include "gba.h"
#include "render.h"
#include "coins.h"

#include "levels/bob/areas/1/macro.inc.c"

extern const s16 gSinQ14[4096];

/* Per level (same order as gHarnessLevels): macro list, or NULL for none yet. */
static const MacroObject *const kLevelMacros[] = { bob_seg7_macro_objs, NULL, NULL, NULL };

#define MAX_COINS 96
/* OAM slots after the HUD's (0..47), before the mannequin's (108..127): the
 * mannequin's big affine sprites use up the scanline's sprite time, and the
 * sprites first in OAM get it first. These are plain (not affine) sprites,
 * pre-scaled, which cost a fraction of an affine sprite's time. */
#define OAM_FIRST 48
#define OAM_COUNT 60
#define COIN_TILE 600       /* pre-scaled sprites, 4bpp, 1D mapping: [color][frame][art size] */
#define NUM_SIZES 12
#define NUM_ART 9           /* sizes drawn as is; the rest are the 16 px art scaled by the GBA */
#define MTX_FIRST 20        /* affine matrices for those, after the mannequin's 0..19 */
#define SHADES 6            /* colors 3..8: yellow, 9..14: red (palette bank 0, after the HUD's) */
#define FOCAL 200

struct Coin {
    s16 x, y, z;   /* bottom center, as the game's object position */
    u8 red, taken;
};

static struct Coin sCoins[MAX_COINS];
static s32 sNumCoins, sNumRed;
static u16 sOam[OAM_COUNT][3];
/* the first NUM_ART must match COIN_SIZES in tools/import_rom.py */
static const u8 kSizes[NUM_SIZES] = { 3, 4, 5, 6, 8, 10, 12, 14, 16, 20, 24, 30 };
static u16 sTile[2][4][NUM_ART]; /* first tile of each sprite: [red][spin frame][size] */
static u32 sTick;

#ifdef DEMO_COIN_ART
extern const u8 gImpCoinArt[4][846]; /* build/import/coin_art.c */
#endif

s32 gCoinCount, gRedCoinCount, gRedCoinTotal;

static s32 qsin(s32 a) { return gSinQ14[(a & 0xFFFF) >> 4]; }
static s32 qcos(s32 a) { return gSinQ14[((a + 0x4000) & 0xFFFF) >> 4]; }

static void add_coin(s32 x, s32 y, s32 z, s32 red) {
    if (sNumCoins >= MAX_COINS) return;
    sCoins[sNumCoins].x = (s16) x;
    sCoins[sNumCoins].y = (s16) y;
    sCoins[sNumCoins].z = (s16) z;
    sCoins[sNumCoins].red = (u8) red;
    sCoins[sNumCoins].taken = 0;
    sNumCoins++;
    if (red) sNumRed++;
}

/* One coin of a formation: spawn_coin_in_formation() */
static void add_formation_coin(s32 i, s32 flags, s32 ox, s32 oy, s32 oz, s32 yaw) {
    s32 rx = 0, ry = 0, rz = 0, onGround = 1, x, y, z;
    switch (flags & COIN_FORMATION_BP_FLAG_MASK) {
        case COIN_FORMATION_BP_LINE_HORIZONTAL:
            if (i > 4) return;
            rz = 160 * (i - 2);
            break;
        case COIN_FORMATION_BP_LINE_VERTICAL:
            if (i > 4) return;
            onGround = 0;
            ry = 128 * i;
            break;
        case COIN_FORMATION_BP_RING_HORIZONTAL:
            rx = qsin(i << 13) * 300 >> 14;
            rz = qcos(i << 13) * 300 >> 14;
            break;
        case COIN_FORMATION_BP_RING_VERTICAL:
            onGround = 0;
            rx = qcos(i << 13) * 200 >> 14;
            ry = (qsin(i << 13) * 200 >> 14) + 200;
            break;
        default:
            return; /* arrows: not in these levels */
    }
    if (flags & COIN_FORMATION_BP_FLAG_FLYING) onGround = 0;
    /* parent-relative position, rotated by the formation's yaw */
    x = ox + ((rx * qcos(yaw) + rz * qsin(yaw)) >> 14);
    y = oy + ry;
    z = oz + ((rz * qcos(yaw) - rx * qsin(yaw)) >> 14);
    if (onGround) {
        struct Surface *floor;
        f32 fy = find_floor((f32) x, (f32) (y + 300), (f32) z, &floor);
        if (floor == NULL || (f32) (y + 300) < fy || fy < -10000.0f) return;
        y = (s32) fy;
    }
    add_coin(x, y, z, 0);
}

void coins_load(s32 level) {
    const MacroObject *m;
    sNumCoins = sNumRed = 0;
    gCoinCount = gRedCoinCount = 0;
    m = level < (s32) (sizeof(kLevelMacros) / sizeof(kLevelMacros[0])) ? kLevelMacros[level] : NULL;
    for (; m && *m != MACRO_OBJECT_END(); m += 5) {
        s32 preset = (m[0] & 0x1FF) - 31;
        s32 yaw = (((m[0] >> 9) & 0x7F) << 1) << 8; /* convert_rotation() */
        s32 x = m[1], y = m[2], z = m[3], i;
        switch (preset) {
            case macro_yellow_coin_1:
            case macro_yellow_coin_2:
                add_coin(x, y, z, 0);
                break;
            case macro_red_coin:
                add_coin(x, y, z, 1);
                break;
            case macro_coin_line_horizontal:
            case macro_coin_ring_horizontal:
            case macro_coin_line_horizontal_flying:
            case macro_coin_line_vertical_flying:
            case macro_coin_ring_horizontal_flying:
            case macro_coin_ring_vertical_flying: {
                static const u8 kFlags[] = {
                    COIN_FORMATION_BP_LINE_HORIZONTAL, COIN_FORMATION_BP_RING_HORIZONTAL, 0,
                    COIN_FORMATION_BP_LINE_HORIZONTAL | COIN_FORMATION_BP_FLAG_FLYING,
                    COIN_FORMATION_BP_LINE_VERTICAL | COIN_FORMATION_BP_FLAG_FLYING,
                    COIN_FORMATION_BP_RING_HORIZONTAL | COIN_FORMATION_BP_FLAG_FLYING,
                    COIN_FORMATION_BP_RING_VERTICAL | COIN_FORMATION_BP_FLAG_FLYING,
                };
                s32 flags = kFlags[preset - macro_coin_line_horizontal];
                for (i = 0; i < 8; i++) add_formation_coin(i, flags, x, y, z, yaw);
                break;
            }
            default:
                break; /* not a coin (boxes, trees, ...): later */
        }
    }
    gRedCoinTotal = sNumRed;
}

/* Collection: the coin hitboxes (radius 100, height 64) against Mario's
 * (radius 37, height 160), as in the game's obj_collide_with(). */
void coins_update(const f32 *pos) {
    s32 i, mx = (s32) pos[0], my = (s32) pos[1], mz = (s32) pos[2];
    for (i = 0; i < sNumCoins; i++) {
        struct Coin *c = &sCoins[i];
        s32 dx, dz;
        if (c->taken) continue;
        dx = c->x - mx;
        dz = c->z - mz;
        if (dx > 137 || dx < -137 || dz > 137 || dz < -137) continue;
        if (dx * dx + dz * dz > 137 * 137) continue;
        if (my + 160 < c->y || c->y + 64 < my) continue;
        c->taken = 1;
        if (c->red) {
            gRedCoinCount++;
            gCoinCount += 2;
        } else {
            gCoinCount++;
        }
    }
}

/* Shade 0 (transparent) or 1..SHADES of pixel (x, y) of spin frame f at size d. */
static s32 art_pixel(s32 f, s32 k, s32 x, s32 y) {
#ifdef DEMO_COIN_ART
    s32 i, at = 0;
    for (i = 0; i < k; i++) at += kSizes[i] * kSizes[i];
    return gImpCoinArt[f][at + y * kSizes[k] + x];
#else
    /* stand-in: a disc turning edge-on (front, tilted, side, tilted) */
    static const u8 kWidth[4] = { 16, 11, 3, 11 }; /* of 16 */
    s32 d = kSizes[k], r = d * 16, wq = kWidth[f];
    s32 dx = (2 * x + 1 - d) * 16 * 16 / wq, dy = (2 * y + 1 - d) * 16, dd = dx * dx + dy * dy;
    if (f == 2) return (2 * x + 1 - d) * (2 * x + 1 - d) <= (d > 6 ? 4 : 1) && dy * dy <= r * r ? 3 : 0;
    if (dd > r * r) return 0;
    if (dd > (r * 3 / 4) * (r * 3 / 4)) return 3;
    return (dx < -r / 6 && dy < 0) ? 6 : 5;
#endif
}

void coins_init(void) {
    volatile u16 *tiles = OBJ_VRAM_BITMAP;
    s32 t, f, k, x, y, i, tile = COIN_TILE;
    for (t = 0; t < 2; t++) {
        for (f = 0; f < 4; f++) {
            for (k = 0; k < NUM_ART; k++) {
                s32 d = kSizes[k], box = d <= 8 ? 8 : 16, w = box / 8, off = (box - d) / 2;
                sTile[t][f][k] = (u16) tile;
                for (y = 0; y < box; y++) {
                    for (x = 0; x < box; x += 4) {
                        u16 v = 0;
                        for (i = 0; i < 4; i++) {
                            s32 px = x + i - off, py = y - off, c = 0;
                            if (px >= 0 && px < d && py >= 0 && py < d) c = art_pixel(f, k, px, py);
                            if (c) c += 2 + t * SHADES;
                            v |= (u16) (c << (i * 4));
                        }
                        tiles[(tile - 512 + (y >> 3) * w + (x >> 3)) * 16 + (y & 7) * 2 + ((x & 4) >> 2)] = v;
                    }
                }
                tile += w * w;
            }
        }
    }
    /* the game multiplies the coin texture's intensity by the vertex color:
     * yellow (255, 255, 0) or red (255, 0, 0) */
    for (i = 1; i <= SHADES; i++) {
        s32 v = 255 * i / SHADES;
        PAL_OBJ[2 + i] = RGB15(v, v * 15 / 16, 0);
        PAL_OBJ[2 + SHADES + i] = RGB15(v, 0, 0);
    }
    coins_hide();
}

void coins_hide(void) {
    s32 i;
    for (i = 0; i < OAM_COUNT; i++) sOam[i][0] = 0x0200;
}

void coins_draw(const struct RCamera *cam, s32 farDist) {
    s32 sinY = qsin(cam->yaw), cosY = qcos(cam->yaw), sinP = qsin(cam->pitch), cosP = qcos(cam->pitch);
    s32 i, n = 0, f = (sTick++ >> 1) & 3; /* 2 game frames per spin frame */
    for (i = 0; i < sNumCoins && n < OAM_COUNT; i++) {
        const struct Coin *c = &sCoins[i];
        s32 vx, vy, vz, zf, cx, cy, cz, diam, sx, sy, k;
        if (c->taken) continue;
        vx = c->x - cam->x;
        vy = c->y + (c->red ? 35 : 32) - cam->y; /* center of the billboard */
        vz = c->z - cam->z;
        if (vx > farDist || vx < -farDist || vz > farDist || vz < -farDist) continue;
        /* camera space, as the renderer: x right, y up, z forward */
        zf = -((vx * sinY + vz * cosY) >> 14);
        cx = (vx * cosY - vz * sinY) >> 14;
        cz = (zf * cosP - vy * sinP) >> 14;
        cy = (zf * sinP + vy * cosP) >> 14;
        if (cz < 64 || cz > farDist) continue;
        sx = 120 + cx * FOCAL / cz;
        sy = 80 - cy * FOCAL / cz;
        diam = (c->red ? 70 : 64) * FOCAL / cz;
        if (sx < -16 || sx > 256 || sy < -16 || sy > 176 || diam < 2) continue;
        for (k = 0; k < NUM_SIZES - 1 && kSizes[k + 1] <= diam; k++) {}
        if (k < NUM_ART) {
            s32 box = kSizes[k] <= 8 ? 8 : 16;
            sx -= box / 2;
            sy -= box / 2;
            sOam[n][0] = (u16) (sy & 0xFF);                                /* square, 4bpp */
            sOam[n][1] = (u16) ((sx & 0x1FF) | ((box >> 4) << 14));         /* 8 or 16 */
            sOam[n][2] = sTile[c->red][f][k];
        } else {
            sx -= 16; /* double-size box: 32x32 around the center */
            sy -= 16;
            sOam[n][0] = (u16) ((sy & 0xFF) | 0x0100 | 0x0200);            /* affine, double size */
            sOam[n][1] = (u16) ((sx & 0x1FF) | ((MTX_FIRST + k - NUM_ART) << 9) | (1 << 14));
            sOam[n][2] = sTile[c->red][f][NUM_ART - 1];
        }
        n++;
    }
    for (; n < OAM_COUNT; n++) sOam[n][0] = 0x0200;
}

/* During VBlank. */
void coins_commit(void) {
    s32 i;
    for (i = 0; i < OAM_COUNT; i++) {
        OAM[(OAM_FIRST + i) * 4 + 0] = sOam[i][0];
        OAM[(OAM_FIRST + i) * 4 + 1] = sOam[i][1];
        OAM[(OAM_FIRST + i) * 4 + 2] = sOam[i][2];
    }
    for (i = NUM_ART; i < NUM_SIZES; i++) {
        u16 p = (u16) (16 * 256 / kSizes[i]); /* 8.8: 16 px of art shown at kSizes[i] px */
        s32 m = MTX_FIRST + i - NUM_ART;
        OAM[m * 16 + 3] = p;
        OAM[m * 16 + 7] = 0;
        OAM[m * 16 + 11] = 0;
        OAM[m * 16 + 15] = p;
    }
}

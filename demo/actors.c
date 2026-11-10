/*
 * Enemies on screen: every active object in the decomp's object pool whose
 * model the demo knows (Goomba, Bob-omb, explosion) is drawn as a billboard
 * sprite, sized by distance and by the object's own scale. The game's
 * models are textured 3D meshes; these are drawn stand-ins, 16x16 designs
 * pre-scaled like the coins (demo/coins.c), and not depth tested.
 */
#include <PR/ultratypes.h>
#include "sm64.h"
#include "types.h"
#include "model_ids.h"
#include "game/object_list_processor.h"
#include "gba.h"
#include "render.h"
#include "actors.h"

extern const s16 gSinQ14[4096];
extern u8 gModelTags[256]; /* src/obj/obj_stubs.inc.c: a model's stand-in graph node */

#define OAM_FIRST 48        /* after the HUD, before the coins (60..107): drawn over them */
#define OAM_COUNT 12
#define TILE_FIRST 768      /* after the coins' tiles (600..767) */
#define NUM_SIZES 12
#define NUM_ART 9           /* sizes drawn as is; larger ones are the 16 px art scaled */
#define MTX_FIRST 23        /* after the coins' 20..22 */
#define FOCAL 200
#define NUM_KINDS 3

/* palette bank 0, colors 11..15 (the HUD has 1..2, the coins 3..10) */
static const char kDesigns[2][16][17] = {
    { /* Goomba */
        "......BBBB......",
        "....BBBBBBBB....",
        "...BBBBBBBBBB...",
        "..BBKBBBBBBKBB..",
        ".BBBWKBBBBKWBBB.",
        ".BBBWKBBBBKWBBB.",
        "BBBBWWBBBBWWBBBB",
        "BBBBBBBBBBBBBBBB",
        "BBBBBBBBBBBBBBBB",
        ".BBBTTTTTTTTBBB.",
        "....TTTTTTTT....",
        "....TTTTTTTT....",
        "...KKKTTTTKKK...",
        "..KKKKK..KKKKK..",
        "..KKKKK..KKKKK..",
        "................",
    },
    { /* Bob-omb */
        ".......TT.......",
        "......TT........",
        ".....KKKKKK.....",
        "...KKKKKKKKKK...",
        "..KKKKKKKKKKKK..",
        ".KKKKWKKKKWKKKK.",
        ".KKKKWKKKKWKKKK.",
        "KKKKKWKKKKWKKKKK",
        "KKKKKKKKKKKKKKKK",
        "KKKKKKKKKKKKKKKK",
        ".KKKKKKKKKKKKKK.",
        ".KKKKKKKKKKKKKK.",
        "..KKKKKKKKKKKK..",
        "....KKKKKKKK....",
        "..OOOO....OOOO..",
        "..OOOO....OOOO..",
    },
};

static const u8 kSizes[NUM_SIZES] = { 3, 4, 5, 6, 8, 10, 12, 14, 16, 20, 24, 30 };
static const u8 kModels[NUM_KINDS] = { MODEL_GOOMBA, MODEL_BLACK_BOBOMB, MODEL_EXPLOSION };
static const s16 kWorldSize[NUM_KINDS] = { 110, 110, 160 }; /* sprite height at scale 1 */
static const s16 kCenterY[NUM_KINDS] = { 55, 55, 0 };       /* above the object's origin */
static u16 sTile[NUM_KINDS][NUM_ART];
static u16 sOam[OAM_COUNT][3];

static s32 qsin(s32 a) { return gSinQ14[(a & 0xFFFF) >> 4]; }
static s32 qcos(s32 a) { return gSinQ14[((a + 0x4000) & 0xFFFF) >> 4]; }

static s32 design_color(char c) {
    switch (c) {
        case 'B': return 11;
        case 'T': return 12;
        case 'K': return 13;
        case 'W': return 14;
        case 'O': return 15;
        default: return 0;
    }
}

/* Color of pixel (x, y) of a kind's sprite at d x d pixels. */
static s32 art_pixel(s32 kind, s32 d, s32 x, s32 y) {
    s32 u = (2 * x + 1) * 16 / (2 * d), v = (2 * y + 1) * 16 / (2 * d);
    if (kind < 2) return design_color(kDesigns[kind][v][u]);
    {
        /* explosion: a burst, white hot in the middle */
        s32 dx = 2 * u - 15, dy = 2 * v - 15, dd = dx * dx + dy * dy;
        s32 spike = ((u * 7 + v * 13) & 3) == 0 ? 30 : 0;
        if (dd < 36) return 14;
        if (dd < 160 + spike) return 15;
        if (dd < 225 && spike) return 12;
        return 0;
    }
}

void actors_init(void) {
    volatile u16 *tiles = OBJ_VRAM_BITMAP;
    s32 kind, k, x, y, i, tile = TILE_FIRST;
    for (kind = 0; kind < NUM_KINDS; kind++) {
        for (k = 0; k < NUM_ART; k++) {
            s32 d = kSizes[k], box = d <= 8 ? 8 : 16, w = box / 8, off = (box - d) / 2;
            sTile[kind][k] = (u16) tile;
            for (y = 0; y < box; y++) {
                for (x = 0; x < box; x += 4) {
                    u16 v = 0;
                    for (i = 0; i < 4; i++) {
                        s32 px = x + i - off, py = y - off, c = 0;
                        if (px >= 0 && px < d && py >= 0 && py < d) c = art_pixel(kind, d, px, py);
                        v |= (u16) (c << (i * 4));
                    }
                    tiles[(tile - 512 + (y >> 3) * w + (x >> 3)) * 16 + (y & 7) * 2 + ((x & 4) >> 2)] = v;
                }
            }
            tile += w * w;
        }
    }
    PAL_OBJ[11] = RGB15(150, 82, 40);   /* brown */
    PAL_OBJ[12] = RGB15(232, 196, 140); /* tan */
    PAL_OBJ[13] = RGB15(36, 36, 44);    /* black */
    PAL_OBJ[14] = RGB15(248, 248, 248); /* white */
    PAL_OBJ[15] = RGB15(248, 140, 24);  /* orange */
    actors_hide();
}

void actors_hide(void) {
    s32 i;
    for (i = 0; i < OAM_COUNT; i++) sOam[i][0] = 0x0200;
}

void actors_draw(const struct RCamera *cam, s32 farDist) {
    s32 sinY = qsin(cam->yaw), cosY = qcos(cam->yaw), sinP = qsin(cam->pitch), cosP = qcos(cam->pitch);
    s32 i, n = 0;
    for (i = 0; i < OBJECT_POOL_CAPACITY && n < OAM_COUNT; i++) {
        struct Object *o = &gObjectPool[i];
        s32 kind, model, vx, vy, vz, zf, cx, cy, cz, diam, sx, sy, k, size;
        if (o->activeFlags == ACTIVE_FLAG_DEACTIVATED || o == gMarioObject) continue;
        if (!(o->header.gfx.node.flags & GRAPH_RENDER_ACTIVE)
            || (o->header.gfx.node.flags & GRAPH_RENDER_INVISIBLE) || o->header.gfx.sharedChild == NULL) {
            continue;
        }
        model = (s32) ((u8 *) o->header.gfx.sharedChild - gModelTags);
        for (kind = 0; kind < NUM_KINDS && kModels[kind] != model; kind++) {}
        if (kind == NUM_KINDS) continue;
        size = (s32) (kWorldSize[kind] * o->header.gfx.scale[1]);
        vx = (s32) o->header.gfx.pos[0] - cam->x;
        vy = (s32) o->header.gfx.pos[1] + kCenterY[kind] - cam->y;
        vz = (s32) o->header.gfx.pos[2] - cam->z;
        if (vx > farDist || vx < -farDist || vz > farDist || vz < -farDist) continue;
        zf = -((vx * sinY + vz * cosY) >> 14);
        cx = (vx * cosY - vz * sinY) >> 14;
        cz = (zf * cosP - vy * sinP) >> 14;
        cy = (zf * sinP + vy * cosP) >> 14;
        if (cz < 64 || cz > farDist) continue;
        sx = 120 + cx * FOCAL / cz;
        sy = 80 - cy * FOCAL / cz;
        diam = size * FOCAL / cz;
        if (sx < -16 || sx > 256 || sy < -16 || sy > 176 || diam < 2) continue;
        for (k = 0; k < NUM_SIZES - 1 && kSizes[k + 1] <= diam; k++) {}
        if (k < NUM_ART) {
            s32 box = kSizes[k] <= 8 ? 8 : 16;
            sx -= box / 2;
            sy -= box / 2;
            sOam[n][0] = (u16) (sy & 0xFF);
            sOam[n][1] = (u16) ((sx & 0x1FF) | ((box >> 4) << 14));
            sOam[n][2] = sTile[kind][k];
        } else {
            sx -= 16;
            sy -= 16;
            sOam[n][0] = (u16) ((sy & 0xFF) | 0x0100 | 0x0200);
            sOam[n][1] = (u16) ((sx & 0x1FF) | ((MTX_FIRST + k - NUM_ART) << 9) | (1 << 14));
            sOam[n][2] = sTile[kind][NUM_ART - 1];
        }
        n++;
    }
    for (; n < OAM_COUNT; n++) sOam[n][0] = 0x0200;
}

void actors_commit(void) {
    s32 i;
    for (i = 0; i < OAM_COUNT; i++) {
        OAM[(OAM_FIRST + i) * 4 + 0] = sOam[i][0];
        OAM[(OAM_FIRST + i) * 4 + 1] = sOam[i][1];
        OAM[(OAM_FIRST + i) * 4 + 2] = sOam[i][2];
    }
    for (i = NUM_ART; i < NUM_SIZES; i++) {
        u16 p = (u16) (16 * 256 / kSizes[i]);
        s32 m = MTX_FIRST + i - NUM_ART;
        OAM[m * 16 + 3] = p;
        OAM[m * 16 + 7] = 0;
        OAM[m * 16 + 11] = 0;
        OAM[m * 16 + 15] = p;
    }
}

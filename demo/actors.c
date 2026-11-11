/*
 * Enemies on screen: every active object in the decomp's object pool whose
 * model the demo knows (Goomba, Bob-omb, explosion) is drawn as a billboard
 * sprite, sized by distance and by the object's own scale. The game's
 * models are textured 3D meshes. With an import, their real models and
 * animations are baked offline into 16/32px sprites, selected by facing,
 * animation frame and eye state. Otherwise these are drawn stand-ins.
 * Sprites are not depth tested against the terrain.
 *
 * Scenery: the level's trees (its special objects, spawned by the game when
 * the terrain loads) are drawn the same way, only drawn: no behavior runs,
 * so they can't be climbed. Those nearer the camera than Mario go in OAM
 * slots before the mannequin's (drawn over him), the others after.
 */
#include <PR/ultratypes.h>
#include "sm64.h"
#include "types.h"
#include "model_ids.h"
#include "behavior_data.h"
#include "game/level_update.h"
#include "game/object_list_processor.h"
#include "gba.h"
#include "render.h"
#include "actors.h"

extern const s16 gSinQ14[4096];
extern const u32 gRecipZ[16384]; /* 2^24 / z (render tables): no divisions per sprite */
#define PERSP(v, z) ((s32) (((s64) (v) * FOCAL * gRecipZ[(z) > 16383 ? 16383 : (z)]) >> 24))
extern u8 gModelTags[256]; /* src/obj/obj_stubs.inc.c: a model's stand-in graph node */

#define OAM_FIRST 36        /* after the HUD, before the coins (48..87): drawn over them */
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

#ifdef DEMO_ENEMY_ART
#include "enemy_art.h"
extern const struct Animation *const bobomb_seg8_anims_0802396C[];
#define ENEMY_BANK 15
#define EXPLOSION_TILE 592
/* Imported Mario doesn't use the mannequin ball at 576..591. Two nearby
 * enemies get 32px art in 768..799; twelve independent 16px slots occupy
 * 800..831 and 576..591. The explosion has 592..595. Coins start at 600,
 * trees at 832. Upload at most 2*512 + 10*128 bytes during VBlank. */
static const u16 *sEnemyPending[OAM_COUNT], *sEnemyLoaded[OAM_COUNT + 2];
static u8 sEnemyCache[OAM_COUNT];
static u16 sEnemyPA[OAM_COUNT], sEnemyPD[OAM_COUNT];

static void enemy_sprite(struct Object *o, s32 kind, s32 slot, s32 sx, s32 sy,
                         s32 depth, s32 diam, u16 cameraYaw, s32 *nearCount) {
    s32 box = 16, tile = EXPLOSION_TILE, bank = 0;
    s32 width = diam, height = diam;
    sEnemyPending[slot] = NULL;
    if (kind < 2) {
        struct AnimInfo *ai = &o->header.gfx.animInfo;
        /* Object animation helpers change curAnim, not Mario's animID. */
        s32 animation = kind == 0 ? 0 : 1 + (ai->curAnim == bobomb_seg8_anims_0802396C[1]);
        s32 frame = ai->animFrame, view, index, cache;
        if (frame < 0) frame = 0;
        if (frame >= gImpEnemyLength[animation]) frame = gImpEnemyLength[animation] - 1;
        view = ((u16) (cameraYaw - o->header.gfx.angle[1] + 0x1000)) >> 13;
        index = (((o->oAnimState & 1) * 8 + view) * 8) + gImpEnemyPhase[animation][frame];
        width = PERSP((s32) (gImpEnemySize[kind] * o->header.gfx.scale[0]), depth);
        bank = ENEMY_BANK;
        if ((width >= 20 || height >= 20) && *nearCount < 2) {
            box = 32;
            cache = OAM_COUNT + *nearCount;
            tile = 768 + (*nearCount)++ * 16;
            sEnemyPending[slot] = gImpEnemyLarge[animation][index];
        } else {
            cache = slot;
            tile = slot < 8 ? 800 + slot * 4 : 576 + (slot - 8) * 4;
            sEnemyPending[slot] = gImpEnemySmall[animation][index];
        }
        sEnemyCache[slot] = (u8) cache;
    }
    if (width < 1) width = 1;
    if (height < 1) height = 1;
    if (width > box * 2) width = box * 2;
    if (height > box * 2) height = box * 2;
    /* Affine reciprocals from the renderer's ROM table: no division per
     * enemy. Matrices 0..11 are free while Mario uses his real 3D model. */
    sEnemyPA[slot] = (u16) ((box * gRecipZ[width]) >> 16);
    sEnemyPD[slot] = (u16) ((box * gRecipZ[height]) >> 16);
    sOam[slot][0] = (u16) (((sy - box) & 0xFF) | 0x0300);
    sOam[slot][1] = (u16) (((sx - box) & 0x1FF) | (slot << 9) | ((box == 32 ? 2 : 1) << 14));
    sOam[slot][2] = (u16) (tile | (bank << 12));
}
#endif

/* ---- trees ---- */
#define MAX_TREES 32
#define TREE_TILE 832       /* after the enemies' (768..831) */
#define TREE_NEAR_FIRST 88  /* 88..92: in front of Mario (before the mannequin's 93..112) */
#define TREE_NEAR_COUNT 4
#define TREE_FAR_FIRST 113  /* 113..127: behind him */
#define TREE_FAR_COUNT 15
#define TREE_BANK 13        /* palette bank (the mannequin's are 1..12) */
#ifdef DEMO_SPRITE_ART
#define TREE_HEIGHT 809     /* the game's tree quad: y -9..800 */
#else
#define TREE_HEIGHT 600     /* world units (its pole hitbox is 500 tall) */
#endif
#define NUM_TREE_SIZES 8
#define STAR_TILE 1018 /* four free tiles after the meter's 1002..1017 */
#define STAR_OAM 92
#define STAR_BANK 0 /* reuse the coin bank's yellow shades (colors 3 and 6) */
#define STAR_SIZE 16
static const u8 kTreeSizes[NUM_TREE_SIZES] = { 6, 8, 12, 16, 24, 32, 48, 64 };
static u16 sTreeTile[NUM_TREE_SIZES];
static s16 sTrees[MAX_TREES][3];
static s32 sNumTrees;
static u16 sTreeOam[TREE_NEAR_COUNT + TREE_FAR_COUNT][3];
static s32 sStarPos[3], sStarVisible;
static u16 sStarOam[3];

static const char *const kStarArt[16] = {
    ".......YY.......", ".......YY.......", "......YYYY......", "......YYYY......",
    "YYYYYYYYYYYYYYYY", ".YYYYYYYYYYYYYY.", "..YYYYYYYYYYYY..", "...YYYYYYYYYY...",
    "....YYYYYYYY....", "...YYYYYYYYYY...", "..YYYYYYYYYYYY..", ".YYYYYYYYYYYYYY.",
    "YYYYYYYYYYYYYYYY", "....YY....YY....", "...YYY....YYY...", "................"
};

static void star_init(void) {
    volatile u16 *tiles = OBJ_VRAM_BITMAP;
    s32 x, y, i;
    for (y = 0; y < STAR_SIZE; y++) for (x = 0; x < STAR_SIZE; x += 4) {
        u16 packed = 0;
        for (i = 0; i < 4; i++) {
            s32 px = x + i, color = kStarArt[y][px] == 'Y' ? (y < 4 ? 6 : 3) : 0;
            packed |= (u16) (color << (i * 4));
        }
        tiles[(STAR_TILE - 512 + (y >> 3) * 2 + (x >> 3)) * 16 + (y & 7) * 2 + ((x & 4) >> 2)] = packed;
    }
    sStarVisible = 0;
    sStarOam[0] = 0x0200;
}

#ifdef DEMO_SPRITE_ART
/* the game's bubbly tree, from your ROM (build/import/sprite_art.c) */
extern const u16 gImpTreePal[15];
extern const u8 gImpTreeArt[64 * 64];

static s32 tree_pixel(s32 u, s32 v) {
    return gImpTreeArt[v * 64 + u];
}
#else
/* 64x64 stand-in: a round crown, lit from the upper left, on a trunk.
 * Colors: 1..3 greens (dark to light), 4..5 trunk. */
static s32 tree_pixel(s32 u, s32 v) {
    s32 dx = u - 32, dy = v - 25, dd = dx * dx * 100 / (27 * 27) + dy * dy * 100 / (24 * 24);
    if (dd <= 100) {
        s32 lit = -dx - dy; /* toward the upper left */
        if (dd > 82) return 1;
        return lit > 14 ? 3 : lit > -10 ? 2 : 1;
    }
    if (u >= 28 && u < 37 && v >= 44 && v < 63) return u < 31 ? 4 : 5;
    return 0;
}
#endif

static void trees_init(void) {
    volatile u16 *tiles = OBJ_VRAM_BITMAP;
    s32 k, x, y, i, tile = TREE_TILE;
    for (k = 0; k < NUM_TREE_SIZES; k++) {
        s32 d = kTreeSizes[k], box = d <= 8 ? 8 : d <= 16 ? 16 : d <= 32 ? 32 : 64;
        s32 w = box / 8, off = (box - d) / 2;
        sTreeTile[k] = (u16) tile;
        for (y = 0; y < box; y++) {
            for (x = 0; x < box; x += 4) {
                u16 v = 0;
                for (i = 0; i < 4; i++) {
                    s32 px = x + i - off, py = y - off, c = 0;
                    if (px >= 0 && px < d && py >= 0 && py < d) {
                        c = tree_pixel((2 * px + 1) * 64 / (2 * d), (2 * py + 1) * 64 / (2 * d));
                    }
                    v |= (u16) (c << (i * 4));
                }
                tiles[(tile - 512 + (y >> 3) * w + (x >> 3)) * 16 + (y & 7) * 2 + ((x & 4) >> 2)] = v;
            }
        }
        tile += w * w;
    }
#ifdef DEMO_SPRITE_ART
    for (i = 0; i < 15; i++) PAL_OBJ[TREE_BANK * 16 + 1 + i] = gImpTreePal[i];
#else
    PAL_OBJ[TREE_BANK * 16 + 1] = RGB15(24, 96, 32);
    PAL_OBJ[TREE_BANK * 16 + 2] = RGB15(40, 150, 48);
    PAL_OBJ[TREE_BANK * 16 + 3] = RGB15(110, 200, 80);
    PAL_OBJ[TREE_BANK * 16 + 4] = RGB15(130, 90, 50);
    PAL_OBJ[TREE_BANK * 16 + 5] = RGB15(86, 56, 32);
#endif
}

/* After a level loads: the trees the terrain spawned (they don't run). */
void actors_load_scenery(void) {
    s32 i;
    sNumTrees = 0;
    for (i = 0; i < OBJECT_POOL_CAPACITY && sNumTrees < MAX_TREES; i++) {
        struct Object *o = &gObjectPool[i];
        if (o->activeFlags != ACTIVE_FLAG_DEACTIVATED && o->behavior == segmented_to_virtual(bhvTree)) {
            sTrees[sNumTrees][0] = (s16) o->oPosX;
            sTrees[sNumTrees][1] = (s16) o->oPosY;
            sTrees[sNumTrees][2] = (s16) o->oPosZ;
            sNumTrees++;
        }
    }
}

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
#ifdef DEMO_ENEMY_ART
    for (i = 0; i < 15; i++) PAL_OBJ[ENEMY_BANK * 16 + 1 + i] = gImpEnemyPal[i];
    for (i = 0; i < OAM_COUNT + 2; i++) sEnemyLoaded[i] = NULL;
    for (y = 0; y < 16; y++) {
        for (x = 0; x < 16; x += 4) {
            u16 v = 0;
            for (i = 0; i < 4; i++) v |= (u16) (art_pixel(2, 16, x + i, y) << (4 * i));
            tiles[(EXPLOSION_TILE - 512 + (y >> 3) * 2 + (x >> 3)) * 16 + (y & 7) * 2 + ((x & 4) >> 2)] = v;
        }
    }
#else
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
#endif
    PAL_OBJ[11] = RGB15(150, 82, 40);   /* brown */
    PAL_OBJ[12] = RGB15(232, 196, 140); /* tan */
    PAL_OBJ[13] = RGB15(36, 36, 44);    /* black */
    PAL_OBJ[14] = RGB15(248, 248, 248); /* white */
    PAL_OBJ[15] = RGB15(248, 140, 24);  /* orange */
    trees_init();
    star_init();
    actors_hide();
}

void actors_star_place(s32 x, s32 y, s32 z, s32 visible) {
    sStarPos[0] = x; sStarPos[1] = y; sStarPos[2] = z;
    sStarVisible = visible;
    if (!visible) sStarOam[0] = 0x0200;
}

void actors_hide(void) {
    s32 i;
    for (i = 0; i < OAM_COUNT; i++) sOam[i][0] = 0x0200;
#ifdef DEMO_ENEMY_ART
    for (i = 0; i < OAM_COUNT; i++) sEnemyPending[i] = NULL;
#endif
    for (i = 0; i < TREE_NEAR_COUNT + TREE_FAR_COUNT; i++) sTreeOam[i][0] = 0x0200;
    sStarOam[0] = 0x0200;
}

/* camera space depth and screen position of a world point; 0 if not drawable */
static s32 project(const struct RCamera *cam, s32 farDist, s32 x, s32 y, s32 z, s32 *sx, s32 *sy, s32 *cz) {
    s32 sinY = qsin(cam->yaw), cosY = qcos(cam->yaw), sinP = qsin(cam->pitch), cosP = qcos(cam->pitch);
    s32 vx = x - cam->x, vy = y - cam->y, vz = z - cam->z, zf, cx, cy;
    if (vx > farDist || vx < -farDist || vz > farDist || vz < -farDist) return 0;
    zf = -((vx * sinY + vz * cosY) >> 14);
    cx = (vx * cosY - vz * sinY) >> 14;
    *cz = (zf * cosP - vy * sinP) >> 14;
    cy = (zf * sinP + vy * cosP) >> 14;
    if (*cz < 64 || *cz > farDist) return 0;
    *sx = 120 + PERSP(cx, *cz);
    *sy = 80 - PERSP(cy, *cz);
    return 1;
}

static void trees_draw(const struct RCamera *cam, s32 farDist) {
    s32 i, k, nNear = 0, nFar = 0, marioZ = 0x7FFFFFFF, mx, my;
    if (gMarioState != NULL) {
        project(cam, 0x7FFF, (s32) gMarioState->pos[0], (s32) gMarioState->pos[1] + 80,
                (s32) gMarioState->pos[2], &mx, &my, &marioZ);
    }
    for (i = 0; i < sNumTrees; i++) {
        s32 sx, sy, cz, diam, box, slot;
        if (!project(cam, farDist, sTrees[i][0], sTrees[i][1] + TREE_HEIGHT / 2, sTrees[i][2], &sx, &sy, &cz)) {
            continue;
        }
        diam = PERSP(TREE_HEIGHT, cz);
        if (diam < 4 || sx < -64 || sx > 304 || sy < -64 || sy > 224) continue;
        for (k = 0; k < NUM_TREE_SIZES - 1 && kTreeSizes[k + 1] <= diam; k++) {}
        if (cz < marioZ) {
            if (nNear >= TREE_NEAR_COUNT) continue;
            slot = nNear++;
        } else {
            if (nFar >= TREE_FAR_COUNT) continue;
            slot = TREE_NEAR_COUNT + nFar++;
        }
        box = kTreeSizes[k] <= 8 ? 8 : kTreeSizes[k] <= 16 ? 16 : kTreeSizes[k] <= 32 ? 32 : 64;
        sx -= box / 2;
        sy -= box / 2;
        sTreeOam[slot][0] = (u16) (sy & 0xFF);
        sTreeOam[slot][1] = (u16) ((sx & 0x1FF) | ((box == 8 ? 0 : box == 16 ? 1 : box == 32 ? 2 : 3) << 14));
        sTreeOam[slot][2] = (u16) (sTreeTile[k] | (TREE_BANK << 12));
    }
    for (; nNear < TREE_NEAR_COUNT; nNear++) sTreeOam[nNear][0] = 0x0200;
    for (; nFar < TREE_FAR_COUNT; nFar++) sTreeOam[TREE_NEAR_COUNT + nFar][0] = 0x0200;
}

static void star_draw(const struct RCamera *cam, s32 farDist) {
    s32 sx, sy, cz;
    if (!sStarVisible || !project(cam, farDist, sStarPos[0], sStarPos[1], sStarPos[2], &sx, &sy, &cz)
        || sx < -16 || sx > 256 || sy < -16 || sy > 176) {
        sStarOam[0] = 0x0200;
        return;
    }
    sx -= STAR_SIZE / 2; sy -= STAR_SIZE / 2;
    sStarOam[0] = (u16) (sy & 0xFF);
    sStarOam[1] = (u16) ((sx & 0x1FF) | (1 << 14));
    sStarOam[2] = (u16) (STAR_TILE | (STAR_BANK << 12));
}

void actors_draw(const struct RCamera *cam, s32 farDist) {
    s32 sinY = qsin(cam->yaw), cosY = qcos(cam->yaw), sinP = qsin(cam->pitch), cosP = qcos(cam->pitch);
    s32 i, n = 0;
#ifdef DEMO_ENEMY_ART
    s32 nearCount = 0;
#endif
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
#ifdef DEMO_ENEMY_ART
        if (kind < 2) {
            size = (s32) (gImpEnemySize[kind] * o->header.gfx.scale[1]);
            vy = (s32) (o->header.gfx.pos[1] + gImpEnemyCenter[kind] * o->header.gfx.scale[1]) - cam->y;
        }
#endif
        vz = (s32) o->header.gfx.pos[2] - cam->z;
        if (vx > farDist || vx < -farDist || vz > farDist || vz < -farDist) continue;
        zf = -((vx * sinY + vz * cosY) >> 14);
        cx = (vx * cosY - vz * sinY) >> 14;
        cz = (zf * cosP - vy * sinP) >> 14;
        cy = (zf * sinP + vy * cosP) >> 14;
        if (cz < 64 || cz > farDist) continue;
        sx = 120 + PERSP(cx, cz);
        sy = 80 - PERSP(cy, cz);
        diam = PERSP(size, cz);
#ifdef DEMO_ENEMY_ART
        if (sx < -32 || sx > 272 || sy < -32 || sy > 192 || diam < 2) continue;
        enemy_sprite(o, kind, n, sx, sy, cz, diam, cam->yaw, &nearCount);
#else
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
#endif
        n++;
    }
    for (; n < OAM_COUNT; n++) {
        sOam[n][0] = 0x0200;
#ifdef DEMO_ENEMY_ART
        sEnemyPending[n] = NULL;
#endif
    }
    trees_draw(cam, farDist);
    star_draw(cam, farDist);
}

void actors_commit(void) {
    s32 i;
    for (i = 0; i < OAM_COUNT; i++) {
#ifdef DEMO_ENEMY_ART
        const u16 *source = sEnemyPending[i];
        if (source != NULL && sEnemyLoaded[sEnemyCache[i]] != source) {
            volatile u16 *dest = OBJ_VRAM_BITMAP + ((sOam[i][2] & 0x3FF) - 512) * 16;
            s32 k, words = sEnemyCache[i] >= OAM_COUNT ? 256 : 64;
            for (k = 0; k < words; k++) dest[k] = source[k];
            sEnemyLoaded[sEnemyCache[i]] = source;
        }
        OAM[i * 16 + 3] = sEnemyPA[i];
        OAM[i * 16 + 7] = 0;
        OAM[i * 16 + 11] = 0;
        OAM[i * 16 + 15] = sEnemyPD[i];
#endif
        OAM[(OAM_FIRST + i) * 4 + 0] = sOam[i][0];
        OAM[(OAM_FIRST + i) * 4 + 1] = sOam[i][1];
        OAM[(OAM_FIRST + i) * 4 + 2] = sOam[i][2];
    }
    for (i = 0; i < TREE_NEAR_COUNT + TREE_FAR_COUNT; i++) {
        s32 at = i < TREE_NEAR_COUNT ? TREE_NEAR_FIRST + i : TREE_FAR_FIRST + i - TREE_NEAR_COUNT;
        OAM[at * 4 + 0] = sTreeOam[i][0];
        OAM[at * 4 + 1] = sTreeOam[i][1];
        OAM[at * 4 + 2] = sTreeOam[i][2];
    }
    OAM[STAR_OAM * 4 + 0] = sStarOam[0];
    OAM[STAR_OAM * 4 + 1] = sStarOam[1];
    OAM[STAR_OAM * 4 + 2] = sStarOam[2];
#ifndef DEMO_ENEMY_ART
    for (i = NUM_ART; i < NUM_SIZES; i++) {
        u16 p = (u16) (16 * 256 / kSizes[i]);
        s32 m = MTX_FIRST + i - NUM_ART;
        OAM[m * 16 + 3] = p;
        OAM[m * 16 + 7] = 0;
        OAM[m * 16 + 11] = 0;
        OAM[m * 16 + 15] = p;
    }
#endif
}

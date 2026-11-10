/*
 * Sound effects on the GBA's four Game Boy sound channels (two square waves,
 * a programmable wave channel, noise): no samples, no mixing, no CPU cost
 * beyond a few register writes.
 *
 * The game's own sound calls drive it: Mario's code and the objects call
 * play_sound() / cur_obj_play_sound_*() with SM64's sound IDs exactly as on
 * the N64 (src/stubs.c and src/obj/obj_stubs.inc.c forward them here in the
 * demo build). Each ID we know is mapped to a short chiptune effect; the
 * sounds themselves are made up, not the game's samples. Object sounds fade
 * with distance from Mario and are cut beyond 2000 units.
 */
#include <PR/ultratypes.h>
#include "sm64.h"
#include "types.h"
#include "sounds.h"
#include "game/level_update.h"
#include "gba.h"
#include "sfx.h"

#define REG16(a) (*(volatile u16 *) (a))
#define SND1_SWEEP REG16(0x04000060)
#define SND1_ENV REG16(0x04000062)
#define SND1_FREQ REG16(0x04000064)
#define SND2_ENV REG16(0x04000068)
#define SND2_FREQ REG16(0x0400006C)
#define SND4_ENV REG16(0x04000078)
#define SND4_FREQ REG16(0x0400007C)
#define SNDCNT_L REG16(0x04000080)
#define SNDCNT_H REG16(0x04000082)
#define SNDCNT_X REG16(0x04000084)

/* square channel: frequency register for f Hz is 2048 - 131072 / f */
#define HZ(f) (2048 - 131072 / (f))
/* envelope: initial volume 0..15, step 0..7 (n/64 s per level, 0 = hold), decreasing */
#define ENV(vol, step, duty) (((vol) << 12) | ((step) << 8) | ((duty) << 6))
#define ENV_UP(vol, step, duty) (ENV(vol, step, duty) | 0x0800)

enum {
    FX_NONE, FX_JUMP, FX_LAND, FX_STEP, FX_BONK, FX_HURT, FX_STOMP, FX_ALERT,
    FX_FUSE, FX_EXPLOSION, FX_COIN, FX_RED_COIN, FX_THROW,
};

/* channel 2 note sequences, one note per game frame (30 Hz): Hz, 0 = end */
static const u16 kCoinNotes[] = { 988, 988, 1319, 1319, 1319, 1319, 1319, 0 };
static const u16 kRedCoinNotes[] = { 1047, 1319, 1568, 2093, 2093, 2093, 0 };
static const u16 kAlertNotes[] = { 784, 784, 1047, 1047, 0 };
static const u16 kStompNotes[] = { 1568, 1175, 784, 0 };

static const u16 *sSeq; /* channel 2 sequence playing */
static s32 sSeqVol;
static s32 sNoiseLock;  /* frames the noise channel stays with the explosion */
static s32 sFuseTimer;

static s32 known_effect(u32 bits) {
    u32 bank = bits >> 28, id = (bits >> 16) & 0xFF;
    switch (bank) {
        case SOUND_BANK_ACTION:
            if (id < 0x08) return FX_JUMP;               /* TERRAIN_JUMP + terrain */
            if (id < 0x10) return FX_LAND;               /* TERRAIN_LANDING + terrain */
            if (id < 0x18) return FX_STEP;               /* TERRAIN_STEP + terrain */
            if (id < 0x20) return FX_LAND;               /* BODY_HIT_GROUND + terrain */
            if (id == 0x44 || id == 0x45) return FX_BONK; /* HIT, BONK */
            if (id == 0x59) return FX_STOMP;             /* BOUNCE_OFF_OBJECT */
            if (id == 0x2D || id == 0x2E) return FX_THROW; /* throw / spin (punch, kick) */
            return FX_NONE;
        case SOUND_BANK_VOICE:
            if (id == 0x0A || id == 0x0B || id == 0x30) return FX_HURT; /* ATTACKED, OOOF, DOH */
            return FX_NONE;
        case SOUND_BANK_OBJ:
            if (id == 0x60 || id == 0x61 || id == 0x2C) return FX_STOMP; /* enemy deaths */
            if (id == 0x2F) return FX_ALERT;            /* GOOMBA_ALERT */
            return FX_NONE;
        case SOUND_BANK_AIR:
            if (id == 0x08) return FX_FUSE;             /* BOBOMB_LIT_FUSE */
            return FX_NONE;
        case SOUND_BANK_GENERAL2:
            if (id == 0x2E) return FX_EXPLOSION;        /* BOBOMB_EXPLOSION */
            return FX_NONE;
        default:
            return FX_NONE;
    }
}

static void seq_start(const u16 *notes, s32 vol) {
    sSeq = notes;
    sSeqVol = vol;
}

static void noise(s32 vol, s32 step, s32 shift, s32 ratio, s32 width7) {
    if (sNoiseLock > 0) return;
    SND4_ENV = (u16) ENV(vol, step, 0);
    SND4_FREQ = (u16) (0x8000 | (shift << 4) | (width7 ? 8 : 0) | ratio);
}

static void fire(s32 fx, s32 vol) {
    switch (fx) {
        case FX_JUMP: /* square rising */
            SND1_SWEEP = (u16) ((2 << 4) | 2);              /* time 2, increase, shift 2 */
            SND1_ENV = (u16) ENV(vol, 2, 2);
            SND1_FREQ = (u16) (0x8000 | HZ(392));
            break;
        case FX_HURT: /* square falling, harsh duty */
            SND1_SWEEP = (u16) ((3 << 4) | 0x08 | 2);       /* time 3, decrease, shift 2 */
            SND1_ENV = (u16) ENV(vol, 3, 1);
            SND1_FREQ = (u16) (0x8000 | HZ(880));
            break;
        case FX_THROW:
            SND1_SWEEP = (u16) ((1 << 4) | 0x08 | 3);
            SND1_ENV = (u16) ENV(vol * 2 / 3, 1, 2);
            SND1_FREQ = (u16) (0x8000 | HZ(659));
            break;
        case FX_LAND:
            noise(vol * 2 / 3, 1, 7, 4, 0);
            break;
        case FX_STEP:
            noise(vol / 4, 1, 3, 2, 0);
            break;
        case FX_BONK:
            noise(vol, 1, 6, 5, 0);
            break;
        case FX_STOMP:
            seq_start(kStompNotes, vol);
            noise(vol / 2, 1, 4, 3, 0);
            break;
        case FX_ALERT:
            seq_start(kAlertNotes, vol * 2 / 3);
            break;
        case FX_FUSE: /* called every frame while lit: a soft hiss every 4 frames */
            if (sFuseTimer > 0) return;
            sFuseTimer = 4;
            noise(vol / 4 + 1, 1, 1, 1, 1);
            break;
        case FX_EXPLOSION:
            sNoiseLock = 0;
            noise(vol, 5, 6, 7, 0);
            sNoiseLock = 45;
            break;
        case FX_COIN:
            seq_start(kCoinNotes, vol);
            break;
        case FX_RED_COIN:
            seq_start(kRedCoinNotes, vol);
            break;
        default:
            break;
    }
}

void sfx_init(void) {
    SNDCNT_X = 0x0080;  /* sound on */
    SNDCNT_L = 0xFF77;  /* PSG channels 1-4 on both sides, full master volume */
    SNDCNT_H = 0x0002;  /* PSG at 100% */
    SND1_SWEEP = 0x0008;
    sSeq = NULL;
    sNoiseLock = sFuseTimer = 0;
}

/* A sound the game asked for. src: the object making it (NULL: Mario). */
void sfx_play(u32 bits, const struct Object *src) {
    s32 fx = known_effect(bits), vol = 12;
    if (fx == FX_NONE) return;
    if (src != NULL && src != gMarioObject && gMarioState != NULL) {
        f32 dx = src->oPosX - gMarioState->pos[0], dy = src->oPosY - gMarioState->pos[1];
        f32 dz = src->oPosZ - gMarioState->pos[2];
        f32 d2 = dx * dx + dy * dy + dz * dz;
        if (d2 > 2000.0f * 2000.0f) return;
        if (d2 > 1000.0f * 1000.0f) vol = 7;
        if (d2 > 1500.0f * 1500.0f) vol = 4;
    }
    fire(fx, vol);
}

void sfx_coin(s32 red) {
    fire(red ? FX_RED_COIN : FX_COIN, 12);
}

/* Once per game frame: step the note sequence and the timers. */
void sfx_frame(void) {
    if (sNoiseLock > 0) sNoiseLock--;
    if (sFuseTimer > 0) sFuseTimer--;
    if (sSeq != NULL) {
        if (*sSeq == 0) {
            SND2_ENV = (u16) ENV(sSeqVol, 1, 2); /* let the last note ring out */
            sSeq = NULL;
        } else {
            SND2_ENV = (u16) ENV(sSeqVol, 0, 2);
            SND2_FREQ = (u16) (0x8000 | HZ(*sSeq));
            sSeq++;
        }
    }
}

void sfx_silence(void) {
    sSeq = NULL;
    sNoiseLock = 0;
    SND1_ENV = SND2_ENV = SND4_ENV = 0;
    SND1_FREQ = SND2_FREQ = 0x8000;
    SND4_FREQ = 0x8000;
}

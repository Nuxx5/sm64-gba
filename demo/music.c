/*
 * Background music, from your ROM only (make import ROM=...): there is no
 * music without it, since the game's music can't be part of this repository.
 *
 * Chiptune: tools/n64music.py arranges each level's SM64 sequence for the
 * GBA's 4 Game Boy voices (melody: square 2, harmony: square 1, bass: wave,
 * drums: noise) as event streams at 60 Hz (build/import/music_data.c). The
 * player steps them from the VBlank interrupt, so the tempo doesn't depend
 * on the game's frame rate. A sound effect takes over a voice for its length
 * (demo/sfx.c marks it busy); the music restores the voice's note after.
 */
#include <PR/ultratypes.h>
#include "gba.h"
#include "music.h"

#define REG16(a) (*(volatile u16 *) (a))
#define SND1_SWEEP REG16(0x04000060)
#define SND1_ENV REG16(0x04000062)
#define SND1_FREQ REG16(0x04000064)
#define SND2_ENV REG16(0x04000068)
#define SND2_FREQ REG16(0x0400006C)
#define SND3_SEL REG16(0x04000070)
#define SND3_VOL REG16(0x04000072)
#define SND3_FREQ REG16(0x04000074)
#define SND4_ENV REG16(0x04000078)
#define SND4_FREQ REG16(0x0400007C)
#define WAVE_RAM ((volatile u16 *) 0x04000090)

extern volatile u32 gVBlankCount;
u32 gSfxBusyUntil[4];          /* VBlank count until which a sound effect owns channel 1..4 */
void (*volatile gVBlankHook)(void); /* called by the VBlank interrupt (demo/irq.s) */

#ifdef DEMO_MUSIC
/* 2048 - 131072 / f (square) and 2048 - 65536 / f (32-sample wave) for the
 * game's note numbers (0 = A0) */
static const u16 kSquareFreq[128] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 44, 157, 263, 363, 457, 547, 631, 711, 786, 856, 923, 986, 1046, 1102, 1155, 1205, 1253, 1297, 1339, 1379, 1417, 1452, 1486, 1517, 1547, 1575, 1602, 1627, 1650, 1673, 1694, 1714, 1732, 1750, 1767, 1783, 1798, 1812, 1825, 1837, 1849, 1860, 1871, 1881, 1890, 1899, 1907, 1915, 1923, 1930, 1936, 1943, 1949, 1954, 1959, 1964, 1969, 1974, 1978, 1982, 1985, 1989, 1992, 1995, 1998, 2001, 2004, 2006, 2009, 2011, 2013, 2015, 2017, 2018, 2020, 2022, 2023, 2025, 2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033, 2034, 2035, 2036, 2036, 2037, 2038, 2038, 2039, 2039, 2040, 2040, 2041, 2041, 2041, 2042, 2042, 2042, 2043, 2043, 2043, 2044, 2044, 2044, 2044, 2045, 2045, 2045};
static const u16 kWaveFreq[128] = {0, 0, 0, 44, 157, 263, 363, 457, 547, 631, 711, 786, 856, 923, 986, 1046, 1102, 1155, 1205, 1253, 1297, 1339, 1379, 1417, 1452, 1486, 1517, 1547, 1575, 1602, 1627, 1650, 1673, 1694, 1714, 1732, 1750, 1767, 1783, 1798, 1812, 1825, 1837, 1849, 1860, 1871, 1881, 1890, 1899, 1907, 1915, 1923, 1930, 1936, 1943, 1949, 1954, 1959, 1964, 1969, 1974, 1978, 1982, 1985, 1989, 1992, 1995, 1998, 2001, 2004, 2006, 2009, 2011, 2013, 2015, 2017, 2018, 2020, 2022, 2023, 2025, 2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033, 2034, 2035, 2036, 2036, 2037, 2038, 2038, 2039, 2039, 2040, 2040, 2041, 2041, 2041, 2042, 2042, 2042, 2043, 2043, 2043, 2044, 2044, 2044, 2044, 2045, 2045, 2045, 2045, 2045, 2045, 2046, 2046, 2046, 2046, 2046, 2046, 2046, 2046, 2046};

struct MusicVoice {
    const u8 *ev;   /* events: delay (frames), note (0 = off, 0xFF = no change), level */
    u16 count, loop, tail;
};
struct MusicSong {
    struct MusicVoice voice[4]; /* melody, harmony, bass, drums */
};
extern const struct MusicSong gImpSongs[];
extern const s8 gImpLevelSong[4]; /* song of each level, -1: none */

enum { V_MELODY, V_HARMONY, V_BASS, V_DRUMS };
static const u8 kChannel[4] = { 1, 0, 2, 3 }; /* index into gSfxBusyUntil: GB channel 2, 1, 3, 4 */

struct VoiceState {
    const struct MusicVoice *v;
    u16 idx, wait;
    u8 note, level, pending; /* what should sound; pending: not written (an effect had the channel) */
};
static struct VoiceState sVoices[4];
static s32 sPlaying;

static void voice_write(s32 voice, s32 note, s32 level) {
    switch (voice) {
        case V_MELODY:
            if (note == 0) {
                SND2_ENV = 0x0008; /* volume 0: channel off */
                SND2_FREQ = 0x8000;
            } else {
                SND2_ENV = (u16) ((level << 12) | (2 << 6));
                SND2_FREQ = (u16) (0x8000 | kSquareFreq[note]);
            }
            break;
        case V_HARMONY:
            SND1_SWEEP = 0x0008;
            if (note == 0) {
                SND1_ENV = 0x0008;
                SND1_FREQ = 0x8000;
            } else {
                SND1_ENV = (u16) ((level << 12) | (1 << 6));
                SND1_FREQ = (u16) (0x8000 | kSquareFreq[note]);
            }
            break;
        case V_BASS:
            if (note == 0) {
                SND3_SEL = 0;
            } else {
                SND3_SEL = 0x0080;
                SND3_VOL = (u16) ((level > 10 ? 1 : level > 5 ? 2 : 3) << 13);
                SND3_FREQ = (u16) (0x8000 | kWaveFreq[note]);
            }
            break;
        case V_DRUMS:
            /* note = kind: 1 kick, 2 snare, 3 hi-hat; they decay on their own */
            if (note == 1) {
                SND4_ENV = (u16) ((level << 12) | (2 << 8));
                SND4_FREQ = (u16) (0x8000 | (6 << 4) | 5);
            } else if (note == 2) {
                SND4_ENV = (u16) ((level << 12) | (2 << 8));
                SND4_FREQ = (u16) (0x8000 | (3 << 4) | 2);
            } else if (note == 3) {
                SND4_ENV = (u16) (((level * 2 / 3) << 12) | (1 << 8));
                SND4_FREQ = (u16) (0x8000 | (1 << 4) | 8 | 1);
            }
            break;
    }
}

static void voice_apply(s32 voice, struct VoiceState *s, const u8 *e) {
    if (e[1] == 0xFF) return;
    s->note = e[1];
    s->level = e[2];
    if ((s32) (gSfxBusyUntil[kChannel[voice]] - gVBlankCount) > 0) {
        s->pending = 1; /* an effect is playing on this channel */
    } else {
        s->pending = 0;
        voice_write(voice, s->note, s->level);
    }
}

/* Once per VBlank, from the interrupt: keep it short. */
static void music_vblank(void) {
    s32 i;
    if (!sPlaying) return;
    for (i = 0; i < 4; i++) {
        struct VoiceState *s = &sVoices[i];
        const struct MusicVoice *v = s->v;
        if (v == 0 || v->count == 0) continue;
        if (s->pending && (s32) (gSfxBusyUntil[kChannel[i]] - gVBlankCount) <= 0) {
            s->pending = 0;
            if (i != V_DRUMS) voice_write(i, s->note, s->level); /* back from the effect */
        }
        if (s->wait) s->wait--;
        while (s->wait == 0) {
            voice_apply(i, s, &v->ev[s->idx * 3]);
            s->idx++;
            if (s->idx == v->count) {
                s->idx = v->loop;
                s->wait = v->tail;
                if (s->wait == 0) s->wait = 1;
                break;
            }
            s->wait = v->ev[s->idx * 3];
        }
    }
}

void music_init(void) {
    s32 i;
    /* the bass's wave: a soft square-ish shape, 32 4-bit samples (bank 0) */
    static const u16 kWave[8] = { 0xEFCD, 0xFFFF, 0xEEFF, 0xACDE, 0x3210, 0x0000, 0x1100, 0x5432 };
    SND3_SEL = 0x0040; /* write bank 0 while bank 1 plays */
    for (i = 0; i < 8; i++) WAVE_RAM[i] = (u16) ((kWave[i] << 8) | (kWave[i] >> 8));
    SND3_SEL = 0;
    gVBlankHook = music_vblank;
}

void music_start(s32 level) {
    s32 i, song = (level >= 0 && level < 4) ? gImpLevelSong[level] : -1;
    music_stop();
    if (song < 0) return;
    for (i = 0; i < 4; i++) {
        struct VoiceState *s = &sVoices[i];
        s->v = &gImpSongs[song].voice[i];
        s->idx = 0;
        s->wait = s->v->count ? s->v->ev[0] : 0;
        s->note = s->level = s->pending = 0;
    }
    sPlaying = 1;
}

void music_stop(void) {
    sPlaying = 0;
    SND1_ENV = SND2_ENV = SND4_ENV = 0x0008;
    SND1_FREQ = SND2_FREQ = SND4_FREQ = 0x8000;
    SND3_SEL = 0;
}
#else
void music_init(void) {}
void music_start(s32 level) { (void) level; }
void music_stop(void) {}
#endif

#ifndef DEMO_SFX_H
#define DEMO_SFX_H

#include <PR/ultratypes.h>

struct Object;

void sfx_init(void);
void sfx_play(u32 soundBits, const struct Object *src); /* the game's sound IDs */
void sfx_coin(s32 red);
void sfx_frame(void);   /* once per game frame */
void sfx_silence(void);

#endif

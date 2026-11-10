#ifndef DEMO_MUSIC_H
#define DEMO_MUSIC_H

#include <PR/ultratypes.h>

extern u32 gSfxBusyUntil[4]; /* demo/sfx.c: VBlank count until which an effect owns GB channel 1..4 */

void music_init(void);
void music_start(s32 level); /* the level's music, if the import has it */
void music_stop(void);

#endif

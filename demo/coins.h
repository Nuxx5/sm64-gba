#ifndef DEMO_COINS_H
#define DEMO_COINS_H

#include "render.h"

extern s32 gCoinCount, gRedCoinCount, gRedCoinTotal;

void coins_init(void);                  /* sprite tiles and palette (once) */
void coins_load(s32 level);             /* placements from the level's macro objects */
void coins_update(const f32 *marioPos); /* collect the coins Mario touches */
void coins_draw(const struct RCamera *cam, s32 farDist);
void coins_hide(void);
void coins_commit(void);                /* OAM writes, during VBlank */

#endif

#ifndef DEMO_ACTORS_H
#define DEMO_ACTORS_H

#include "render.h"

void actors_init(void);   /* sprite tiles and palette (once) */
void actors_draw(const struct RCamera *cam, s32 farDist);
void actors_load_scenery(void); /* after a level loads: its trees */
void actors_hide(void);
void actors_commit(void); /* OAM writes, during VBlank */

#endif

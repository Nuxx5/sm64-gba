#ifndef HARNESS_OBJECTS_H
#define HARNESS_OBJECTS_H

#include <PR/ultratypes.h>
#include "types.h"

s32 objects_level_ported(s32 level);
void objects_clear(void);                 /* empty the object pool (level load) */
struct Object *objects_spawn_mario(void); /* Mario's object, in the player list */
void objects_load(s32 level);             /* the level's ported objects */
s32 objects_count(const BehaviorScript *behavior); /* active objects with it */
void objects_frame(void);                 /* update_objects(): Mario, then the others */
void objects_render_step(void);           /* animation step of the render pass */

#endif

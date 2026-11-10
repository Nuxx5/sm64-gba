/*
 * Objects for the object-enabled builds (the demo and build/host/harness_obj):
 * the decomp's own object system (object_list_processor.c, the behavior
 * script interpreter, object_helpers.c, interaction.c, ...) running the
 * behaviors listed in tools/gen_objsrc.py, with Mario as an object in the
 * player list like in the game.
 *
 * Frame order, as in the game: update_objects() runs the spawners, detects
 * object collisions, then updates the object lists in the game's order,
 * Mario's first (his behavior here is the harness's step: execute his action,
 * copy his state to his object), then the enemies. The N64 then advances
 * animations while rendering; objects_render_step() does that for all of
 * them (the game only does it for objects in view: here, always).
 */
#include <PR/ultratypes.h>
#include "sm64.h"
#include "types.h"
#include "behavior_data.h"
#include "engine/behavior_script.h"
#include "engine/graph_node.h"
#include "game/level_update.h"
#include "game/macro_special_objects.h"
#include "game/mario.h"
#include "game/memory.h"
#include "game/object_helpers.h"
#include "game/object_list_processor.h"
#include "game/spawn_object.h"
#include "macro_presets.h"
#include "level_misc_macros.h"
#include "dialog_ids.h"
#include "objects.h"

#include "levels/bob/areas/1/macro.inc.c"

void copy_mario_state_to_object(void);
extern const BehaviorScript bhvHarnessMarioScript[];
void mario_anim_render_step(struct Object *obj);

/* Per level, in gHarnessLevels order. */
static const MacroObject *const kLevelMacros[] = { bob_seg7_macro_objs, NULL, NULL, NULL };

/* Macro presets spawned as objects (the rest are static, or not ported). */
static const u8 kPorted[] = {
    macro_goomba, macro_goomba_triplet_spawner, macro_bobomb, macro_bobomb_stationary,
};

/* The game marks killed objects in the level's macro list (respawn info), so
 * the list must be writable: the ported entries are copied here. */
#define MAX_MACRO_OBJS 48
static MacroObject sMacroList[MAX_MACRO_OBJS * 5 + 1];

/* Mario's behavior (bhvHarnessMarioScript, tools/gen_objsrc.py): the game's
 * bhvMario with the harness's update: no particle objects, no debug hooks. */
void harness_mario_update(void) {
    gCurrentObject->oMarioParticleFlags = execute_mario_action(gCurrentObject);
    copy_mario_state_to_object();
}

s32 objects_level_ported(s32 level) {
    return level >= 0 && level < (s32) (sizeof(kLevelMacros) / sizeof(kLevelMacros[0]))
           && kLevelMacros[level] != NULL;
}

void objects_init_model_tags(void);

void objects_clear(void) {
    objects_init_model_tags();
    clear_objects();
}

struct Object *objects_spawn_mario(void) {
    struct Object *o = create_object(bhvHarnessMarioScript);
    o->header.gfx.areaIndex = 1;
    o->header.gfx.activeAreaIndex = 1;
    o->header.gfx.node.flags |= GRAPH_RENDER_ACTIVE | GRAPH_RENDER_HAS_ANIMATION;
    return o;
}

void objects_load(s32 level) {
    const MacroObject *m;
    s32 n = 0, i;
    if (!objects_level_ported(level)) return;
    for (m = kLevelMacros[level]; *m != MACRO_OBJECT_END() && n < MAX_MACRO_OBJS; m += 5) {
        s32 preset = (m[0] & 0x1FF) - 31;
        for (i = 0; i < (s32) sizeof(kPorted); i++) {
            if (preset == kPorted[i]) {
                for (i = 0; i < 5; i++) sMacroList[n * 5 + i] = m[i];
                n++;
                break;
            }
        }
    }
    sMacroList[n * 5] = -1;
    spawn_macro_objects(1, sMacroList);
}

/* Active objects running a behavior (for the demo's checks). */
s32 objects_count(const BehaviorScript *behavior) {
    s32 i, n = 0;
    for (i = 0; i < OBJECT_POOL_CAPACITY; i++) {
        if (gObjectPool[i].activeFlags != ACTIVE_FLAG_DEACTIVATED
            && gObjectPool[i].behavior == segmented_to_virtual(behavior)) {
            n++;
        }
    }
    return n;
}

void objects_frame(void) {
    update_objects(0);
}

/* The render pass's animation step, for every object but Mario (the harness
 * steps him itself, as before objects). */
void objects_render_step(void) {
    s32 i;
    for (i = 0; i < OBJECT_POOL_CAPACITY; i++) {
        struct Object *o = &gObjectPool[i];
        if (o->activeFlags == ACTIVE_FLAG_DEACTIVATED || o == gMarioObject) continue;
        if (o->header.gfx.animInfo.curAnim != NULL) mario_anim_render_step(o);
    }
}

#ifdef OBJ_DEBUG
extern void *stderr;
int fprintf(void *f, const char *fmt, ...);
void objects_debug(s32 frame) {
    s32 i, n = 0;
    for (i = 0; i < OBJECT_POOL_CAPACITY; i++) if (gObjectPool[i].activeFlags != ACTIVE_FLAG_DEACTIVATED) n++;
    fprintf(stderr, "frame %d: %d objects, mario %.0f %.0f %.0f hp %x act %x\n", frame, n,
            gMarioState->pos[0], gMarioState->pos[1], gMarioState->pos[2], gMarioState->health, gMarioState->action);
    for (i = 0; i < OBJECT_POOL_CAPACITY; i++) {
        struct Object *o = &gObjectPool[i];
        if (o->activeFlags == ACTIVE_FLAG_DEACTIVATED || o == gMarioObject) continue;
        fprintf(stderr, "  %2d %-8s act %d pos %6.0f %6.0f %6.0f dist %6.0f\n", i,
                o->behavior == segmented_to_virtual(bhvGoomba) ? "goomba"
                : o->behavior == segmented_to_virtual(bhvBobomb) ? "bobomb"
                : o->behavior == segmented_to_virtual(bhvGoombaTripletSpawner) ? "triplet"
                : o->behavior == segmented_to_virtual(bhvExplosion) ? "explode" : "other",
                o->oAction, o->oPosX, o->oPosY, o->oPosZ, o->oDistanceToMario);
    }
}
#endif

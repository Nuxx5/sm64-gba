/*
 * Object builds (HARNESS_OBJECTS), included by src/stubs.c: the object code is
 * the decomp's, compiled; what it reaches outside of gameplay lands here.
 * Graph-node setup that behaviors read (animation, position, flags) is copied
 * from the decomp's graph_node.c; rendering, sound, cutscenes, debug, save
 * file and effects not ported yet are no-ops.
 */
#include "engine/math_util.h"
#include "game/spawn_sound.h"

/* No models: each model ID gets a distinct stand-in "graph node", a byte of
 * gModelTags, so cur_obj_has_model() still tells models apart and the demo's
 * renderer can tell what to draw (model = sharedChild - gModelTags). */
u8 gModelTags[256];
static struct GraphNode *sLoadedGraphNodes[256];
struct GraphNode **gLoadedGraphNodes = sLoadedGraphNodes;

void objects_init_model_tags(void) {
    s32 i;
    sLoadedGraphNodes[0] = NULL; /* MODEL_NONE */
    for (i = 1; i < 256; i++) sLoadedGraphNodes[i] = (struct GraphNode *) &gModelTags[i];
}
struct GraphNodeObject *gCurGraphNodeObject;
struct GraphNodeHeldObject *gCurGraphNodeHeldObject;
struct GraphNodeCamera *gCurGraphNodeCamera;
struct GraphNode gObjParentGraphNode;
Vec3s gVec3sZero = { 0, 0, 0 };
Vec3f gVec3fOne = { 1.0f, 1.0f, 1.0f };
s16 gCurrCourseNum = 1;
struct Controller *gPlayer3Controller = &gControllers[2];
struct Object *gSecondCameraFocus;
const Collision warp_pipe_seg3_collision_03009AC8[] = { 0x0040, 0, 0x0041, 0x0042 }; /* empty */

/* ---- graph_node.c ---- */

void geo_obj_init(struct GraphNodeObject *graphNode, void *sharedChild, Vec3f pos, Vec3s angle) {
    vec3f_set(graphNode->scale, 1.0f, 1.0f, 1.0f);
    vec3f_copy(graphNode->pos, pos);
    vec3s_copy(graphNode->angle, angle);

    graphNode->sharedChild = sharedChild;
    graphNode->unk4C = 0;
    graphNode->throwMatrix = NULL;
    graphNode->animInfo.curAnim = NULL;

    graphNode->node.flags |= GRAPH_RENDER_ACTIVE;
    graphNode->node.flags &= ~GRAPH_RENDER_INVISIBLE;
    graphNode->node.flags |= GRAPH_RENDER_HAS_ANIMATION;
    graphNode->node.flags &= ~GRAPH_RENDER_BILLBOARD;
}

void geo_obj_init_spawninfo(struct GraphNodeObject *graphNode, struct SpawnInfo *spawn) {
    vec3f_set(graphNode->scale, 1.0f, 1.0f, 1.0f);
    vec3s_copy(graphNode->angle, spawn->startAngle);

    graphNode->pos[0] = (f32) spawn->startPos[0];
    graphNode->pos[1] = (f32) spawn->startPos[1];
    graphNode->pos[2] = (f32) spawn->startPos[2];

    graphNode->areaIndex = spawn->areaIndex;
    graphNode->activeAreaIndex = spawn->activeAreaIndex;
    graphNode->sharedChild = spawn->model;
    graphNode->unk4C = spawn;
    graphNode->throwMatrix = NULL;
    graphNode->animInfo.curAnim = 0;

    graphNode->node.flags |= GRAPH_RENDER_ACTIVE;
    graphNode->node.flags &= ~GRAPH_RENDER_INVISIBLE;
    graphNode->node.flags |= GRAPH_RENDER_HAS_ANIMATION;
    graphNode->node.flags &= ~GRAPH_RENDER_BILLBOARD;
}

void geo_obj_init_animation(struct GraphNodeObject *graphNode, struct Animation **animPtrAddr) {
    struct Animation **animSegmented = segmented_to_virtual(animPtrAddr);
    struct Animation *anim = segmented_to_virtual(*animSegmented);

    if (graphNode->animInfo.curAnim != anim) {
        graphNode->animInfo.curAnim = anim;
        graphNode->animInfo.animFrame = anim->startFrame + ((anim->flags & ANIM_FLAG_BACKWARD) ? 1 : -1);
        graphNode->animInfo.animAccel = 0;
        graphNode->animInfo.animYTrans = 0;
    }
}

void geo_obj_init_animation_accel(struct GraphNodeObject *graphNode, struct Animation **animPtrAddr, u32 animAccel) {
    struct Animation **animSegmented = segmented_to_virtual(animPtrAddr);
    struct Animation *anim = segmented_to_virtual(*animSegmented);

    if (graphNode->animInfo.curAnim != anim) {
        graphNode->animInfo.curAnim = anim;
        graphNode->animInfo.animYTrans = 0;
        graphNode->animInfo.animFrameAccelAssist =
            (anim->startFrame << 16) + ((anim->flags & ANIM_FLAG_BACKWARD) ? animAccel : -animAccel);
        graphNode->animInfo.animFrame = graphNode->animInfo.animFrameAccelAssist >> 16;
    }

    graphNode->animInfo.animAccel = animAccel;
}

/* geo_reset_object_node() without the scene graph */
void geo_reset_object_node(struct GraphNodeObject *graphNode) {
    graphNode->node.type = GRAPH_NODE_TYPE_OBJECT;
    graphNode->node.flags = 0;
    graphNode->sharedChild = NULL;
    graphNode->throwMatrix = NULL;
    graphNode->animInfo.curAnim = NULL;
    vec3f_set(graphNode->scale, 1.0f, 1.0f, 1.0f);
    vec3f_copy(graphNode->pos, gVec3fZero);
    vec3s_copy(graphNode->angle, gVec3sZero);
    graphNode->node.flags &= ~GRAPH_RENDER_ACTIVE;
}

struct GraphNode *geo_add_child(UNUSED struct GraphNode *parent, struct GraphNode *child) { return child; }
struct GraphNode *geo_remove_child(struct GraphNode *graphNode) { return graphNode; }
struct GraphNode *geo_make_first_child(struct GraphNode *newFirstChild) { return newFirstChild; }
void *alloc_display_list(UNUSED u32 size) { return NULL; }

/* klepto.inc.c (not ported), used by others */
void obj_set_speed_to_zero(void) {
    gCurrentObject->oForwardVel = gCurrentObject->oVelY = 0.0f;
}

/* ---- memory.c ---- */
struct MemoryPool *mem_pool_init(UNUSED u32 size, UNUSED u32 side) { return NULL; }

/* ---- sound ---- */
void cur_obj_play_sound_1(UNUSED s32 soundMagic) {}
void cur_obj_play_sound_2(UNUSED s32 soundMagic) {}
void create_sound_spawner(UNUSED s32 soundMagic) {}
void stop_sounds_from_source(UNUSED f32 *pos) {}
void play_cap_music(UNUSED u16 seqArgs) {}
void fadeout_level_music(UNUSED s16 fadeTimer) {}
void drop_queued_background_music(void) {}

/* ---- level, camera, cutscenes, save file ---- */
u16 level_control_timer(UNUSED s32 timerOp) { return 0; }
s16 cutscene_object_with_dialog(UNUSED u8 cutscene, UNUSED struct Object *o, UNUSED s16 dialogID) { return 0; }
s16 cutscene_object_without_dialog(UNUSED u8 cutscene, UNUSED struct Object *o) { return 0; }
s16 cutscene_object(UNUSED u8 cutscene, UNUSED struct Object *o) { return 0; }
void set_environmental_camera_shake(UNUSED s16 shake) {}
void set_camera_shake_from_point(UNUSED s16 shake, UNUSED f32 posX, UNUSED f32 posY, UNUSED f32 posZ) {}
void save_file_set_cap_pos(UNUSED s16 x, UNUSED s16 y, UNUSED s16 z) {}
void save_file_set_cannon_unlocked(void) {}
void save_file_collect_star_or_key(UNUSED s16 coinScore, UNUSED s16 starIndex) {}

/* ---- effects and behaviors not ported yet ---- */
void spawn_mist_particles_variable(UNUSED s32 count, UNUSED s32 offsetY, UNUSED f32 size) {}
void spawn_triangle_break_particles(UNUSED s16 numTris, UNUSED s16 triModel, UNUSED f32 triSize,
                                    UNUSED s16 triAnimState) {}
void spawn_default_star(UNUSED f32 homeX, UNUSED f32 homeY, UNUSED f32 homeZ) {}
void bhv_spawn_star_no_level_exit(UNUSED u32 starIndex) {}
void wiggler_jumped_on_attack_handler(void) {}
void shelled_koopa_attack_handler(UNUSED s32 attackType) {}

/* ---- profiling and debug ---- */
s64 get_current_clock(void) { return 0; }
s64 get_clock_difference(UNUSED u64 cycles) { return 0; }
void print_debug_top_down_objectinfo(UNUSED const char *str, UNUSED s32 number) {}
void try_print_debug_mario_object_info(void) {}
void stub_debug_5(void) {}
void reset_debug_objectinfo(void) {}
void debug_unknown_level_select_check(void) {}
void spawn_wind_particles(UNUSED s16 pitch, UNUSED s16 yaw) {}

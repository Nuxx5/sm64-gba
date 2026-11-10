#ifndef DEMO_ENEMY_ART_H
#define DEMO_ENEMY_ART_H

/* Offline poses of the original models: Goomba walk, Bob-omb walk/held.
 * Each animation has 2 eye states x 8 views x 8 animation phases. The
 * palette is shared; each tile word contains four 4-bit pixel indices. */
extern const unsigned short gImpEnemyPal[15];
extern const unsigned short gImpEnemySize[2];
extern const short gImpEnemyCenter[2];
extern const unsigned char gImpEnemyLength[3];
extern const unsigned char gImpEnemyPhase[3][30];
extern const unsigned short gImpEnemySmall[3][128][64];
extern const unsigned short gImpEnemyLarge[3][128][256];

#endif

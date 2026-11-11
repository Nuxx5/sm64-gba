#ifndef DEMO_INTRO_H
#define DEMO_INTRO_H

/* Optional locally imported opening movie. A fresh Start press skips it.
 * Returns with video blanked and Direct Sound DMA/timer fully stopped. */
void intro_run(void (*logger)(const char *));

#endif

#ifndef DEMO_TITLE_H
#define DEMO_TITLE_H

/* 1 = New Game, 2 = Continue. Existing saves require confirmation before
 * replacement. The logger is optional and used by headless boot tests. */
int title_run(int haveSave, void (*logger)(const char *));

#endif

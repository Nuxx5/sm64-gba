#ifndef DEMO_INTRO_CODEC_H
#define DEMO_INTRO_CODEC_H

/* Halfword stream: 00=literal, 01=repeat, 10=unchanged, 11=invalid.
 * Low 14 bits give the word count. Zero terminates a complete frame.
 * Unchanged words refer to the previous contents of this bitmap page
 * (frame n-2), so no decompression buffer is needed in work RAM. */
int intro_decode(const unsigned short *source, unsigned sourceWords,
                 volatile unsigned short *destination, unsigned words);

#endif

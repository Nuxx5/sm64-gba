// A small sequence in the decomp's sequence macros (include/seq_macros.inc),
// assembled by binutils: tools/test_music.py checks what tools/n64seq.py
// plays from it (tempo, loops, calls, large and small notes, transposition).
#include "seq_macros.inc"
.section .rodata
.align 0
sequence_start:
    seq_settempo 120
    seq_setvol 127
    seq_initchannels 0x3
    seq_startchannel 0, .chan0
    seq_startchannel 1, .chan1
.top:
    seq_delay 192
    seq_jump .top

.chan0:
    chan_largenoteson
    chan_setinstr 3
    chan_setvol 127
    chan_setlayer 0, .layer0
.chan0_wait:
    chan_delay 192
    chan_jump .chan0_wait

.layer0:
    layer_note1 39, 48, 100          // C4, a beat, velocity 100
    layer_loop 2
    layer_call .sub
    layer_loopend
    layer_note0 46, 48, 80, 128      // G4, held half the beat
.layer0_rest:
    layer_delay 192
    layer_jump .layer0_rest

.sub:
    layer_note1 43, 24, 90           // E4, half a beat
    layer_end

.chan1:
    chan_setinstr 0x7f               // drum kit
    chan_transpose 2
    chan_setlayer 0, .layer1
.chan1_wait:
    chan_delay 192
    chan_jump .chan1_wait

.layer1:
    layer_setshortnotevelocity 64
    layer_setshortnotedefaultplaypercentage 96
    layer_somethingon
    layer_somethingoff
    .byte 0x40 + 10                   // small note type 1 (no macro): default play percentage 96, velocity 64
.layer1_rest:
    layer_delay 192
    layer_jump .layer1_rest

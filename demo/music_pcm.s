@ The true build's music (make import ROM=...): build/import/music_pcm.bin,
@ rendered from your ROM's samples. Only assembled when it exists.
    .section .rodata
    .align 2
    .global gImpPcm
gImpPcm:
    .incbin "build/import/music_pcm.bin"

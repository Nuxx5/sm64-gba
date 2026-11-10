# Handoff: state of the work (branch `claude/affectionate-johnson-enpy9o`)

Written for whoever continues this (another assistant or a person). Read
`README.md` first for the project itself; this file covers what this branch
added, how to check it, and what is half done.

## Continuation: full asset library and real-ROM music (2026-11-10)

The user requested all assets, not only music, and text-only updates (do not
post videos or pictures in chat). Their uploaded US ROM matches the expected
SHA-1. Keep the upload, extracted assets and built ROMs out of Git.

- `make import ROM=...` now extracts the complete version-specific library
  before the existing demo conversion. `make import-assets ROM=...` extracts
  only the library, using native host tools. See `tools/asset_library.py`.
- The pinned extractor runs in a disposable workspace, leaving `sm64/`
  unchanged. US extraction verified: 1,539 ROM assets and 2,512 decomp source
  definitions. All 1,278 PNGs also produce GBA 4bpp tiles and RGB555 palettes.
  The library manifest has hashes, provenance, actor/level groups and image
  dimensions. `make asset-library-check` verifies the complete output.
- Full extraction is separate from engine support: imported model textures
  are not rendered enemy sprites; behavior sources do not activate new
  objects. The demo still uses its existing four-level subset.
- Real music initially skipped every demo song. `sequence_channel_enable`
  preserves instrument and large-note settings when restarting a channel;
  the Python player reset them and lost instruction alignment. Fixed channel
  restart/reinitialization and `chan_writeseq` semantics, with original
  bytecode regression fixtures in `tools/test_n64seq.py`.
- All three real demo sequences now parse and render: grass 1,419 notes,
  snow 1,753, koopa road 1,704. Song lengths are about 72.2/91.0/71.1 s.
  The older "never run on a real ROM" notes below describe the prior state.

## Ground rules (keep these)

1. **Mario's physics stay bit-exact.** Every gameplay change must keep
   `make demo-check` passing: it replays the demo's inputs through the PC
   reference (`build/host/harness_obj`) and compares Mario's position bit for
   bit, on 3 routes (plus `make test`, `make gba-opt-test` for the parity
   suites). Optimizations must not change results (same C source, or proven
   exact like `src/fast/sqrtf_exact.c`, checked by `make sqrtf-check`).
2. **No Nintendo assets in the repository.** Art and music come only from the
   user's own ROM through `make import ROM=...` into `build/import/`
   (git-ignored, as are `*.z64 *.v64 *.n64 *.gba`). Without a ROM the demo
   uses drawn stand-ins and has no music.
3. The decomp (`make fetch` -> `sm64/`) is never modified; decomp code used in
   the build is copied at build time (`tools/gen_objsrc.py`) or included.

## Build and check

```sh
docker build -t sm64-gba .          # toolchain (or the packages in the Dockerfile)
make fetch                          # the decomp at a pinned revision
make demo                           # build/demo/sm64demo.gba
make demo-check                     # physics (3 routes, bit-exact) + frame-rate tour
make test && make gba-opt-test      # parity suites (23 scripts, PC/ARM/GBA)
make import ROM=sm64.us.z64         # optional: the game's art and music
make import-check ROM=sm64.us.z64   # import's texture reading vs the decomp's tools
```

`build/mgba_runner ROM --frames N [--keys F | --keys-game F] [--capture DIR K]
[--audio out.wav]` runs the demo headless (debug stats on stdout, one `f`
line per game frame: `p` physics cycles, `H` health, `G` Goombas alive,
`V` lives, `w` stack use, ...). `MGBA_PROFILE=file` + `tools/gba_pcprof.py`
profiles it.

## What this branch added (all pushed, all checked)

- **Coins** in BoB at their original places (`demo/coins.c`): macro objects
  from the decomp, formations, floor snap, pickup, counter, spin, ROM art.
- **Enemies: Goombas and Bob-ombs** in BoB running the decomp's own object
  system (`src/obj/`, `tools/gen_objsrc.py`: object list processor, behavior
  interpreter, object_helpers, interaction.c, collision; pool of 40 objects).
  Mario is an object in the player list. Drawn as sprites (`demo/actors.c`).
- **Trees** (BoB's special objects) drawn as sprites, no climbing.
- **Sound effects** on the GB channels from the game's sound IDs (`demo/sfx.c`).
- **Lives (4) and game over**, **health meter** (power meter style, `demo/hud.c`).
- **ROM art import** (`tools/import_rom.py` -> `build/import/sprite_art.c`):
  coin spin frames, bubbly tree, power meter. Enemies still stand-ins.
- **Performance** (same results): exact fast sqrtf, skipped empty dynamic
  surface clear, hot object functions as ARM in IWRAM (`gba/demo.ld`), sprite
  projection without divisions. BoB Mario+objects 184k -> 136k cycles/frame;
  BoB at quality step 1 (one below full), 99.5% of frames at 30 fps.
- **Test tooling**: `--keys-game` (key scripts in game frames), `--expect
  hurt|stomp` in `tools/demo_physics_check.py`, `--audio` WAV recording.

OAM slots: HUD 0-34, health meter 35, enemies 36-47, coins 48-87, near trees
88-92, mannequin 93-112, far trees 113-127. OBJ tiles: coins 600-767, enemies
768-831, trees 832-1001, meter 1002-1017. Palette bank 0: HUD 1-2, coins
3-10, enemies 11-15; banks 1-12 mannequin, 13 trees, 14 meter. EWRAM is
~254.7 of 256 KB; IWRAM leaves 3.8 KB of stack (peak 1.9 KB).

## In progress: music (committed, partly working)

Goal (asked by the user): background music from the ROM, two builds:
**chiptune** (sequence arranged for the 4 GB voices) and a **"true" build**
with the real instrument samples. Nothing musical can be committed; it is all
generated by `make import`.

Done and verified (without a ROM, on synthetic data):

- `tools/n64seq.py`: plays an `.m64` sequence like the decomp's
  `src/audio/seqplayer.c` (US) into timed notes + loop point. Tested with
  `src/test/music/test_seq.s` (decomp macros; build:
  `arm-none-eabi-gcc -x assembler-with-cpp -DVERSION_US -I sm64/include -c
  src/test/music/test_seq.s -o t.o && arm-none-eabi-objcopy -O binary -j
  .rodata t.o t.m64`; expected: 5 notes, loop 0.00..2.00 s).
- `tools/n64audio.py`: banks/samples/sequences from the ROM via the decomp's
  `tools/disassemble_sound.py`; `vadpcm_decode()` matches the SDK's
  `vadpcm_dec` exactly (checked: 3008 samples, 0 differences; the SDK tools
  build with `make -C sm64/tools/sdk-tools/adpcm native`).
- `tools/n64music.py` `chip()`: 4-voice arrangement as 60 Hz event streams.
- `demo/music.c` chip player, driven from the VBlank interrupt
  (`gVBlankHook`, `demo/irq.s`); sound effects mark channels busy
  (`gSfxBusyUntil`) and the music yields. Checked in mGBA with a synthetic
  `build/import/music_data.c`: right pitches, durations, 2 s loop.
- `tools/import_rom.py` writes `build/import/music_data.c` (songs:
  `03_level_grass` for BoB/WF, `08_level_snow` CCM, `11_level_koopa_road`
  BITDW; a song the player can't parse is skipped with a warning).

**Never run on a real ROM.** First thing to do with one: `make import
ROM=...`, read the `music:` lines (notes, loop times), `make demo`, listen.
Likely issues: unhandled sequence commands (`SeqError` -> that song skipped:
add the command in `n64seq.py` following `seqplayer.c`/`seq_decoder.py`),
voice roles that pick the wrong channels (`_roles()` in `n64music.py`),
levels too loud/quiet (`level` formula in `_mono()`), drum mapping.

Done since: the true build (import writes `music_pcm.bin` + `music_pcm.c`;
`demo/music.c` streams it with timer 0 + DMA 1, looping in the VBlank hook;
default when present, `MUSIC=chip` for the chiptune) and `make music-check`
(`tools/test_music.py`). Both builds were checked in mGBA with a synthetic
bank (right pitch, 2.0 s loop, physics still bit-exact).

Still to do:

1. Run it with a real ROM and fix what comes up (see above).
2. Ideas left from earlier: enemy sprites from the ROM (render the models to
   sprites at import), King Bob-omb / Chain Chomp / signposts as solid
   objects, 1-ups, BoB full resolution (needs ~15-20k more cycles/frame).

## Where things are

| Path | What |
|---|---|
| `demo/demo_main.c` | demo loop, level load, lives, HUD text, debug stats |
| `demo/coins.c`, `actors.c`, `hud.c`, `sfx.c`, `music.c` | coins, enemy/tree sprites, HUD + meter, effects, music |
| `src/obj/` | objects for the harness and demo (spawn, frame, stubs) |
| `tools/gen_objsrc.py` | decomp object sources cut down, IWRAM marking |
| `tools/import_rom.py` | the ROM import (art, music) |
| `tools/n64seq.py`, `n64audio.py`, `n64music.py` | music: sequences, sound data, arrangement/render |
| `gba/demo.ld`, `gba/mgba_runner.c` | demo memory layout, headless runner |
| `demo/keys/*.keys` | input scripts (goomba_* are in game frames) |

# Handoff: state of the work (branch `claude/affectionate-johnson-enpy9o`)

Written for whoever continues this (another assistant or a person). Read
`README.md` first for the project itself; this file covers what this branch
added, how to check it, and what is half done.

## Continuation: headless opening FMV (2026-11-11)

The uploaded `Super Mario 64 Opening Cutscene Super Mario 3D All-Stars.mp4`
is the source for the new movie, not a YouTube download or a new ROM capture.
Keep working headless: user is at work and does not want images/videos posted.
Source SHA-256 and crop are recorded in ignored `build/import/intro/manifest.json`.
The clip is 30.046621 s with 29.931926 s of video; the final frame is held to
preserve the complete audio. Detected black borders crop to 960x672 at 160,24;
active picture proportions are retained within the 240x160 output.

`make import-intro VIDEO=...` runs `tools/import_intro.py` with ffmpeg/Pillow.
It stages conversion then replaces the import atomically, retaining the old
working movie on failure. Generated palette, offsets, video/audio binaries,
header, assembler blob and manifest all remain under ignored build/import.
No media, generated assets or ROMs should enter Git. MP4 inputs are ignored.

`demo/intro.c` plays only after confirmed New Game. The New Game SRAM record
commits before playback; Continue skips the movie. A fresh Start press skips
and stops DMA/timer cleanly; held title Start is consumed. `NOINTRO=1` and
`NOIMPORT=1` omit the movie. Bench mode bypasses menu/movie as before.
`demo/intro_codec.c` decodes bounded halfword literal/repeat/skip commands
directly into the back VRAM page, with deltas against frame n-2. Both pages
are cleared first. No video RAM buffer is allocated in EWRAM. Level music's
VBlank hook is suspended during the movie and restored on every exit path;
movie audio uses DMA1/timer0, signed 8-bit mono, 224 samples/VBlank exactly.

The imported movie has 449 frames at 14.9319 fps, 30.07 s playback duration,
11,689,046 compressed video bytes and 402,432 audio bytes including DMA padding.
Sampled ROM: 18,500,280 bytes; chip ROM: 15,360,816 bytes; both fit 32 MiB.
IWRAM end stays 0x030074B0, EWRAM end 0x0203DDE0 (same as title/save build).
ZIP the ROM downloads to fit the Pages 10 MiB file-upload limit; users extract
and run the .gba. Keep prior builds on the same private download Page.

`make intro-check` checks native malformed/truncated streams, run/count
boundaries, original synthetic video conversion, crop/aspect/audio behavior,
failed-import recovery, and every real converted frame SHA-256 against the C
decoder. `make intro-runtime-check` boots the real ROM headless: all 449
frames must appear in order and meet four-VBlank deadlines, with source audio
envelope correlation >0.9 and <=80 ms A/V offset; then tests skip, held Start,
and Continue. Both music builds pass (zero late frames; ~10 ms A/V offset).
Runner `--start-game` also skips intro automatically; standalone `--skip-intro`
lets existing UI checks run quickly. The held-Start SRAM test now waits for
actual gameplay before corrupting the latest of its two records.

Final regression: sampled/chip demo physics routes and live enemy checks pass
(2,499/2,196 sprite observations). Both music builds pass nine save/menu
checks. `make test` passes 23/23 scripts (53,139 frames); `gba-opt-test`
passes 23/23 ROMs. Random-memory tour: 1,228 game frames and all 2,880 screen
hashes identical. NOINTRO save checks and NOIMPORT demo/save checks pass.
ZIPs contain one ROM each and pass ZIP CRC plus extracted-ROM SHA-256 checks.

## Continuation: animated imported enemies (2026-11-10)

Goombas and black Bob-ombs now use the original models and ROM textures,
baked offline by `tools/bake_enemies.py`. The existing object behaviors and
physics are unchanged. `make import ROM=...` generates `enemy_art.c` and
`enemy_art.json`; a standalone baker command can refresh only that art.

- 384 poses: Goomba walk, Bob-omb walk/held, two eye states, eight directions
  and eight animation phases. Original geo layouts, scale, animation
  channels and billboard nodes are interpreted. Lighting and the 15-degree
  orthographic sprite camera are approximations. Runtime selects the pose
  using gfx facing, curAnim/frame and oAnimState; object animation helpers
  do not update Mario's animID field, so Bob-omb uses curAnim identity.
- Each pose has 16px/32px 4bpp tiles, with shared OBJ palette bank 15. Two
  nearby actors can use 32px art. Per-object affine matrices preserve gfx
  scale and squash. Sprites remain billboards without terrain depth tests.
- Imported-only VRAM: large slots 768..799; small slots 800..831 and
  576..591 (the unused mannequin ball); explosion 592..595. Existing coins
  at 600..767 and trees at 832+ are unchanged. Matrices 0..11 are reused
  after mannequin_commit while Mario uses his real model. Tile uploads are
  cached and done in VBlank (at most 2,304 bytes/frame). Fallback art and
  its allocations remain available in NOIMPORT builds.
- `make enemy-check` adds synthetic alpha/depth, rotation and billboard
  tests; validates all pose/view/eye-state images and transparent borders;
  and compares live mGBA OAM/VRAM tile and palette hashes against baked data.
  Both Goomba and Bob-omb, both sprite sizes and 130 distinct images were
  observed: 1,731 sampled-build / 1,730 chip-build sprite observations.
  The runner's `--sprite-report FILE` is text-only; no pictures are posted.
- Full import and library checks passed. Both music builds pass demo physics
  checks including hurt/stomp (sampled: 674/328/340 frames; chip:
  674/327/339). `make test`: 23/23 scripts, 53,139 frames;
  `make gba-opt-test`: 23/23 ROMs; randomized-memory check: 1,238 game frames
  and 2,880 framebuffer hashes identical. NOIMPORT demo-check also passes.
  Imported tours reach 30 fps on about 94%/93% of frames (sampled/chip).
  Sampled EWRAM use: 253,344 bytes; IWRAM stack peak 2,000 of 2,640 bytes.

No ROM, baked art, generated audio or built ROMs belong in Git. Keep updates
text-only as requested. Refresh both private ROM downloads after rebuilding.

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
- Full extraction is separate from engine support: the Goomba/Bob-omb
  sprite path above now uses some of those models, but other imported
  behavior sources do not activate new objects. The demo still uses its
  existing four-level subset.
- Real music initially skipped every demo song. `sequence_channel_enable`
  preserves instrument and large-note settings when restarting a channel;
  the Python player reset them and lost instruction alignment. Fixed channel
  restart/reinitialization and `chan_writeseq` semantics, with original
  bytecode regression fixtures in `tools/test_n64seq.py`.
- All three real demo sequences now parse and render: grass 1,419 notes,
  snow 1,753, koopa road 1,704. Song lengths are about 72.2/91.0/71.1 s.
  The older "never run on a real ROM" notes below describe the prior state.
- Real imported builds exposed two memory issues: EWRAM overflow and too
  little IWRAM stack. The import now emits `import_limits.h` so renderer
  mesh/cache capacities match the largest imported level (670 vertices,
  1,058 triangles), retaining all geometry. The blob-shadow routine moves
  to ROM in imported builds. Sampled build EWRAM use: 253,236 bytes; IWRAM
  stack available: 2,640 bytes, measured tour peak: 2,000 bytes.
- Validation: full US import and library integrity pass; 1,267 ordinary
  textures plus ten skyboxes match native decomp tools. `make music-check`
  passes. Both PCM and chip `make demo-check` pass all three physics routes
  (669/331/342 frames, including hurt/stomp). Tours reach 30 fps on about
  95%/94% of frames respectively; CCM is 87%, so performance work remains.
  `make test`: 23/23 scripts, 53,139 frames. `make gba-opt-test`: 23/23 ROMs.
  This cloud kernel rejects i386 executables; the unchanged 32-bit PC
  reference binaries were run through `qemu-i386` using local build wrappers.

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


## Title and SRAM saves (November 2026)

`demo/title.c` runs before gameplay; Start = New Game, A = Continue when
saved, Start then A confirms overwrite, B cancels. L+R+Start returns to title.
`tools/import_title.py` captures 48 original US-ROM Mario-face idle frames
using Mupen64Plus Rice/HLE (`Dockerfile.title`), quantizes to Mode 4 and emits
ignored `build/import/title_art.c`. This is prerecorded animation, no live
Goddard face deformation; no claim of pixel identity at GBA resolution.
`NOIMPORT=1` uses a text title. Capture is a separate `make import-title`
step because it needs the optional emulator tools and currently supports US.

`demo/save.c` maintains two versioned CRC32 records at SRAM offsets 4096 and
4224 (outside benchmark data). New records commit magic last. Saved profile:
level, lives, visited mask, 96 coin flags per each of four levels and best
coin counts. Autosave on coin/life/level changes; Continue respawns at entrance.
`make save-check` tests interrupted writes/corruption; `save-ui-check` boots
the real ROM repeatedly and exercises title controls and persistent saves.
Runner `--start-game` bypasses title for existing checks; `--title-keys` uses
script times relative to title readiness. Save fixtures use bus writes to
initialize mGBA SRAM autodetection (raw writes silently drop them).

Validation: both sampled/chip demo-check and enemy-check pass (2,020/2,019
live enemy sprite observations, 137 images). NOIMPORT demo-check passes.
Host parity: 23/23 scripts, 53,139 frames. Optimized GBA parity: 23/23 ROMs.
Randomized RAM: 1,230 game frames and 2,880 framebuffer hashes identical.
SRAM native power-cut checks and nine real-ROM menu/persistence checks pass.
EWRAM ends at 0x0203DDE0; IWRAM end remains 0x030074B0. The title loop was
also checked internally in mGBA: successive framebuffers show changing art.

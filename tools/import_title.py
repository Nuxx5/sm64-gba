#!/usr/bin/env python3
"""Capture original US-ROM title frames and bake a GBA Mode 4 idle loop.

Run inside Dockerfile.title, or install mupen64plus (Rice/HLE), Xvfb and Pillow.
Generated frames and C stay under the ignored build/import directory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from PIL import Image

US_SHA1 = '9bef1128717f958171a4afac3ed78ee2bb4e86ce'
FRAMES = list(range(240, 336, 2))


def bake(paths, output):
    images = [Image.open(p).convert('RGB').resize((240, 160), Image.Resampling.LANCZOS) for p in paths]
    sheet = Image.new('RGB', (240, 160 * len(images)))
    for i, image in enumerate(images):
        sheet.paste(image, (0, i * 160))
    palette = sheet.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    colors = palette.getpalette()[:765]
    colors += [0] * (765 - len(colors))
    rgb555 = [0] + [(colors[i] >> 3) | ((colors[i+1] >> 3) << 5) | ((colors[i+2] >> 3) << 10) for i in range(0, 765, 3)]
    with (output / 'title_art.c').open('w') as f:
        f.write('/* Generated locally from the user ROM; do not commit. */\n#include "gba.h"\n')
        f.write('const u16 gImpTitlePalette[256] = {' + ','.join(map(str, rgb555)) + '};\n')
        f.write('const u16 gImpTitleFrameCount = %d;\n' % len(images))
        f.write('const u16 gImpTitleFrames[%d][19200] = {\n' % len(images))
        for image in images:
            pixels = image.quantize(palette=palette, dither=Image.Dither.NONE).tobytes()
            words = [(pixels[i]+1) | ((pixels[i+1]+1) << 8) for i in range(0, len(pixels), 2)]
            f.write('{\n')
            for i in range(0, len(words), 24):
                f.write(','.join(map(str, words[i:i+24])) + ',\n')
            f.write('},\n')
        f.write('};\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rom', required=True, type=Path)
    p.add_argument('--out', type=Path, default=Path('build/import'))
    p.add_argument('--frames', type=Path, help='reuse previously captured PNG frames')
    args = p.parse_args()
    if hashlib.sha1(args.rom.read_bytes()).hexdigest() != US_SHA1:
        p.error('title capture currently supports the verified US big-endian ROM only')
    args.out.mkdir(parents=True, exist_ok=True)
    frames = args.frames or args.out / 'title-frames'
    if not args.frames:
        if frames.exists():
            shutil.rmtree(frames)
        frames.mkdir()
        emulator = shutil.which('mupen64plus') or '/usr/games/mupen64plus'
        subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 640x480x24', emulator,
                        '--noosd', '--nospeedlimit', '--windowed', '--resolution', '320x240',
                        '--audio', 'dummy', '--input', 'dummy', '--gfx', 'mupen64plus-video-rice',
                        '--rsp', 'mupen64plus-rsp-hle', '--configdir', str(args.out / 'title-config'),
                        '--sshotdir', str(frames.resolve()), '--testshots', ','.join(map(str, FRAMES)),
                        str(args.rom.resolve())], check=True)
    paths = sorted(frames.glob('*.png'))
    if len(paths) != len(FRAMES):
        p.error('expected %d captured title frames, got %d' % (len(FRAMES), len(paths)))
    bake(paths, args.out)
    (args.out / 'title-provenance.json').write_text(json.dumps(dict(rom_sha1=US_SHA1,
        renderer='mupen64plus Rice/HLE', frames=FRAMES, resolution=[240,160], colors=256,
        mode='prerendered idle; no interactive face deformation'), indent=2) + '\n')
    print('Wrote %d native title frames to %s' % (len(paths), args.out / 'title_art.c'))


if __name__ == '__main__':
    main()

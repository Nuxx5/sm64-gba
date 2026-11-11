#!/usr/bin/env python3
"""Convert a local opening video to a headless GBA Mode 4 movie import.

No media is stored in the repository. Requires ffmpeg, ffprobe and Pillow.
The decoder updates alternate VRAM pages directly using halfword runs and
frame n-2 deltas. Audio is signed 8-bit mono PCM streamed once from ROM.
"""
import argparse
from array import array
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

from PIL import Image

CLOCK, VBLANK_CYCLES, PERIOD, TIMER = 16777216, 280896, 4, 1254
FPS = CLOCK / VBLANK_CYCLES / PERIOD
WIDTH, HEIGHT = 240, 160
WORDS = WIDTH * HEIGHT // 2
LIMIT = 0x3FFF


def words(data):
    result = array('H')
    result.frombytes(data)
    if sys.byteorder != 'little':
        result.byteswap()
    return result


def packed(values):
    result = array('H', values)
    if sys.byteorder != 'little':
        result.byteswap()
    return result.tobytes()


def encode(current, previous):
    out, at, size = [], 0, len(current)
    while at < size:
        if current[at] == previous[at]:
            end = at + 1
            while end < size and end - at < LIMIT and current[end] == previous[end]:
                end += 1
            if end - at >= 2:
                out.append(0x8000 | (end - at))
                at = end
                continue
        end = at + 1
        while end < size and end - at < LIMIT and current[end] == current[at]:
            end += 1
        if end - at >= 3:
            out.extend((0x4000 | (end - at), current[at]))
            at = end
            continue
        end = at + 1
        while end < size and end - at < LIMIT:
            if end + 1 < size and current[end] == previous[end] and current[end+1] == previous[end+1]:
                break
            if end + 2 < size and current[end] == current[end+1] == current[end+2]:
                break
            end += 1
        out.append(end - at)
        out.extend(current[at:end])
        at = end
    out.append(0)
    return packed(out)


def detect_crop(video):
    result = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(video), '-vf',
                             'fps=1,cropdetect=24:2:0', '-an', '-f', 'null', '-'],
                            capture_output=True, text=True, check=True)
    boxes = [tuple(map(int, match)) for match in re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)', result.stderr)]
    if not boxes:
        return None
    # cropdetect accumulates bounds. Take the largest detected rectangle,
    # rather than trimming to a small initial logo or fade-in frame.
    return max(Counter(boxes), key=lambda box: (box[0] * box[1], Counter(boxes)[box]))


def _convert(video, output, crop=None, blob_root=None):
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                        '-show_format', '-of', 'json', str(video)]))
    if not any(s['codec_type'] == 'video' for s in probe['streams']):
        raise ValueError('source has no video')
    duration = float(probe['format']['duration'])
    if not 0 < duration <= 180:
        raise ValueError('expected an opening clip of at most three minutes')
    frame_count = math.ceil(duration * FPS)
    output.mkdir(parents=True, exist_ok=True)
    crop = crop if crop is not None else detect_crop(video)
    filtering = ['crop=' + ':'.join(map(str, crop))] if crop else []
    # Preserve the active picture's aspect ratio, centering any small bars.
    filtering += ['scale=240:160:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos',
                  'pad=240:160:(ow-iw)/2:(oh-ih)/2:black',
                  'tpad=stop_mode=clone:stop_duration=1', 'fps=%.12f' % FPS]
    raw_path = output / 'frames.rgb'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(video),
                    '-vf', ','.join(filtering), '-frames:v', str(frame_count), '-an',
                    '-f', 'rawvideo', '-pix_fmt', 'rgb24', str(raw_path)], check=True)
    raw = raw_path.read_bytes()
    frame_bytes = WIDTH * HEIGHT * 3
    if len(raw) != frame_count * frame_bytes:
        raise ValueError('ffmpeg produced an incomplete movie')
    # Train a fixed palette on evenly spaced frames. A fixed palette both
    # prevents color flicker and keeps inter-frame deltas useful.
    sample_indices = list(range(0, frame_count, max(1, frame_count // 90)))
    sheet = Image.new('RGB', (WIDTH, HEIGHT * len(sample_indices)))
    for j, i in enumerate(sample_indices):
        image = Image.frombytes('RGB', (WIDTH, HEIGHT), raw[i*frame_bytes:(i+1)*frame_bytes])
        sheet.paste(image, (0, j*HEIGHT))
    palette_rgb = [0, 0, 0] + sheet.quantize(colors=255, method=Image.Quantize.MEDIANCUT).getpalette()[:765]
    fixed = Image.new('P', (1, 1))
    fixed.putpalette(palette_rgb)
    palette = [(palette_rgb[i] >> 3) | ((palette_rgb[i+1] >> 3) << 5) |
               ((palette_rgb[i+2] >> 3) << 10) for i in range(0, 768, 3)]
    previous = [array('H', [0]) * WORDS, array('H', [0]) * WORDS]
    offsets, hashes, payload = [0], [], bytearray()
    for i in range(frame_count):
        image = Image.frombytes('RGB', (WIDTH, HEIGHT), raw[i*frame_bytes:(i+1)*frame_bytes])
        pixels = image.quantize(palette=fixed, dither=Image.Dither.NONE).tobytes()
        current = words(pixels)
        payload.extend(encode(current, previous[i & 1]))
        offsets.append(len(payload) // 2)
        previous[i & 1] = current
        hashes.append(hashlib.sha256(pixels).hexdigest())
    audio_samples = frame_count * PERIOD * 224
    audio_path = output / 'audio.pcm'
    if any(s['codec_type'] == 'audio' for s in probe['streams']):
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(video),
                        '-vn', '-ac', '1', '-ar', '13379', '-f', 's8', str(audio_path)], check=True)
        audio = audio_path.read_bytes()[:audio_samples]
    else:
        audio = b''
    audio = audio.ljust(audio_samples + 128, b'\0')
    audio_path.write_bytes(audio)
    (output / 'video.bin').write_bytes(payload)
    (output / 'palette.bin').write_bytes(packed(palette))
    (output / 'offsets.bin').write_bytes(struct.pack('<%dI' % len(offsets), *offsets))
    (output / 'intro_data.h').write_text('''/* Generated locally from a user video; do not commit. */
#ifndef IMPORT_INTRO_DATA_H
#define IMPORT_INTRO_DATA_H
#include "gba.h"
#define INTRO_FRAMES %d
#define INTRO_PERIOD %d
#define INTRO_WORDS %d
extern const u16 gIntroPalette[256];
extern const u32 gIntroOffsets[INTRO_FRAMES + 1];
extern const u16 gIntroVideo[];
extern const s8 gIntroAudio[];
#endif
''' % (frame_count, PERIOD, WORDS))
    assembly = '.section .rodata.intro, "a", %%progbits\n'
    for name, file in [('gIntroPalette', 'palette.bin'), ('gIntroOffsets', 'offsets.bin'),
                       ('gIntroVideo', 'video.bin'), ('gIntroAudio', 'audio.pcm')]:
        assembly += '.balign 4\n.global %s\n%s:\n.incbin %s\n' % (name, name, json.dumps(str((blob_root or output) / file)))
    (output / 'intro_blob.s').write_text(assembly.replace('%%progbits', '%progbits'))
    report = dict(format_version=1, source_name=video.name, source_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
                  source_duration=duration, crop=crop, width=WIDTH, height=HEIGHT, palette=256,
                  frames=frame_count, vblanks_per_frame=PERIOD, fps=FPS,
                  playback_seconds=frame_count / FPS, video_bytes=len(payload),
                  audio_bytes=len(audio), audio_samples=audio_samples, audio_timer=TIMER,
                  offsets=offsets, frame_sha256=hashes)
    (output / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    raw_path.unlink()
    print('Intro: %d frames, %.2fs, %.2f fps, %d video bytes + %d audio bytes' %
          (frame_count, frame_count / FPS, FPS, len(payload), len(audio)), flush=True)
    print('Active picture crop:', crop, flush=True)
    return report


def convert(video, output, crop=None):
    # Publish a complete import only after every frame and the audio finish.
    # A failed conversion leaves the previous working movie intact.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.intro-', dir=output.parent) as tmp:
        staging, backup = Path(tmp)/'ready', Path(tmp)/'previous'
        report = _convert(video, staging, crop, blob_root=output)
        if output.exists():
            os.replace(output, backup)
        try:
            os.replace(staging, output)
        except OSError:
            if backup.exists():
                os.replace(backup, output)
            raise
        return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video', required=True, type=Path)
    p.add_argument('--out', type=Path, default=Path('build/import/intro'))
    p.add_argument('--crop', help='optional ffmpeg width:height:x:y override')
    args = p.parse_args()
    convert(args.video, args.out, tuple(map(int, args.crop.split(':'))) if args.crop else None)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Headless movie checks: native codec, every imported frame, audio and UI.

No frames or recordings are displayed or uploaded by these tests.
"""
import argparse
from array import array
from collections import Counter
import ctypes
import hashlib
import json
import math
from pathlib import Path
import random
import re
import struct
import subprocess
import sys
import tempfile
import wave

import import_intro as imp


def check(condition, text):
    if not condition:
        raise SystemExit('FAIL: ' + text)
    print('PASS: ' + text, flush=True)


def decoder(library):
    decode = ctypes.CDLL(str(library.resolve())).intro_decode
    decode.argtypes = [ctypes.POINTER(ctypes.c_ushort), ctypes.c_uint,
                       ctypes.POINTER(ctypes.c_ushort), ctypes.c_uint]
    decode.restype = ctypes.c_int
    return decode


def apply(decode, payload, previous):
    source = (ctypes.c_ushort * (len(payload)//2)).from_buffer_copy(payload)
    output = (ctypes.c_ushort * len(previous))(*previous)
    check_ok = decode(source, len(source), output, len(output))
    if not check_ok:
        raise ValueError('native decoder rejected a generated frame')
    return array('H', output)


def synthetic(decode):
    rng = random.Random(64)
    for length in (1, 2, 3, 7, imp.LIMIT-1, imp.LIMIT, imp.LIMIT+1, imp.WORDS):
        old = array('H', [rng.randrange(65536) for _ in range(length)])
        cases = [array('H', [0])*length, array('H', [0x1234])*length,
                 old[:], array('H', [rng.randrange(65536) for _ in range(length)])]
        varied = old[:]
        for i in range(0, length, 19):
            varied[i] ^= 0xA5A5
        cases.append(varied)
        for current in cases:
            if apply(decode, imp.encode(current, old), old) != current:
                raise ValueError('codec mismatch at length %d' % length)
    check(True, 'native codec round trips runs, deltas, noise and 14-bit command boundaries')


def synthetic_import(decode):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        video = root/'original-fixture.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
                        '-f','lavfi','-i','testsrc2=size=288x216:rate=30,pad=320:240:16:12:black',
                        '-f','lavfi','-i','sine=frequency=880:sample_rate=44100',
                        '-t','3.1','-c:v','mpeg4','-c:a','aac',str(video)],check=True)
        report = imp.convert(video,root/'import')
        check(report['frames'] == 47 and tuple(report['crop']) == (288,216,16,12),
              'local-video conversion, aspect preservation and audio padding work on original fixtures')
        _, frames, palette = imported(root/'import',decode)
        check(all(palette[frame[y*240]] == palette[frame[y*240+239]] == 0
                  for frame in frames for y in range(160)),
              '4:3 input keeps its proportions with centered black side bars')
        original = (root/'import'/'manifest.json').read_bytes()
        invalid = root/'invalid.mp4'
        invalid.write_bytes(b'original invalid-media fixture')
        try:
            imp.convert(invalid,root/'import')
        except subprocess.CalledProcessError:
            pass
        else:
            raise ValueError('invalid input was accepted')
        check((root/'import'/'manifest.json').read_bytes() == original,
              'failed conversions preserve the last working import')


def imported(directory, decode):
    report = json.loads((directory / 'manifest.json').read_text())
    payload = (directory / 'video.bin').read_bytes()
    offsets = list(struct.unpack('<%dI' % (report['frames']+1), (directory/'offsets.bin').read_bytes()))
    check(offsets == report['offsets'] and offsets[0] == 0 and offsets[-1]*2 == len(payload)
          and all(a < b for a, b in zip(offsets, offsets[1:])), 'movie offsets cover the entire encoded stream')
    pages = [array('H', [0])*imp.WORDS, array('H', [0])*imp.WORDS]
    frames = []
    for i in range(report['frames']):
        data = payload[offsets[i]*2:offsets[i+1]*2]
        pages[i&1] = apply(decode, data, pages[i&1])
        frame = imp.packed(pages[i&1])
        if hashlib.sha256(frame).hexdigest() != report['frame_sha256'][i]:
            raise ValueError('decoded frame %d differs from imported video' % i)
        frames.append(frame)
    check(len(set(report['frame_sha256'])) > min(10, report['frames']//2),
          '%d converted frames decode exactly, including alternating-page history' % len(frames))
    palette = struct.unpack('<256H', (directory / 'palette.bin').read_bytes())
    check(palette[0] == 0 and max(palette) <= 32767, 'valid RGB555 palette with a black border color')
    audio = (directory/'audio.pcm').read_bytes()
    check(len(audio) == report['audio_samples']+128 and len(set(audio)) > 16 and not any(audio[-128:]),
          'movie audio has content and a silent DMA safety tail')
    return report, frames, palette


def fnv(data):
    value = 2166136261
    for byte in data:
        value = ((value ^ byte)*16777619) & 0xFFFFFFFF
    return '%08x' % value


def frame_hashes(frames, palette, replicate):
    rgb = bytearray()
    for c in palette:
        for shift in (0, 5, 10):
            channel = (c >> shift) & 31
            rgb.append((channel << 3) | (channel >> 2 if replicate else 0))
    # Pillow performs the palette expansion in C; the checksum is independent
    # of the GBA decoder and checked against actual mGBA screen output.
    from PIL import Image
    out = []
    for frame in frames:
        im = Image.frombytes('P', (240,160), frame)
        im.putpalette(rgb)
        out.append(fnv(im.convert('RGB').tobytes()))
    return out


def runs(values):
    return [v for i, v in enumerate(values) if i == 0 or v != values[i-1]]


def envelope(samples, rate):
    # Round each absolute boundary, not the block size: 32768 Hz and
    # 13379 Hz are not divisible by 100, so a fixed rounded step drifts.
    out = []
    for i in range(int(len(samples)*100/rate)):
        start, end = round(i*rate/100), round((i+1)*rate/100)
        out.append(math.sqrt(sum(v*v for v in samples[start:end])/(end-start)))
    return out


def audio_check(path, directory, video_start):
    with wave.open(str(path)) as wav:
        rate, channels = wav.getframerate(), wav.getnchannels()
        pcm = array('h', wav.readframes(wav.getnframes()))
    if sys.byteorder != 'little':
        pcm.byteswap()
    actual = envelope(pcm[::channels], rate)
    signed = array('b', (directory/'audio.pcm').read_bytes())
    expected = envelope(signed, 13379)
    # Compare the amplitude envelope across the full clip, allowing the
    # mixer/filter to change individual samples. Search only near video time.
    best = (-1, 0)
    center = round(video_start / 59.7275 * 100)
    for lag in range(max(0,center-15), center+16):
        n = min(len(expected), len(actual)-lag)
        x, y = expected[:n], actual[lag:lag+n]
        if n < len(expected)-3:
            continue
        mx, my = sum(x)/n, sum(y)/n
        xx = sum((v-mx)**2 for v in x)
        yy = sum((v-my)**2 for v in y)
        correlation = sum((a-mx)*(b-my) for a,b in zip(x,y)) / math.sqrt(xx*yy) if xx*yy else 0
        if correlation > best[0]:
            best = (correlation, lag)
    check(best[0] > .9, 'full movie audio matches the source envelope (r=%.3f)' % best[0])
    check(abs(best[1]-center) <= 8, 'audio and picture start within 80 ms (measured %.0f ms)' % ((best[1]-center)*10))


def runtime(args, report, frames, palette):
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    def run(name, keys, count, save=None, audio=False):
        script = out/(name+'.keys')
        script.write_text(keys)
        command = [args.runner,args.rom,'--title-keys','--frames',str(count),'--keys',str(script),
                   '--save-out',str(out/(name+'.sav')),'--video-hash',str(out/(name+'.hash'))]
        if save:
            command += ['--save-in',str(save)]
        if audio:
            command += ['--audio',str(out/(name+'.wav'))]
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        (out/(name+'.log')).write_text(result.stdout)
        (out/(name+'.stderr')).write_text(result.stderr)
        check('intro error' not in result.stdout, name + ' boots without decode errors')
        return result.stdout

    count = report['frames']*report['vblanks_per_frame']+420
    log = run('full', '30 36 S\n', count, audio=True)
    check('intro done' in log and 'intro skipped' not in log and '\nf ' in log,
          'New Game plays the entire movie and enters gameplay')
    rows = [tuple(int(v,16) for v in row) for row in re.findall(r'intro frame ([0-9A-F]+) tick ([0-9A-F]+) late ([0-9A-F]+)',log)]
    check(len(rows) == report['frames'] and all(row == (i,i*4,0) for i,row in enumerate(rows)),
          'all %d frames meet their four-VBlank deadlines with zero late frames' % report['frames'])
    actual = (out/'full.hash').read_text().splitlines()
    actual_runs = runs(actual)
    chosen = None
    for replicate in (False,True):
        expected = frame_hashes(frames,palette,replicate)
        expected_runs = runs(expected)
        for at in range(len(actual_runs)-len(expected_runs)+1):
            if actual_runs[at:at+len(expected_runs)] == expected_runs:
                chosen = expected
                break
        if chosen:
            break
    check(chosen is not None, 'actual GBA framebuffer hashes match the full converted movie in order')
    unique = Counter(chosen)
    anchor = next(i for i,h in enumerate(chosen) if unique[h] == 1)
    video_start = actual.index(chosen[anchor])-anchor*4
    audio_check(out/'full.wav',args.data,video_start)
    log = run('skip', '30 36 S\n100 106 S\n', 500)
    check('intro skipped' in log and 'intro done' not in log and '\nf ' in log,
          'a fresh Start press skips the movie and enters gameplay')
    # The key used to select New Game must never count as the skip press.
    log = run('held', '30 160 S\n', 300)
    check('intro ready' in log and 'intro skipped' not in log and 'intro frame' in log,
          'holding the title Start press does not accidentally skip the intro')
    log = run('continue', '30 36 A\n', 420, out/'full.sav')
    check('game continue' in log and 'intro ready' not in log and '\nf ' in log,
          'Continue enters gameplay directly without replaying the movie')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,default=Path('build/import/intro'))
    p.add_argument('--library',type=Path,default=Path('build/host/intro_codec.so'))
    p.add_argument('--runner')
    p.add_argument('--rom',default='build/demo/sm64demo.gba')
    p.add_argument('--out',type=Path,default=Path('build/intro-check'))
    args = p.parse_args()
    decode = decoder(args.library)
    synthetic(decode)
    if not args.runner:
        synthetic_import(decode)
    if (args.data/'manifest.json').exists():
        report,frames,palette = imported(args.data,decode)
        if args.runner:
            runtime(args,report,frames,palette)
    else:
        print('(no imported intro: synthetic codec checks only)')


if __name__ == '__main__':
    main()

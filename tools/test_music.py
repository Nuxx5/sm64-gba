#!/usr/bin/env python3
"""Checks of the music import without a ROM (make music-check):

1. tools/n64seq.py plays src/test/music/test_seq.s (written in the decomp's
   sequence macros, assembled by binutils) as worked out by hand from
   seqplayer.c: notes, lengths, transposition, calls, loop point.
2. tools/n64audio.py's VADPCM decoder against the N64 SDK's vadpcm_dec
   (decomp tools/sdk-tools/adpcm) on a sample the SDK's vadpcm_enc encoded.
3. tools/n64music.py: the chip arrangement adds up to the loop, and the
   renderer produces the loop's length of audio at the right pitch.

Usage: test_music.py [--decomp sm64]
"""
import argparse
import math
import os
import random
import struct
import subprocess
import sys
import tempfile
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import n64audio  # noqa: E402
import n64music  # noqa: E402
import n64seq  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OK = True


def check(name, ok, detail=""):
    global OK
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, (": " + detail) if detail and not ok else ""))
    OK &= ok


def assemble_seq(decomp, tmp):
    o, out = os.path.join(tmp, "t.o"), os.path.join(tmp, "t.m64")
    subprocess.run(["arm-none-eabi-gcc", "-x", "assembler-with-cpp", "-DVERSION_US", "-I",
                    os.path.join(decomp, "include"), "-c",
                    os.path.join(ROOT, "src", "test", "music", "test_seq.s"), "-o", o], check=True)
    subprocess.run(["arm-none-eabi-objcopy", "-O", "binary", "-j", ".rodata", o, out], check=True)
    return open(out, "rb").read()


def test_sequence(seq):
    notes, loop = n64seq.play(seq)
    got = [(round(n.t, 3), round(n.length, 3), n.chan, n.instr, n.note, n.velocity, n.drum) for n in notes]
    want = [(0.0, 0.5, 0, 3, 39, 100, False), (0.0, 0.5, 1, 127, 12, 64, True),
            (0.5, 0.25, 0, 3, 43, 90, False), (0.75, 0.25, 0, 3, 43, 90, False),
            (1.0, 0.25, 0, 3, 46, 80, False)]
    check("sequence notes as seqplayer.c plays them", got == want, "%r" % got)
    check("sequence loop point", (round(loop[0], 3), round(loop[1], 3)) == (0.0, 2.0), "%r" % (loop,))
    return notes, loop


def test_vadpcm(decomp, tmp):
    adpcm = os.path.join(decomp, "tools", "sdk-tools", "adpcm")
    subprocess.run(["make", "-s", "-C", adpcm, "native"], check=True, capture_output=True)

    def book_for(a1, a2):
        rows = []
        for j in range(2):
            x = [0.0, 0.0]
            x[j] = 1.0
            out = []
            for _ in range(8):
                v = a1 * x[-1] + a2 * x[-2]
                x.append(v)
                out.append(int(round(v * 2048)))
            rows.append(out)
        return rows
    with open(os.path.join(tmp, "book.txt"), "w") as f:
        f.write("2\n2\n")
        for p in (book_for(1.8, -0.85), book_for(1.2, -0.4)):
            for r in p:
                f.write(" ".join(map(str, r)) + "\n")
    random.seed(1)
    n = 3000
    s = [int(9000 * math.sin(i * 0.07) * math.exp(-i / 2500) + 5000 * math.sin(i * 0.23) + random.randint(-1500, 1500))
         for i in range(n)]
    ssnd = struct.pack(">II", 0, 0) + b"".join(struct.pack(">h", max(-32768, min(32767, v))) for v in s)
    e = int(math.floor(math.log2(16000.0)))
    comm = struct.pack(">hIh", 1, n, 16) + struct.pack(">HQ", e + 16383, int(16000.0 / 2 ** e * 2 ** 63))
    body = b"AIFF" + b"COMM" + struct.pack(">I", len(comm)) + comm + b"SSND" + struct.pack(">I", len(ssnd)) + ssnd
    open(os.path.join(tmp, "in.aiff"), "wb").write(b"FORM" + struct.pack(">I", len(body)) + body)
    subprocess.run([os.path.join(adpcm, "vadpcm_enc_native"), "-c", os.path.join(tmp, "book.txt"),
                    os.path.join(tmp, "in.aiff"), os.path.join(tmp, "out.aifc")], check=True)
    raw = subprocess.run([os.path.join(adpcm, "vadpcm_dec_native"), os.path.join(tmp, "out.aifc")],
                         check=True, capture_output=True).stdout
    d = open(os.path.join(tmp, "out.aifc"), "rb").read()
    pos, data, book = 12, None, None
    while pos < len(d):
        cid, size = d[pos:pos + 4], struct.unpack(">I", d[pos + 4:pos + 8])[0]
        chunk = d[pos + 8:pos + 8 + size]
        if cid == b"SSND":
            data = chunk[8:]
        if cid == b"APPL" and b"VADPCMCODES" in chunk:
            i = chunk.index(b"VADPCMCODES") + 11
            _, order, npred = struct.unpack(">hhh", chunk[i:i + 6])
            book = list(struct.unpack(">%dh" % (order * npred * 8), chunk[i + 6:i + 6 + order * npred * 16]))
        pos += 8 + size + (size & 1)
    mine = n64audio.vadpcm_decode(data, book)
    ref = list(struct.unpack(">%dh" % (len(raw) // 2), raw))
    check("VADPCM decoder identical to the SDK's vadpcm_dec (%d samples)" % len(ref), mine == ref)


def test_music(notes, loop):
    voices = n64music.chip(notes, loop)
    fps_loop = int(round(loop[1] * n64music.FPS)) - int(round(loop[0] * n64music.FPS))
    ok = all(sum(d for d, _, _ in ev) + tail == fps_loop for ev, _, tail in voices.values())
    check("chip voices each add up to one loop (%d frames)" % fps_loop, ok)
    Snd = namedtuple("Snd", "sample_addr tuning")
    Inst = namedtuple("Inst", "normal_range_lo normal_range_hi sound_lo sound_med sound_hi envelope release_rate")
    Drum = namedtuple("Drum", "sound envelope release_rate")

    class Bank:
        def instrument(self, b, i):
            return Inst(0, 127, None, Snd(1, 261.63 / 1000.0), None, 100, 8)

        def drum(self, b, i):
            return Drum(Snd(2, 1.0), 101, 20)

        def envelope(self, b, a):
            return [(4, 32000), (0xFFFF, 0)] if a == 100 else [(2, 32000), (30, 0), (0, 0)]

        def sample(self, b, a):
            if a == 1:  # a 32-sample sine: 1000 Hz at tuning 1
                return [int(12000 * math.sin(2 * math.pi * k / 32)) for k in range(32)], (0, 32, -1)
            return [0] * 100, (0, 0, 0)
    data, ls = n64music.render(notes, loop, Bank(), [0])
    rate = n64music.PCM_RATE
    check("rendered length = loop + padding", len(data) == int(loop[1] * rate) + 2048 and ls == 0)
    seg = [b - 256 if b >= 128 else b for b in data[int(0.1 * rate):int(0.4 * rate)]]
    zc = sum(1 for a, b in zip(seg, seg[1:]) if a < 0 <= b) / 0.3
    check("rendered C4 at %.0f Hz (261.6)" % zc, abs(zc - 261.6) < 6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decomp", default="sm64")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        notes, loop = test_sequence(assemble_seq(args.decomp, tmp))
        test_vadpcm(args.decomp, tmp)
        test_music(notes, loop)
    print("PASS: music checks" if OK else "FAIL: music checks")
    sys.exit(0 if OK else 1)


if __name__ == "__main__":
    main()

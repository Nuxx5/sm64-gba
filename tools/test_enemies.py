#!/usr/bin/env python3
"""Original fixtures for the baker; optional real-art and live VRAM checks."""
import argparse
import re
import struct
import subprocess
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import bake_enemies as be


class BakerChecks(unittest.TestCase):
    def test_animation_rotation_convention(self):
        v = be.vector([0, 1, 0], be.xyz([0x4000, 0, 0]))
        for got, want in zip(v, [0, 0, 1]):
            self.assertAlmostEqual(got, want)

    def test_billboard_cancels_parent_and_camera_rotation(self):
        actor = be.Actor.__new__(be.Actor)
        verts = [dict(pos=p, c=[255] * 4, uv=[0, 0]) for p in ([0, 0, 0], [4, 0, 0], [0, 4, 0])]
        actor.syms = SimpleNamespace(gfx={"test": [("gsSPClearGeometryMode", "G_LIGHTING"),
                            ("gsSPVertex", "verts, 3, 0"), ("gsSP1Triangle", "0, 1, 2, 0")]}, vtx={"verts": verts})
        actor.nodes = [("GEO_SCALE", ["0", "16384"], [
            ("GEO_ANIMATED_PART", ["LAYER_OPAQUE", "0", "0", "0", "NULL"], [
                ("GEO_BILLBOARD", [], [("GEO_DISPLAY_LIST", ["LAYER_OPAQUE", "test"], [])])])])]
        actor.animations = [dict(index=[1, 2, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0],
                                values=[0, 0x4000, 10], flags=0, divisor=0)]
        for view in range(8):
            triangle = actor.pose(0, 0, 0, be.view_matrix(view))[0][0]
            a, b, c = [v[0] for v in triangle]
            for got, want in zip([b[i] - a[i] for i in range(3)], [1, 0, 0]):
                self.assertAlmostEqual(got, want)
            for got, want in zip([c[i] - a[i] for i in range(3)], [0, 1, 0]):
                self.assertAlmostEqual(got, want)

    def test_alpha_test_preserves_geometry_behind_holes(self):
        state = dict(cull=False, texture=None, combine="G_CC_SHADE", env_alpha=255)
        points = [[-1, -1, 0], [1, -1, 0], [0, 1, 0]]
        red = [([*p], [255, 0, 0], [0, 0]) for p in points]
        front = [([p[0], p[1], 1], [255] * 3, [0, 0]) for p in points]
        textured = dict(state, texture="test", combine="G_CC_DECALRGBA", clamp_s=True, clamp_t=True)
        assets = SimpleNamespace(texture=lambda _: (1, 1, [(0, 255, 0, 0)]))
        image = be.render([(red, state, "LAYER_OPAQUE"), (front, textured, "LAYER_ALPHA")], assets, 8, 2, 0)
        self.assertEqual(image.getpixel((4, 4)), (255, 0, 0, 255))
        assets.texture = lambda _: (1, 1, [(0, 255, 0, 255)])
        image = be.render([(front, textured, "LAYER_ALPHA"), (red, state, "LAYER_OPAQUE")], assets, 8, 2, 0)
        self.assertEqual(image.getpixel((4, 4)), (0, 255, 0, 255))


def fnv(data):
    value = 2166136261
    for b in data:
        value = ((value ^ b) * 16777619) & 0xFFFFFFFF
    return value


def read_art(directory):
    source = (directory / "enemy_art.c").read_text()
    result = {}
    for name, words in (("Small", 64), ("Large", 256)):
        match = re.search(r"gImpEnemy%s\[3\]\[128\]\[\d+\] = \{(.*?)\n\};" % name, source, re.S)
        values = list(map(int, re.findall(r"\d+", match[1])))
        if len(values) != 384 * words:
            raise ValueError("wrong tile count for " + name)
        rows = [struct.pack("<%dH" % words, *values[i:i + words]) for i in range(0, len(values), words)]
        if any(not any(row) for row in rows):
            raise ValueError("empty enemy sprite")
        size = 16 if name == "Small" else 32
        for row in rows:
            # No opaque pixels may touch the canvas boundary: that would
            # indicate a model/pose clipped during baking.
            def pixel(x, y):
                offset = ((y // 8) * (size // 8) + x // 8) * 32 + (y % 8) * 4 + (x % 8) // 2
                return (row[offset] >> (4 * (x % 2))) & 15
            if any(pixel(x, 0) or pixel(x, size - 1) or pixel(0, x) or pixel(size - 1, x) for x in range(size)):
                raise ValueError("baked enemy touches the sprite boundary")
        result[name] = rows
    for ai in range(3):
        rows = result["Large"][ai * 128:(ai + 1) * 128]
        if len(set(rows[:8])) < 3:
            raise ValueError("enemy animation phases did not change the sprite")
        if len({rows[v * 8] for v in range(8)}) < 4:
            raise ValueError("enemy view directions did not change the sprite")
        if all(rows[v * 8] == rows[64 + v * 8] for v in range(8)):
            raise ValueError("enemy eye states did not change the sprite")
    pal = list(map(int, re.search(r"gImpEnemyPal\[15\] = \{(.*?)\};", source)[1].split(",")))
    if len(pal) != 15 or any(c < 0 or c > 32767 for c in pal):
        raise ValueError("invalid enemy palette")
    result["Palette"] = struct.pack("<15H", *pal)
    return result


def runtime_check(args, art):
    valid = {16: {fnv(row) for row in art["Small"]}, 32: {fnv(row) for row in art["Large"]}}
    by_animation = {size: [{fnv(row) for row in art[name][i * 128:(i + 1) * 128]} for i in range(3)]
                    for size, name in ((16, "Small"), (32, "Large"))}
    palette = fnv(art["Palette"])
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "sprites.txt"
        reports = []
        for frames, option, keys in ((1800, "--keys-game", "demo/keys/goomba_hit.keys"),
                                      (1500, "--keys", "demo/keys/physics_check.keys")):
            subprocess.run([args.runner, args.rom, "--frames", str(frames), option, keys,
                            "--sprite-report", str(report)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            reports.append(report.read_text().splitlines())
        observations, hashes, sizes, slots, animations = 0, set(), set(), defaultdict(list), set()
        for route, line in ((i, line) for i, lines in enumerate(reports) for line in lines):
            frame, slot, box, tile, matrix, pa, pd, pixel_hash, pal_hash = line.split()
            frame, slot, box, tile, matrix = map(int, (frame, slot, box, tile, matrix))
            if int(pixel_hash, 16) not in valid[box] or int(pal_hash, 16) != palette:
                raise ValueError("OAM sprite has corrupted/unexpected imported tile or palette data")
            allowed = (768, 784) if box == 32 else tuple(range(800, 832, 4)) + tuple(range(576, 592, 4))
            if tile not in allowed or matrix != slot - 36 or not int(pa, 16) or not int(pd, 16):
                raise ValueError("enemy sprite overlaps reserved VRAM or uses an invalid affine matrix")
            for old_start, old_end in slots[route, frame]:
                if tile < old_end and tile + box * box // 64 > old_start:
                    raise ValueError("visible enemies share conflicting tile slots")
            slots[route, frame].append((tile, tile + box * box // 64))
            observations += 1
            sizes.add(box)
            hashes.add(pixel_hash)
            animations.update(i for i, hashes_for_anim in enumerate(by_animation[box]) if int(pixel_hash, 16) in hashes_for_anim)
        if observations < 50 or len(hashes) < 10 or sizes != {16, 32} or not {0, 1} <= animations:
            raise ValueError("runtime coverage: %d observations, %d images, sizes %s; "
                             "need both sprite sizes and animated imported art" % (observations, len(hashes), sorted(sizes)))
        print("PASS: %d live enemy sprites, %d tile images, Goomba/Bob-omb, 16/32px art, palettes and VRAM slots verified" %
              (observations, len(hashes)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--art", default="build/import")
    parser.add_argument("--runner")
    parser.add_argument("--rom", default="build/demo/sm64demo.gba")
    args = parser.parse_args()
    if not unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BakerChecks)).wasSuccessful():
        raise SystemExit(1)
    directory = Path(args.art)
    if (directory / "enemy_art.c").exists():
        art = read_art(directory)
        print("PASS: 384 real model poses; animated phases, views and eye states verified")
        if args.runner:
            runtime_check(args, art)
    else:
        print("(no imported enemy art: skipping real model and live VRAM checks)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Asset library checks; optional --library verifies a complete ROM import."""
import argparse
import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import asset_library as al


class TileChecks(unittest.TestCase):
    def test_tile_order_transparency_and_padding(self):
        # Cross a horizontal and vertical tile boundary with odd dimensions.
        image = Image.new("RGBA", (11, 9), (255, 0, 0, 255))
        image.putpixel((0, 0), (0, 255, 0, 255))
        image.putpixel((1, 0), (0, 0, 255, 0))
        image.putpixel((8, 8), (0, 0, 255, 255))
        palette, tiles = al.gba_texture(image)
        colors = struct.unpack("<16H", palette)
        self.assertEqual(len(tiles), 4 * 32)
        for y in range(16):
            for x in range(16):
                offset = ((y // 8) * 2 + x // 8) * 32 + (y % 8) * 4 + (x % 8) // 2
                index = (tiles[offset] >> (4 * (x % 2))) & 15
                if x >= 11 or y >= 9 or (x, y) == (1, 0):
                    self.assertEqual(index, 0, (x, y))
                else:
                    r, g, b, _ = image.getpixel((x, y))
                    self.assertNotEqual(index, 0)
                    self.assertEqual(colors[index], (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10))

    def test_fully_transparent_texture(self):
        palette, tiles = al.gba_texture(Image.new("RGBA", (8, 8)))
        self.assertEqual(len(palette), 32)
        self.assertEqual(tiles, bytes(32))

    def test_many_colors_fit_hardware_palette(self):
        image = Image.new("RGBA", (16, 16))
        image.putdata([(i, (i * 17) % 256, (i * 31) % 256, 255) for i in range(256)])
        palette, tiles = al.gba_texture(image)
        self.assertEqual(len(palette), 32)
        self.assertTrue(all((b & 15) != 0 and (b >> 4) != 0 for b in tiles))

    def test_integrity_detects_corrupted_or_missing_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = root / "test.bin"
            asset.write_bytes(b"original")
            entry = al.file_entry(root, "test.bin", "binary_data", origin="rom")
            manifest = dict(files=[entry], extracted_asset_count=1, categories={"binary_data": 1})
            (root / "manifest.json").write_text(json.dumps(manifest))
            al.verify_library(root)
            asset.write_bytes(b"modified")
            with self.assertRaisesRegex(ValueError, "checksum"):
                al.verify_library(root)
            asset.unlink()
            with self.assertRaises(FileNotFoundError):
                al.verify_library(root)

    def test_failed_extraction_preserves_previous_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decomp, out = root / "decomp", root / "out"
            decomp.mkdir()
            (decomp / "tools").mkdir()
            (decomp / "sound").mkdir()
            (decomp / "assets.json").write_text("{}")
            for name in ("extract_assets.py", "util.mk", "sm64.us.sha1"):
                (decomp / name).write_text("fixture")
            old = out / "library" / "previous.bin"
            old.parent.mkdir(parents=True)
            old.write_bytes(b"previous complete import")
            with mock.patch.object(al.subprocess, "check_output", return_value="revision\n"), \
                 mock.patch.object(al.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
                with self.assertRaisesRegex(RuntimeError, "extraction failed"):
                    al.import_library(b"fixture ROM", "us", "fixture sha", decomp, out)
            self.assertEqual(old.read_bytes(), b"previous complete import")
            self.assertEqual(list(out.glob(".asset-import-*")), [])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--library")
    parser.add_argument("--decomp", default="sm64")
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TileChecks)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        raise SystemExit(1)
    if args.library:
        manifest = al.verify_library(args.library)
        asset_map = json.loads((Path(args.decomp) / "assets.json").read_text())
        expected = set(al.asset_paths(asset_map, manifest["rom_version"]))
        got = {e["path"] for e in manifest["files"] if e["origin"] == "rom"}
        if got != expected:
            raise SystemExit("FAIL: ROM assets do not match the decomp's complete asset map")
        pngs = {p for p in got if p.endswith(".png")}
        converted = {t["source"] for t in manifest["gba_textures"]}
        if pngs != converted:
            raise SystemExit("FAIL: some images have no GBA conversion")
        root = Path(args.library)
        for texture in manifest["gba_textures"]:
            if (root / texture["palette"]).stat().st_size != 32:
                raise SystemExit("FAIL: GBA palette must contain 16 RGB555 colors")
            if (root / texture["tiles"]).stat().st_size != texture["tile_columns"] * texture["tile_rows"] * 32:
                raise SystemExit("FAIL: GBA tile data has the wrong size")
        print("PASS: all %d ROM assets and %d GBA textures verified" % (len(got), len(pngs)))
    else:
        print("(no --library: skipping full ROM library verification)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Extract the complete ROM asset library without modifying the decomp.

The pinned decomp's extractor handles every texture layout and sound sample.
Run it in a disposable workspace, then publish only verified assets and source
definitions into build/import/library. This is an offline library, not a claim
that the GBA runtime implements every object's behavior or draws every model.
"""
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path


def category(path):
    if path.startswith("textures/skyboxes/") or path.startswith("levels/ending/cake"):
        return "backgrounds"
    if path.startswith("sound/samples/"):
        return "sound_samples"
    if path.endswith(".m64"):
        return "music_sequences"
    if path.endswith(".png"):
        return "actor_textures" if path.startswith("actors/") else "textures"
    return "binary_data"


def asset_paths(asset_map, version):
    return sorted(path for path, meta in asset_map.items()
                  if not path.startswith("@") and version in meta[-1])


def file_entry(root, path, kind, **metadata):
    data = (root / path).read_bytes()
    if not data:
        raise ValueError("empty imported asset: %s" % path)
    return dict(path=path, category=kind, bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(), **metadata)


def gba_texture(image):
    """RGB555 palette + 4bpp tiles, index zero transparent, in GBA tile order.

    Keep source dimensions; pad the right/bottom edges to whole 8x8 tiles.
    Large images are tile grids for streaming, not single hardware sprites.
    """
    from PIL import Image
    image = image.convert("RGBA")
    w, h = image.size
    pixels = list(image.getdata())
    opaque = next((p[:3] for p in pixels if p[3] >= 128), (0, 0, 0))
    rgb = Image.new("RGB", (w, h))
    rgb.putdata([p[:3] if p[3] >= 128 else opaque for p in pixels])
    indexed = rgb.quantize(colors=15, method=Image.Quantize.MEDIANCUT)
    colors = indexed.getpalette()
    colors += [0] * (45 - len(colors))
    palette = [0]
    for i in range(15):
        r, g, b = colors[i * 3:i * 3 + 3]
        palette.append((r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10))
    indices = list(indexed.getdata())
    indices = [i + 1 if p[3] >= 128 else 0 for i, p in zip(indices, pixels)]
    tiles = bytearray()
    for ty in range(0, h, 8):
        for tx in range(0, w, 8):
            for y in range(8):
                for x in range(0, 8, 2):
                    a = indices[(ty + y) * w + tx + x] if ty + y < h and tx + x < w else 0
                    b = indices[(ty + y) * w + tx + x + 1] if ty + y < h and tx + x + 1 < w else 0
                    tiles.append(a | (b << 4))
    return struct.pack("<16H", *palette), bytes(tiles)


def convert_textures(library, paths):
    from PIL import Image
    entries, textures = [], []
    for path in paths:
        if not path.endswith(".png"):
            continue
        with Image.open(library / path) as image:
            width, height = image.size
            palette, tiles = gba_texture(image)
        base = "gba/" + path[:-4]
        pal_path, tile_path = base + ".pal", base + ".4bpp"
        for dest, data, kind in ((pal_path, palette, "gba_palettes"),
                                 (tile_path, tiles, "gba_texture_tiles")):
            target = library / dest
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            entries.append(file_entry(library, dest, kind, origin="converted", source=path))
        textures.append(dict(source=path, width=width, height=height,
                             tile_columns=(width + 7) // 8, tile_rows=(height + 7) // 8,
                             palette=pal_path, tiles=tile_path))
    return entries, textures


def verify_library(path):
    root = Path(path)
    manifest = json.loads((root / "manifest.json").read_text())
    entries = manifest["files"]
    names = [entry["path"] for entry in entries]
    if len(names) != len(set(names)):
        raise ValueError("duplicate paths in library manifest")
    for entry in entries:
        rel = Path(entry["path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("unsafe library path: %s" % rel)
        got = file_entry(root, entry["path"], entry["category"])
        if any(got[k] != entry[k] for k in ("bytes", "sha256")):
            raise ValueError("library checksum mismatch: %s" % rel)
    if sum(e["origin"] == "rom" for e in entries) != manifest["extracted_asset_count"]:
        raise ValueError("ROM asset count mismatch")
    if dict(Counter(e["category"] for e in entries)) != manifest["categories"]:
        raise ValueError("category counts do not match library files")
    return manifest


def copy_sources(decomp, library):
    """Preserve meshes, geo layouts, animations, collision and object scripts.

    These are the decomp's source definitions, not invented ROM offsets or
    already converted GBA objects. Textures and audio remain ROM-derived.
    """
    entries = []
    roots = ("actors", "levels", "assets", "data", "src/game/behaviors", "sound")
    files = set()
    for rel in roots:
        files.update(p for p in (decomp / rel).rglob("*")
                     if p.is_file() and p.suffix in (".c", ".h", ".s", ".json"))
    files.update(decomp / "include" / name for name in
                 ("model_ids.h", "macro_presets.h", "special_presets.h", "behavior_data.h"))
    for source in sorted(files):
        rel = source.relative_to(decomp).as_posix()
        dest = "sources/" + rel
        target = library / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        kind = "source_definitions"
        if rel.startswith("src/game/behaviors/") or rel == "data/behavior_data.c":
            kind = "object_behaviors"
        elif "/anims/" in rel:
            kind = "animations"
        elif source.name.startswith("collision"):
            kind = "collision"
        elif rel.startswith(("actors/", "levels/")):
            kind = "models_and_layouts"
        entries.append(file_entry(library, dest, kind, origin="decomp"))
    return entries


def import_library(rom, version, sha, decomp, out):
    decomp, out = Path(decomp).resolve(), Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    asset_map = json.loads((decomp / "assets.json").read_text())
    expected = asset_paths(asset_map, version)
    expected_set = set(expected)
    revision = subprocess.check_output(
        ["git", "-C", str(decomp), "rev-parse", "HEAD"], text=True).strip()
    # Keep the previous complete library if extraction or verification fails.
    with tempfile.TemporaryDirectory(prefix=".asset-import-", dir=out) as tmp:
        stage = Path(tmp)
        work = stage / "extract"
        work.mkdir()
        for name in ("extract_assets.py", "assets.json", "util.mk", "sm64.%s.sha1" % version):
            shutil.copyfile(decomp / name, work / name)
        shutil.copytree(decomp / "tools", work / "tools",
                        ignore=shutil.ignore_patterns("__pycache__", ".git"))
        shutil.copytree(decomp / "sound", work / "sound")
        rom_path = work / ("baserom.%s.z64" % version)
        rom_path.write_bytes(rom)
        log_path = out / "extraction.log"
        print("library: extracting all %d assets for %s (log: %s)" %
              (len(expected), version.upper(), log_path), flush=True)
        with log_path.open("w") as log:
            result = subprocess.run([sys.executable, "extract_assets.py", version],
                                    cwd=work, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            tail = "\n".join(log_path.read_text(errors="replace").splitlines()[-20:])
            raise RuntimeError("full asset extraction failed; see %s\n%s" % (log_path, tail))
        library = stage / "library"
        library.mkdir()
        entries = []
        for path in expected:
            dest = library / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(work / path, dest)
            meta = asset_map[path]
            entries.append(file_entry(library, path, category(path), origin="rom",
                                      rom_location=meta[-1][version], encoded_bytes=meta[-2]))
        sources = copy_sources(decomp, library)
        entries.extend(sources)
        converted, textures = convert_textures(library, expected)
        entries.extend(converted)
        groups = {}
        for entry in entries:
            rel = entry["path"].removeprefix("sources/")
            parts = rel.split("/")
            if parts[0] in ("actors", "levels"):
                groups.setdefault(parts[0] + "/" + parts[1], []).append(entry["path"])
        counts = dict(sorted(Counter(e["category"] for e in entries).items()))
        manifest = dict(schema_version=1, rom_version=version, rom_sha1=sha,
                        decomp_revision=revision, extracted_asset_count=len(expected),
                        categories=counts, files=entries, groups=groups, gba_textures=textures,
                        unavailable_in_version=sorted(path for path in asset_map
                            if not path.startswith("@") and path not in expected_set),
                        runtime_note="Offline asset library. The demo currently uses Mario, four levels, "
                        "coin/tree/meter art and three music tracks. Other models and object behaviors "
                        "require GBA conversion and engine support; extraction does not enable them.")
        (library / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        verify_library(library)
        previous = out / ".library-previous"
        if previous.exists():
            raise RuntimeError("previous library backup exists: %s; inspect it before retrying" % previous)
        target = out / "library"
        if target.exists():
            target.rename(previous)
        try:
            library.rename(target)
        except OSError:
            if previous.exists():
                previous.rename(target)
            raise
        if previous.exists():
            shutil.rmtree(previous)
    print("library: %d ROM assets, %d source definitions, %d GBA textures" %
          (len(expected), len(sources), len(textures)))
    for kind, count in counts.items():
        print("  %s: %d" % (kind, count))
    return manifest

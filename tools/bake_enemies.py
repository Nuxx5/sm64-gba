#!/usr/bin/env python3
"""Bake the decomp's animated enemy models with textures from YOUR ROM.

No game art is stored here. Generated tiles go to ignored build/import/.
Geometry, animation channels, geo scale/switches and billboard nodes follow
the original Goomba and black Bob-omb layouts. Lighting and the orthographic
sprite camera are offline approximations; gameplay is untouched.
"""
import argparse
import json
import math
import re
from pathlib import Path

from PIL import Image

import n64gfx as gfx

VIEWS, PHASES, VARIANTS = 8, 8, 2
PITCH = math.radians(15)
IDENTITY = [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]


def pixels(image):
    # Pillow 10 on the toolchain and Pillow 13+ in newer hosts.
    return image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()


def mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def vector(v, r):
    return [sum(v[k] * r[k][j] for k in range(3)) for j in range(3)]


def xyz(angles):
    x, y, z = [v * math.tau / 65536 for v in angles]
    sx, cx, sy, cy, sz, cz = math.sin(x), math.cos(x), math.sin(y), math.cos(y), math.sin(z), math.cos(z)
    return [[cy * cz, cy * sz, -sy],
            [sx * sy * cz - cx * sz, sx * sy * sz + cx * cz, sx * cy],
            [cx * sy * cz + sx * sz, cx * sy * sz - sx * cz, cx * cy]]


def view_matrix(view):
    y = view * math.tau / VIEWS
    sy, cy, sp, cp = math.sin(y), math.cos(y), math.sin(PITCH), math.cos(PITCH)
    return [[cy, -sy * sp, sy * cp], [0, cp, sp], [-sy, -cy * sp, cy * cp]]


def read_animations(root, actor):
    directory = Path(root) / "actors" / actor / "anims"
    src = "\n".join(p.read_text() for p in sorted(directory.glob("anim_*.inc.c")))
    arrays = {}
    for m in re.finditer(r"(?:s16|u16)\s+(\w+)\[\]\s*=\s*\{(.*?)\};", src, re.S):
        arrays[m[1]] = [gfx.num(v) for v in re.findall(gfx.NUM, m[2])]
    definitions = {}
    for m in re.finditer(r"struct Animation\s+(\w+)\s*=\s*\{(.*?)\};", src, re.S):
        fields = gfx.split_args(m[2])
        definitions[m[1]] = dict(flags=gfx.num(fields[0]), divisor=gfx.num(fields[1]),
                                 start=gfx.num(fields[2]), loop=gfx.num(fields[3]), length=gfx.num(fields[4]),
                                 values=arrays[fields[6]], index=arrays[fields[7]])
    names = re.findall(r"&(\w+)", (directory / "table.inc.c").read_text())
    return [definitions[name] for name in names]


class Actor:
    def __init__(self, root, name, layout):
        self.syms = gfx.Symbols(str(root))
        self.syms.load("actors/%s/model.inc.c" % name)
        layouts = gfx.parse_geo((Path(root) / "actors" / name / "geo.inc.c").read_text())
        self.nodes = gfx.geo_tree(layouts, layout)
        self.animations = read_animations(root, name)

    def pose(self, animation, frame, variant, view):
        anim = self.animations[animation]
        cursor, bones = 0, 0
        triangles, state = [], gfx.State()

        def channel():
            nonlocal cursor
            count, offset = anim["index"][cursor:cursor + 2]
            cursor += 2
            value = anim["values"][offset + min(max(0, frame), count - 1)]
            return value - 65536 if value >= 32768 else value

        def walk(nodes, rotation, translation):
            nonlocal bones
            for cmd, args, kids in nodes:
                r, t = rotation, translation
                if cmd == "GEO_SCALE":
                    scale = gfx.num(args[1]) / 65536
                    r = [[v * scale for v in row] for row in r]
                elif cmd == "GEO_ANIMATED_PART":
                    offset = [gfx.num(v) for v in args[1:4]]
                    if bones == 0:
                        trans = [channel() for _ in range(3)]
                        if anim["flags"] & 0x40:
                            trans = [0, 0, 0]
                        elif anim["flags"] & 0x08:  # horizontal translation disabled
                            trans[0] = trans[2] = 0
                        elif anim["flags"] & 0x10:  # vertical translation disabled
                            trans[1] = 0
                        # Both imported actors have animYTransDivisor == 0.
                        if anim["divisor"]:
                            raise ValueError("enemy animation translation divisor needs a runtime scale")
                        offset = [a + b for a, b in zip(offset, trans)]
                    bones += 1
                    local = xyz([channel() for _ in range(3)])
                    shift = vector(offset, r)
                    t = [a + b for a, b in zip(t, shift)]
                    r = mul(local, r)
                    if args[4] != "NULL":
                        emit_dl(args[4], args[0], r, t)
                elif cmd == "GEO_BILLBOARD":
                    # Billboard basis is identity in camera space, preserving
                    # world translation and the geo's uniform scale.
                    scale = math.sqrt(sum(v * v for v in r[0]))
                    r = [[view[j][i] * scale for j in range(3)] for i in range(3)]
                elif cmd == "GEO_SWITCH_CASE":
                    walk([kids[min(variant, len(kids) - 1)]], r, t)
                    continue
                elif cmd == "GEO_DISPLAY_LIST":
                    emit_dl(args[1], args[0], r, t)
                elif cmd not in ("GEO_SHADOW", "GEO_NODE_START"):
                    raise ValueError("unsupported enemy geo command " + cmd)
                walk(kids, r, t)

        def emit_dl(name, layer, rotation, translation):
            def emit(tri):
                vertices = []
                for v in tri["v"]:
                    world = [a + b for a, b in zip(vector(v["pos"], rotation), translation)]
                    p = vector(world, view)
                    st = tri["state"]
                    if st["lighting"]:
                        light = st["light"]
                        if light is None:
                            raise ValueError("enemy lit triangle has no light: " + name)
                        normal = [c - 256 if c >= 128 else c for c in v["c"][:3]]
                        normal = vector(vector(normal, rotation), view)
                        length = math.sqrt(sum(c * c for c in normal)) or 1
                        lit = max(0, sum(a * b for a, b in zip(normal, (.4, .82, .41))) / length)
                        shade = [min(255, light["amb"][i] + light["col"][i] * lit) for i in range(3)]
                    else:
                        shade = v["c"][:3]
                    uv = [v["uv"][i] * st["tex_scale"][i] / 32 for i in range(2)]
                    vertices.append((p, shade, uv))
                triangles.append((vertices, tri["state"], layer))
            gfx.run_dl(self.syms, name, state, emit, layer)

        walk(self.nodes, IDENTITY, [0., 0., 0.])
        if cursor != len(anim["index"]):
            raise ValueError("enemy skeleton/animation channel mismatch: %d/%d" % (cursor, len(anim["index"])))
        return triangles


def render(triangles, assets, size, span, center):
    """Orthographic z-buffer with alpha test, Gouraud light and texture UVs."""
    pixels, depth = [(0, 0, 0, 0)] * (size * size), [-math.inf] * (size * size)
    for vertices, st, layer in triangles:
        p = [[size * (.5 + v[0][0] / span), size * (.5 - (v[0][1] - center) / span), v[0][2]] for v in vertices]
        (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = p
        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denom) < 1e-8 or st["cull"] and denom >= 0:
            continue
        tex = assets.texture(st["texture"]) if st["texture"] else None
        if st["texture"] and st["texture"].startswith("?"):
            raise ValueError("unresolved enemy texture " + st["texture"])
        comb = st["combine"]
        for y in range(max(0, int(min(y0, y1, y2))), min(size, math.ceil(max(y0, y1, y2)))):
            for x in range(max(0, int(min(x0, x1, x2))), min(size, math.ceil(max(x0, x1, x2)))):
                a = ((y1 - y2) * (x + .5 - x2) + (x2 - x1) * (y + .5 - y2)) / denom
                b = ((y2 - y0) * (x + .5 - x2) + (x0 - x2) * (y + .5 - y2)) / denom
                c = 1 - a - b
                if min(a, b, c) < -1e-8:
                    continue
                z = a * z0 + b * z1 + c * z2
                at = y * size + x
                if z < depth[at] - 1e-5:
                    continue
                weights = (a, b, c)
                shade = [sum(weights[j] * vertices[j][1][i] for j in range(3)) for i in range(3)]
                color, alpha = shade, 255
                if tex and ("SHADE" not in comb or "MODULATE" in comb or "BLEND" in comb):
                    uv = [sum(weights[j] * vertices[j][2][i] for j in range(3)) for i in range(2)]
                    w, h, data = tex
                    u, v = math.floor(uv[0]), math.floor(uv[1])
                    u = max(0, min(w - 1, u)) if st["clamp_s"] else u % w
                    v = max(0, min(h - 1, v)) if st["clamp_t"] else v % h
                    tc = data[v * w + u]
                    if "DECAL" in comb:
                        color, alpha = tc[:3], tc[3]
                    elif "BLEND" in comb:
                        color = [shade[i] + (tc[i] - shade[i]) * tc[3] / 255 for i in range(3)]
                    else:
                        color = [shade[i] * tc[i] / 255 for i in range(3)]
                        if "RGBA" in comb or "IA" in comb or layer == "LAYER_ALPHA":
                            alpha = tc[3]
                if alpha * st["env_alpha"] / 255 < 128:
                    continue
                pixels[at] = tuple(max(0, min(255, round(v))) for v in color) + (255,)
                depth[at] = z
    image = Image.new("RGBA", (size, size))
    image.putdata(pixels)
    return image


def tiles(indices, size):
    out = []
    for ty in range(0, size, 8):
        for tx in range(0, size, 8):
            for y in range(8):
                for x in range(0, 8, 4):
                    out.append(sum(indices[(ty + y) * size + tx + x + k] << (4 * k) for k in range(4)))
    return out


def bake(assets, root, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    actors = [Actor(root, "goomba", "goomba_geo"), Actor(root, "bobomb", "black_bobomb_geo")]
    animations = [(actors[0], 0), (actors[1], 0), (actors[1], 1)]
    bounds, sizes, centers, texture_paths = [], [], [], set()
    for actor in actors:
        xs, ys = [], []
        for ai, anim in enumerate(actor.animations):
            for variant in range(VARIANTS):
                for view in range(VIEWS):
                    for phase in range(PHASES):
                        frame = phase * anim["length"] // PHASES
                        for triangle, state, _ in actor.pose(ai, frame, variant, view_matrix(view)):
                            xs.extend(v[0][0] for v in triangle)
                            ys.extend(v[0][1] for v in triangle)
                            if state["texture"]:
                                texture_paths.add(state["texture"])
        center = (min(ys) + max(ys)) / 2
        span = math.ceil(max(max(xs) - min(xs), max(ys) - min(ys)) * 1.08)
        bounds.append((span, center))
        sizes.append(span)
        centers.append(round(center / math.cos(PITCH)))
    images = []
    lengths = []
    for actor, ai in animations:
        kind = actors.index(actor)
        span, center = bounds[kind]
        anim = actor.animations[ai]
        if not 0 < anim["length"] <= 30:
            raise ValueError("enemy animation length exceeds runtime phase table")
        lengths.append(anim["length"])
        for variant in range(VARIANTS):
            for view in range(VIEWS):
                for phase in range(PHASES):
                    frame = phase * anim["length"] // PHASES
                    tri = actor.pose(ai, frame, variant, view_matrix(view))
                    image = render(tri, assets, 64, span, center)
                    if image.getbbox() is None:
                        raise ValueError("empty baked enemy sprite")
                    images.append(image)
    # One shared palette for all views, states and animation phases. Reserve
    # index zero for transparency; transparent RGB must not bias quantization.
    sheet = Image.new("RGB", (64, 64 * len(images)))
    for i, image in enumerate(images):
        rgb = Image.new("RGB", image.size)
        data = list(pixels(image))
        opaque = next(p[:3] for p in data if p[3])
        rgb.putdata([p[:3] if p[3] else opaque for p in data])
        sheet.paste(rgb, (0, i * 64))
    palette_image = sheet.quantize(colors=15, method=Image.Quantize.MEDIANCUT)
    palette = palette_image.getpalette()[:45]
    palette += [0] * (45 - len(palette))
    fixed = Image.new("P", (1, 1))
    fixed.putpalette(palette + [0] * (768 - len(palette)))
    converted = {16: [], 32: []}
    coverage = []
    for image in images:
        coverage.append(sum(p[3] != 0 for p in pixels(image)))
        for size in converted:
            small = image.resize((size, size), Image.Resampling.BOX)
            rgb = small.convert("RGB").quantize(palette=fixed, dither=Image.Dither.NONE)
            # Fixed palette contains black padding entries too. Map them to
            # the closest of the actual fifteen colors, then shift by one.
            colors = [tuple(palette[i:i + 3]) for i in range(0, 45, 3)]
            indices = []
            for color, rgba in zip(pixels(rgb), pixels(small)):
                if rgba[3] < 128:
                    indices.append(0)
                else:
                    if color >= 15:
                        color = min(range(15), key=lambda i: sum(c * c for c in colors[i]))
                    indices.append(color + 1)
            converted[size].append(tiles(indices, size))
    path = out / "enemy_art.c"
    with path.open("w") as f:
        f.write('/* Generated from your ROM and the pinned decomp; keep local. */\n#include "enemy_art.h"\n')
        f.write("const unsigned short gImpEnemyPal[15] = {%s};\n" % ",".join(
            str((palette[i] >> 3) | ((palette[i + 1] >> 3) << 5) | ((palette[i + 2] >> 3) << 10)) for i in range(0, 45, 3)))
        f.write("const unsigned short gImpEnemySize[2] = {%s};\n" % ",".join(map(str, sizes)))
        f.write("const short gImpEnemyCenter[2] = {%s};\n" % ",".join(map(str, centers)))
        f.write("const unsigned char gImpEnemyLength[3] = {%s};\n" % ",".join(map(str, lengths)))
        f.write("const unsigned char gImpEnemyPhase[3][30] = {\n")
        for length in lengths:
            f.write("{%s},\n" % ",".join(str(min(i, length - 1) * PHASES // length) for i in range(30)))
        f.write("};\n")
        for size, name in ((16, "Small"), (32, "Large")):
            f.write("const unsigned short gImpEnemy%s[3][128][%d] = {\n" % (name, size * size // 4))
            for ai in range(3):
                f.write("{\n")
                for row in converted[size][ai * 128:(ai + 1) * 128]:
                    f.write("{%s},\n" % ",".join(map(str, row)))
                f.write("},\n")
            f.write("};\n")
    report = dict(views=VIEWS, phases=PHASES, variants=VARIANTS, animations=lengths,
                  frames=len(images), world_sizes=sizes, center_y=centers,
                  min_opaque_pixels=min(coverage), max_opaque_pixels=max(coverage),
                  texture_paths=sorted(texture_paths))
    (out / "enemy_art.json").write_text(json.dumps(report, indent=2) + "\n")
    print("enemies: %d baked poses, 8 views, 8 animation phases, 16/32 px tiles" % len(images), flush=True)
    return report


def main():
    import import_rom as ir
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom")
    parser.add_argument("--decomp", default="sm64")
    parser.add_argument("--out", default="build/import")
    args = parser.parse_args()
    rom, _ = ir.normalize_rom(Path(args.rom).read_bytes())
    version, _ = ir.identify(rom, args.decomp)
    bake(ir.Assets(rom, version, args.decomp), args.decomp, args.out)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Import tool, in the spirit of libsm64: reads YOUR copy of Super Mario 64
and extracts every available asset into build/import/library, then converts
what the demo supports into build/import/import_data.c.

    tools/import_rom.py ROM [--decomp sm64] [--out build/import]

- The ROM can be .z64, .v64 or .n64 (byte order is detected) and must be one
  the decomp knows (US, JP, EU, Shindou, iQue): its SHA-1 is checked against
  the decomp's sm64.<version>.sha1.
- Geometry (Mario's low-poly model, the level meshes) comes from the decomp's
  sources; the ROM provides the textures, located with the decomp's
  assets.json (MIO0 decompression and N64 texture decoding are done here, so
  no decomp tools need to be built).
- The complete offline library contains all available textures, skyboxes,
  samples, sequences and binary data, plus model/object source definitions.
  Every image also has RGB555 palettes and tiled 4bpp GBA data. The library
  manifest records provenance, dimensions, groups and checksums.
- The demo conversion uses a subset: triangle colors, sky gradients, coin,
  tree and meter sprites, and three songs. Importing an object into the
  library does not implement its behavior or rendering in the GBA engine.

The output is derived from your ROM: keep it, and the demo ROM built from it,
to yourself.
"""
import argparse
import hashlib
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import n64gfx  # noqa: E402
import n64music  # noqa: E402
import n64seq  # noqa: E402

LEVELS = ["bob", "wf", "ccm", "bitdw"]  # the demo's level order
SKYBOXES = ["water", "bitfs", "wdw", "cloud_floor", "ccm", "ssl", "bbh", "bidw", "clouds", "bits"]
BACKGROUNDS = ["BACKGROUND_OCEAN_SKY", "BACKGROUND_FLAMING_SKY", "BACKGROUND_UNDERWATER_CITY",
               "BACKGROUND_BELOW_CLOUDS", "BACKGROUND_SNOW_MOUNTAINS", "BACKGROUND_DESERT",
               "BACKGROUND_HAUNTED", "BACKGROUND_GREEN_SKY", "BACKGROUND_ABOVE_CLOUDS",
               "BACKGROUND_PURPLE_SKY"]

LEVEL_COLORS = 48     # palette: 48 colors x 4 fog levels = indices 0..191
MARIO_MATERIALS = 8   # palette: 8 materials x 4 light levels = 192..223
SUN = (0.40, 0.82, 0.41)  # the demo's sun (render_build.c)


# --- ROM --------------------------------------------------------------------

def normalize_rom(data):
    magic = data[:4]
    if magic == b"\x80\x37\x12\x40":
        return data, "z64"
    if magic == b"\x37\x80\x40\x12":  # v64: 16-bit byte swapped
        b = bytearray(data)
        b[0::2], b[1::2] = data[1::2], data[0::2]
        return bytes(b), "v64"
    if magic == b"\x40\x12\x37\x80":  # n64: 32-bit little endian
        b = bytearray(len(data))
        b[0::4], b[1::4], b[2::4], b[3::4] = data[3::4], data[2::4], data[1::4], data[0::4]
        return bytes(b), "n64"
    raise SystemExit("not an N64 ROM (unknown header %s)" % magic.hex())


def identify(rom, decomp):
    sha = hashlib.sha1(rom).hexdigest()
    for ver in ("us", "jp", "eu", "sh", "cn"):
        path = os.path.join(decomp, "sm64.%s.sha1" % ver)
        if os.path.exists(path) and open(path).read().split()[0] == sha:
            return ver, sha
    raise SystemExit("ROM not recognized (SHA-1 %s): the decomp supports the US, JP, EU, "
                     "Shindou and iQue releases, unmodified" % sha)


def mio0_decode(buf, off):
    if buf[off:off + 4] != b"MIO0":
        raise ValueError("no MIO0 block at 0x%x" % off)
    size = int.from_bytes(buf[off + 4:off + 8], "big")
    comp = off + int.from_bytes(buf[off + 8:off + 12], "big")
    raw = off + int.from_bytes(buf[off + 12:off + 16], "big")
    out = bytearray()
    bit = 0
    while len(out) < size:
        if buf[off + 16 + bit // 8] & (0x80 >> (bit % 8)):
            out.append(buf[raw])
            raw += 1
        else:
            v = (buf[comp] << 8) | buf[comp + 1]
            comp += 2
            length, back = (v >> 12) + 3, (v & 0xFFF) + 1
            for _ in range(length):
                out.append(out[-back])
        bit += 1
    return bytes(out)


def s5(v):
    return v * 255 // 31


def decode_texture(raw, fmt, w, h):
    """N64 texture -> list of (r, g, b, a), 0..255 (as the decomp's n64graphics)."""
    px = []
    n = w * h
    if fmt == "rgba16":
        for i in range(n):
            v = (raw[2 * i] << 8) | raw[2 * i + 1]
            px.append((s5(v >> 11), s5((v >> 6) & 31), s5((v >> 1) & 31), 255 if v & 1 else 0))
    elif fmt == "rgba32":
        for i in range(n):
            px.append(tuple(raw[4 * i:4 * i + 4]))
    elif fmt == "ia16":
        for i in range(n):
            px.append((raw[2 * i],) * 3 + (raw[2 * i + 1],))
    elif fmt == "ia8":
        for i in range(n):
            px.append(((raw[i] >> 4) * 0x11,) * 3 + ((raw[i] & 15) * 0x11,))
    elif fmt == "ia4":
        for i in range(n):
            b = raw[i // 2] >> 4 if i % 2 == 0 else raw[i // 2] & 15
            px.append((((b >> 1) & 7) * 0x24,) * 3 + (255 if b & 1 else 0,))
    elif fmt == "ia1":
        for i in range(n):
            v = 255 if raw[i // 8] & (0x80 >> (i % 8)) else 0
            px.append((v,) * 4)
    elif fmt == "i8":
        for i in range(n):
            px.append((raw[i],) * 3 + (255,))
    elif fmt == "i4":
        for i in range(n):
            b = raw[i // 2] >> 4 if i % 2 == 0 else raw[i // 2] & 15
            px.append((b * 0x11,) * 3 + (b * 0x11,))
    else:
        raise ValueError("texture format %s not supported" % fmt)
    return px


class Assets:
    def __init__(self, rom, ver, decomp):
        self.rom, self.ver = rom, ver
        self.map = json.load(open(os.path.join(decomp, "assets.json")))
        self.blocks, self.cache = {}, {}

    def raw(self, path):
        meta = self.map[path]
        size, pos = meta[-2], meta[-1][self.ver]
        if len(pos) == 2:
            if pos[0] not in self.blocks:
                self.blocks[pos[0]] = mio0_decode(self.rom, pos[0])
            return self.blocks[pos[0]][pos[1]:pos[1] + size], meta
        return self.rom[pos[0]:pos[0] + size], meta

    def texture(self, path):
        """(w, h, pixels) for an asset path like 'actors/mario/mario_logo.rgba16.png'."""
        if path not in self.cache:
            data, meta = self.raw(path)
            w, h = meta[0], meta[1]
            self.cache[path] = (w, h, decode_texture(data, path.split(".")[-2], w, h))
        return self.cache[path]

    def skybox(self, name):
        """The skybox as 8 rows x 8 columns of 31x31 tiles (skyconv's layout)."""
        data, _ = self.raw("textures/skyboxes/%s.png" % name)
        table_at = len(data) - 80 * 4
        table = [int.from_bytes(data[table_at + 4 * i:table_at + 4 * i + 4], "big") for i in range(80)]
        base = table[0]
        img = [[None] * 248 for _ in range(248)]
        for row in range(8):
            for col in range(8):
                t = (table[row * 10 + col] - base) // 0x800
                tile = decode_texture(data[t * 2048:(t + 1) * 2048], "rgba16", 32, 32)
                for y in range(31):
                    for x in range(31):
                        img[row * 31 + y][col * 31 + x] = tile[y * 32 + x]
        return img


# --- colors -----------------------------------------------------------------

def sample_points(n):
    """Barycentric sample points spread over a triangle."""
    pts = []
    for i in range(n):
        for j in range(n - i):
            a, b = (i + 1 / 3) / n, (j + 1 / 3) / n
            pts.append((1 - a - b, a, b))
    return pts


SAMPLES = sample_points(8)


def texel(tex, s, t, clamp_s, clamp_t):
    w, h, px = tex
    s, t = int(math.floor(s)), int(math.floor(t))
    s = min(max(s, 0), w - 1) if clamp_s else s % w
    t = min(max(t, 0), h - 1) if clamp_t else t % h
    return px[t * w + s]


def light_dir(light):
    d = light["dir"]
    l = math.sqrt(sum(x * x for x in d)) or 1
    return [x / l for x in d]


def shade_of(tri, k, bake):
    """(ambient, diffuse) per vertex k, each RGB 0..1. Unlit: the vertex
    color. Lit: the Lights1 colors; with bake, the vertex is lit as the RSP
    does (ambient + color * max(0, n.l), clamped) against the light's own
    direction; without, the diffuse part is kept for per-frame lighting."""
    st, v = tri["state"], tri["v"][k]
    if st["lighting"] and st["light"] is not None:
        amb = [c / 255 for c in st["light"]["amb"]]
        col = [c / 255 for c in st["light"]["col"]]
        if not bake:
            return amb, col
        d = max(0.0, sum(a * b for a, b in zip(vertex_normal(v), light_dir(st["light"]))))
        return [min(1.0, amb[c] + col[c] * d) for c in range(3)], [0.0, 0.0, 0.0]
    return [c / 255 for c in v["c"][:3]], [0.0, 0.0, 0.0]


def vertex_normal(v):
    n = [x - 256 if x > 127 else x for x in v["c"][:3]]
    l = math.sqrt(sum(x * x for x in n)) or 1
    return [x / l for x in n]


def tri_color(tri, assets, bake=False):
    """Per-triangle color as (ambient RGB, diffuse RGB, coverage): the average
    over sample points of what the combiner outputs, with the light's diffuse
    term kept separate (Mario is lit per frame; levels are baked by the caller)."""
    st = tri["state"]
    shades = [shade_of(tri, k, bake) for k in range(3)]
    tex = None
    if st["texture"] and not st["texture"].startswith("?") and not st["texgen"]:
        tex = assets.texture(st["texture"])
    comb = st["combine"]
    amb, dif, cov = [0.0] * 3, [0.0] * 3, 0.0
    for b in SAMPLES:
        sa = [sum(b[k] * shades[k][0][c] for k in range(3)) for c in range(3)]
        sd = [sum(b[k] * shades[k][1][c] for k in range(3)) for c in range(3)]
        if tex is not None:
            s = sum(b[k] * tri["v"][k]["uv"][0] for k in range(3)) * st["tex_scale"][0] / 32
            t = sum(b[k] * tri["v"][k]["uv"][1] for k in range(3)) * st["tex_scale"][1] / 32
            r, g, bb, a = texel(tex, s, t, st.get("clamp_s"), st.get("clamp_t"))
            tc, ta = [r / 255, g / 255, bb / 255], a / 255
        else:
            tc, ta = [1.0, 1.0, 1.0], 1.0
        if tex is None or "SHADE" in comb and "MODULATE" not in comb and "BLEND" not in comb:
            ca, cd, alpha = sa, sd, 1.0
        elif "DECAL" in comb:
            ca, cd, alpha = tc, [0.0] * 3, ta
        elif "BLEND" in comb:
            ca = [sa[c] + (tc[c] - sa[c]) * ta for c in range(3)]
            cd = [sd[c] * (1 - ta) for c in range(3)]
            alpha = 1.0
        else:  # MODULATE*
            ca = [sa[c] * tc[c] for c in range(3)]
            cd = [sd[c] * tc[c] for c in range(3)]
            alpha = ta if "RGBA" in comb or "IA" in comb or tri["layer"] == "LAYER_ALPHA" else 1.0
        for c in range(3):
            amb[c] += ca[c] * alpha
            dif[c] += cd[c] * alpha
        cov += alpha
    if not st["lighting"] and "TRANSPARENT" in (tri["layer"] or ""):
        cov *= sum(v["c"][3] for v in tri["v"]) / (3 * 255.0)  # vertex alpha
    if cov <= 0:
        return [0.0] * 3, [0.0] * 3, 0.0
    return [x / cov for x in amb], [x / cov for x in dif], cov / len(SAMPLES)


def face_normal(p):
    a = [p[1][i] - p[0][i] for i in range(3)]
    b = [p[2][i] - p[0][i] for i in range(3)]
    n = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    l = math.sqrt(sum(x * x for x in n))
    return [x / l for x in n] if l > 0 else None


def kmeans(points, weights, k, iters=40):
    """Weighted k-means in RGB (deterministic seeding: farthest point)."""
    if len(points) <= k:
        return [list(p) for p in points], list(range(len(points)))
    order = sorted(range(len(points)), key=lambda i: -weights[i])
    centers = [list(points[order[0]])]
    while len(centers) < k:
        best, bd = None, -1
        for i in order:
            d = min(sum((points[i][c] - ce[c]) ** 2 for c in range(len(ce))) for ce in centers) * (weights[i] ** 0.5)
            if d > bd:
                best, bd = i, d
        centers.append(list(points[best]))
    assign = [0] * len(points)
    for _ in range(iters):
        for i, p in enumerate(points):
            assign[i] = min(range(k), key=lambda j: sum((p[c] - centers[j][c]) ** 2 for c in range(len(p))))
        for j in range(k):
            ws = sum(weights[i] for i in range(len(points)) if assign[i] == j)
            if ws > 0:
                centers[j] = [sum(points[i][c] * weights[i] for i in range(len(points)) if assign[i] == j) / ws
                              for c in range(len(points[0]))]
    return centers, assign


def rgb15(c):
    r, g, b = [min(31, max(0, int(round(x * 31)))) for x in c]
    return r | (g << 5) | (b << 10)


# --- Mario ------------------------------------------------------------------

def convert_mario(decomp, assets):
    parts, tris = n64gfx.mario_triangles(decomp)
    verts, vindex, out = [], {}, []
    feats, weights = [], []
    for t in tris:
        p = [v["pos"] for v in t["v"]]
        n = face_normal(p)
        if n is None:
            continue
        amb, dif, cov = tri_color(t, assets)
        if cov < 0.3:
            continue
        ids = []
        for v in p:
            key = (t["part"], tuple(v))
            if key not in vindex:
                vindex[key] = len(verts)
                verts.append(key)
            ids.append(vindex[key])
        area = 0.5 * math.sqrt(sum(x * x for x in [
            (p[1][1] - p[0][1]) * (p[2][2] - p[0][2]) - (p[1][2] - p[0][2]) * (p[2][1] - p[0][1]),
            (p[1][2] - p[0][2]) * (p[2][0] - p[0][0]) - (p[1][0] - p[0][0]) * (p[2][2] - p[0][2]),
            (p[1][0] - p[0][0]) * (p[2][1] - p[0][1]) - (p[1][1] - p[0][1]) * (p[2][0] - p[0][0])]))
        out.append({"v": ids, "n": n, "part": t["part"]})
        feats.append(amb + dif)
        weights.append(area + 1)
    centers, assign = kmeans(feats, weights, MARIO_MATERIALS)
    pal = []
    for j in range(MARIO_MATERIALS):
        c = centers[j] if j < len(centers) else [0.0] * 6
        for lvl in range(4):
            pal.append(rgb15([min(1.0, c[i] + c[3 + i] * lvl / 3) for i in range(3)]))
    for t, a in zip(out, assign):
        t["mat"] = a
    return verts, out, pal


# --- levels -----------------------------------------------------------------

def level_background(decomp, level):
    src = open(os.path.join(decomp, "levels/%s/areas/1/geo.inc.c" % level)).read()
    for i, name in enumerate(BACKGROUNDS):
        if "GEO_BACKGROUND(%s," % name in src:
            return SKYBOXES[i]
    return None


def sky_gradient(assets, name):
    """16 colors from 43.6 degrees above the horizon (entry 0) down to the
    horizon (entry 15), averaged around the full 360 degrees. Skybox rows: the
    horizon is at tile row 4, one tile row per 30 degrees (skybox.c)."""
    img = assets.skybox(name)
    out = []
    for i in range(16):
        elev = 43.6 * (15 - i) / 15
        row = 4 - elev / 30
        y0, y1 = int(row * 31) - 4, int(row * 31) + 4
        acc, n = [0, 0, 0], 0
        for y in range(max(0, y0), min(248, y1)):
            for p in img[y]:
                for c in range(3):
                    acc[c] += p[c]
                n += 1
        out.append([x / n / 255 for x in acc])
    return out


def convert_level(decomp, assets, level):
    tris = n64gfx.level_triangles(decomp, level)
    verts, vindex, out = [], {}, []
    colors, weights = [], []
    for t in tris:
        p = [[int(round(x)) for x in v["pos"]] for v in t["v"]]
        n = face_normal(p)
        if n is None:
            continue
        col, _, cov = tri_color(t, assets, bake=True)
        if t["layer"] == "LAYER_ALPHA" and cov < 0.5:
            continue  # mostly transparent cutouts (grass tufts, fence gaps)
        if "TRANSPARENT" in t["layer"] and cov < 0.6:
            continue  # translucent decals (soft shadows, dirt): no blending here
        st = t["state"]
        ids = []
        for v in p:
            key = tuple(v)
            if key not in vindex:
                vindex[key] = len(verts)
                verts.append(key)
            ids.append(vindex[key])
        flags = 0
        if "DECAL" in t["layer"]:
            flags |= 1
        if not st.get("cull", True):
            flags |= 2
        area = 0.5 * math.sqrt(sum((x * 1.0) ** 2 for x in [
            (p[1][1] - p[0][1]) * (p[2][2] - p[0][2]) - (p[1][2] - p[0][2]) * (p[2][1] - p[0][1]),
            (p[1][2] - p[0][2]) * (p[2][0] - p[0][0]) - (p[1][0] - p[0][0]) * (p[2][2] - p[0][2]),
            (p[1][0] - p[0][0]) * (p[2][1] - p[0][1]) - (p[1][1] - p[0][1]) * (p[2][0] - p[0][0])]))
        out.append({"v": ids, "flags": flags, "n": n, "area": area})
        colors.append(col)
        weights.append(math.sqrt(area) + 1)
    centers, assign = kmeans(colors, weights, LEVEL_COLORS)
    for t, a in zip(out, assign):
        t["color"] = a
    sky = sky_gradient(assets, level_background(decomp, level))
    horizon = sky[15]
    pal = []
    for j in range(LEVEL_COLORS):
        c = centers[j] if j < len(centers) else [0.0] * 3
        for f in range(4):
            pal.append(rgb15([c[i] + (horizon[i] - c[i]) * f * 5 / 16 for i in range(3)]))
    # ground color: the most common (by area) color of upward-facing triangles
    ground = {}
    for t in out:
        if t["n"][1] > 0.7:
            ground[t["color"]] = ground.get(t["color"], 0) + t["area"]
    groundColor = max(ground, key=ground.get) if ground else 0
    return {"verts": verts, "tris": out, "pal": pal, "sky": [rgb15(c) for c in sky],
            "ground": groundColor * 4, "groundIndex": groundColor}


# --- coins ------------------------------------------------------------------

# The coin's spin, in order (yellow_coin_geo's switch: 2 game frames each).
COIN_TEXTURES = ["actors/coin/coin_front.ia16.png", "actors/coin/coin_tilt_right.ia16.png",
                 "actors/coin/coin_side.ia16.png", "actors/coin/coin_tilt_left.ia16.png"]
# Sprite sizes in pixels: must match kArtSizes in demo/coins.c (larger coins
# are the 16 px sprite scaled up by the GBA).
COIN_SIZES = [3, 4, 5, 6, 8, 10, 12, 14, 16]
COIN_SHADES = 4  # must match SHADES in demo/coins.c


def coin_sprite(tex, size):
    """A 32x32 IA texture box-filtered to size x size: 0 = transparent, else a
    shade 1..COIN_SHADES of the texture's intensity (the game multiplies it by
    the coin's vertex color: yellow or red)."""
    w, h, px = tex
    out = []
    for y in range(size):
        for x in range(size):
            x0, x1 = x * w / size, (x + 1) * w / size
            y0, y1 = y * h / size, (y + 1) * h / size
            a_sum = i_sum = area = 0.0
            for sy in range(int(y0), min(h, int(math.ceil(y1)))):
                fy = min(y1, sy + 1) - max(y0, sy)
                for sx in range(int(x0), min(w, int(math.ceil(x1)))):
                    f = fy * (min(x1, sx + 1) - max(x0, sx))
                    r, _, _, a = px[sy * w + sx]
                    a_sum += a * f
                    i_sum += r * a * f
                    area += f
            if a_sum < 0.5 * 255 * area:
                out.append(0)
            else:
                i = i_sum / a_sum / 255.0
                out.append(max(1, min(COIN_SHADES, int(round(i * COIN_SHADES)))))
    return out


def convert_coin(textures):
    """textures: the 4 decoded spin frames -> [frame][size] pixel lists."""
    return [[coin_sprite(t, s) for s in COIN_SIZES] for t in textures]


# --- tree and power meter ---------------------------------------------------

def sample(tex, u, v):
    """Texel (u, v) of a decoded texture, clamped like G_TX_CLAMP."""
    w, h, px = tex
    u = min(w - 1, max(0, int(math.floor(u))))
    v = min(h - 1, max(0, int(math.floor(v))))
    return px[v * w + u]


def raster_tri(tri, x, y):
    """(u, v) in texels at world (x, y) if inside the triangle, else None.
    tri: 3 vertices (x, y, s, t), s and t in the N64's 1/32 texel units."""
    (x0, y0, s0, t0), (x1, y1, s1, t1), (x2, y2, s2, t2) = tri
    d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    a = ((y1 - y2) * (x - x2) + (x2 - x1) * (y - y2)) / d
    b = ((y2 - y0) * (x - x2) + (x0 - x2) * (y - y2)) / d
    c = 1 - a - b
    if min(a, b, c) < 0:
        return None
    return (a * s0 + b * s1 + c * s2) / 32.0, (a * t0 + b * t1 + c * t2) / 32.0


def render_quads(parts, x0, y1, scale, w, h, ss=4):
    """Render textured triangles (as the game's display list draws them) into a
    w x h RGBA image: pixel (px, py) covers world x0 + px*scale, y1 - py*scale.
    parts: [(texture, [tri, ...])], later parts drawn over earlier ones."""
    out = []
    for py in range(h):
        for px in range(w):
            acc, alpha = [0.0, 0.0, 0.0], 0.0
            for sy in range(ss):
                for sx in range(ss):
                    x = x0 + (px + (sx + 0.5) / ss) * scale
                    y = y1 - (py + (sy + 0.5) / ss) * scale
                    col = None
                    for tex, tris in parts:
                        for tri in tris:
                            uv = raster_tri(tri, x, y)
                            if uv is not None:
                                c = sample(tex, *uv)
                                if c[3] >= 128:
                                    col = c
                    if col is not None:
                        for k in range(3):
                            acc[k] += col[k]
                        alpha += 1
            n = ss * ss
            if alpha >= n / 2:
                out.append((acc[0] / alpha, acc[1] / alpha, acc[2] / alpha, 255))
            else:
                out.append((0, 0, 0, 0))
    return out


def quad(x0, y0, x1, y1, s0, t0, s1, t1):
    """Two triangles of an axis-aligned quad, (x0, y0) bottom left (y up)."""
    a, b, c, d = (x0, y0, s0, t0), (x1, y0, s1, t0), (x1, y1, s1, t1), (x0, y1, s0, t1)
    return [(a, b, c), (a, c, d)]


def bubbly_tree(assets):
    """actors/tree: tree_seg3_dl_0302FEE8's two triangles, left and right side
    textures, world x -356..358, y -9..800. 64 px tall, centered."""
    left = assets.texture("actors/tree/tree_left_side.rgba16.png")
    right = assets.texture("actors/tree/tree_right_side.rgba16.png")
    parts = [(left, [((-356, -9, -796, 2012), (0, -9, 990, 2012), (0, 800, 990, -712))]),
             (right, [((0, -9, 0, 2012), (358, -9, 1756, 2012), (0, 800, 0, -712))])]
    scale = 809 / 64.0
    return render_quads(parts, -32 * scale, 800, scale, 64, 64)


METER_TEXTURES = ["one_segment", "two_segments", "three_segments", "four_segments",
                  "five_segments", "six_segments", "seven_segments", "full"]


def power_meter(assets):
    """actors/power_meter: the base (left and right halves, 64x64 around the
    center) with the health segments for 0..8 wedges over it (32x32 at x
    -16..15, y -20..12), as dl_power_meter_base and the segments' list draw
    them. 9 images, 32x32 (half size)."""
    cn = "_cn" if assets.ver == "cn" else ""  # the iQue version's base says so in Chinese
    base = [(assets.texture("actors/power_meter/power_meter_left_side%s.rgba16.png" % cn),
             quad(-32, -32, 0, 32, 0, 2016, 992, 0)),
            (assets.texture("actors/power_meter/power_meter_right_side%s.rgba16.png" % cn),
             quad(0, -32, 32, 32, 1, 2016, 1024, 0))]
    images = []
    for n in range(9):
        parts = list(base)
        if n > 0:
            seg = assets.texture("actors/power_meter/power_meter_%s.rgba16.png" % METER_TEXTURES[n - 1])
            parts.append((seg, quad(-16, -20, 15, 12, 0, 992, 992, 0)))
        images.append(render_quads(parts, -32, 32, 2.0, 32, 32, ss=2))
    return images


def palettize(images, k=15):
    """Shared palette of up to k colors (index 0 = transparent) -> (pal, idx)."""
    counts = {}
    for img in images:
        for p in img:
            if p[3]:
                key = tuple(int(c) >> 3 for c in p[:3])
                counts[key] = counts.get(key, 0) + 1
    keys = sorted(counts)
    pts = [[c / 31.0 for c in key] for key in keys]
    centers, assign = kmeans(pts, [counts[kk] for kk in keys], min(k, max(1, len(keys))))
    lookup = {kk: assign[i] + 1 for i, kk in enumerate(keys)}
    idx = [[lookup[tuple(int(c) >> 3 for c in p[:3])] if p[3] else 0 for p in img] for img in images]
    return [rgb15(c) for c in centers], idx


def write_sprite_c(path, coin, tree, meter, info):
    with open(path, "w") as f:
        f.write("/* Generated by tools/import_rom.py from %s. Derived from your ROM:\n"
                " * do not distribute. Sprites for the demo (demo/coins.c, actors.c, hud.c). */\n\n" % info)
        f.write("/* The coin's 4 spin frames, pre-scaled to %s px, 0 = transparent,\n"
                " * 1..%d = shade. */\n" % ("/".join(map(str, COIN_SIZES)), COIN_SHADES))
        n = sum(s * s for s in COIN_SIZES)
        f.write("const unsigned char gImpCoinArt[4][%d] = {\n" % n)
        for fr in coin:
            flat = [v for sp in fr for v in sp]
            f.write("    {%s},\n" % ",".join(str(v) for v in flat))
        f.write("};\n\n")
        pal, idx = tree
        f.write("/* The bubbly tree, 64x64, 0 = transparent, 1..15 = gImpTreePal. */\n")
        f.write("const unsigned short gImpTreePal[15] = {%s};\n" % ", ".join("0x%04x" % c for c in pal + [0] * (15 - len(pal))))
        f.write("const unsigned char gImpTreeArt[64 * 64] = {%s};\n\n" % ",".join(str(v) for v in idx[0]))
        pal, idx = meter
        f.write("/* The power meter with 0..8 wedges, 32x32, 0 = transparent, 1..15 = gImpMeterPal. */\n")
        f.write("const unsigned short gImpMeterPal[15] = {%s};\n" % ", ".join("0x%04x" % c for c in pal + [0] * (15 - len(pal))))
        f.write("const unsigned char gImpMeterArt[9][32 * 32] = {\n")
        for im in idx:
            f.write("    {%s},\n" % ",".join(str(v) for v in im))
        f.write("};\n")


# --- music ------------------------------------------------------------------

# The demo's levels' music (their level scripts' SET_BACKGROUND_MUSIC).
SONGS = ["03_level_grass", "08_level_snow", "11_level_koopa_road"]
LEVEL_SONGS = [0, 0, 1, 2]  # bob, wf (grass too), ccm, bitdw


def convert_music(sound):
    """[(name, chip voices or None)]: a song the sequence player can't play
    is left out (with a warning) rather than failing the import."""
    out = []
    for name in SONGS:
        try:
            notes, loop = n64seq.play(sound.sequence(name))
            out.append((name, n64music.chip(notes, loop), notes, loop))
        except (n64seq.SeqError, KeyError, IndexError) as e:
            print("music: %s skipped (%s)" % (name, e))
            out.append((name, None, None, None))
    return out


def write_music_c(path, songs, info):
    voices = ("melody", "harmony", "bass", "drums")
    with open(path, "w") as f:
        f.write("/* Generated by tools/import_rom.py from %s. Derived from your ROM:\n"
                " * do not distribute. The levels' music arranged for the GBA's 4 Game Boy\n"
                " * voices (tools/n64music.py), for demo/music.c. */\n" % info)
        f.write("struct MusicVoice { const unsigned char *ev; unsigned short count, loop, tail; };\n")
        f.write("struct MusicSong { struct MusicVoice voice[4]; };\n\n")
        for si, (name, chip, _, _) in enumerate(songs):
            for v in voices:
                ev = chip.get(v, ([], 0, 0))[0] if chip else []
                flat = []
                for d, note, lv in ev:
                    flat += [d, note & 0xFF, lv]
                f.write("static const unsigned char sSong%d_%s[%d] = {%s};\n" % (
                    si, v, max(1, len(flat)), ",".join(map(str, flat)) or "0"))
        f.write("\nconst struct MusicSong gImpSongs[%d] = {\n" % len(songs))
        for si, (name, chip, _, _) in enumerate(songs):
            parts = []
            for v in voices:
                ev, loop, tail = chip.get(v, ([], 0, 0)) if chip else ([], 0, 0)
                parts.append("{ sSong%d_%s, %d, %d, %d }" % (si, v, len(ev), loop, tail))
            f.write("    /* %s */ { { %s } },\n" % (name, ", ".join(parts)))
        f.write("};\n")
        level = [LEVEL_SONGS[i] if songs[LEVEL_SONGS[i]][1] else -1 for i in range(len(LEVEL_SONGS))]
        f.write("const signed char gImpLevelSong[4] = {%s};\n" % ", ".join(map(str, level)))


def write_music_pcm(out_dir, sound, songs, info):
    """The true build's music: each song rendered with the ROM's samples
    (n64music.render) into build/import/music_pcm.bin, with its offsets and
    loop points in music_pcm.c. demo/music.c streams it by DMA."""
    blob, rows = bytearray(), []
    for name, chip, notes, loop in songs:
        if not notes:
            rows.append((0, 0, 0))
            continue
        data, loop_start = n64music.render(notes, loop, sound, sound.sequence_banks(name))
        while len(blob) % 4:
            blob.append(0)
        length = len(data) - 2048  # the padding after the loop end
        rows.append((len(blob), length, loop_start))
        print("music: %s rendered, %.1f s, %d KB" % (name, length / float(n64music.PCM_RATE), len(data) // 1024))
        blob += data
    open(os.path.join(out_dir, "music_pcm.bin"), "wb").write(bytes(blob))
    with open(os.path.join(out_dir, "music_pcm.c"), "w") as f:
        f.write("/* Generated by tools/import_rom.py from %s. Derived from your ROM:\n"
                " * do not distribute. Offsets into music_pcm.bin (8-bit mono, %d Hz). */\n" % (info, n64music.PCM_RATE))
        f.write("struct PcmSong { unsigned int offset, length, loop; };\n")
        f.write("const struct PcmSong gImpPcmSongs[%d] = {\n" % len(rows))
        for (o, l, lp), (name, _, _, _) in zip(rows, songs):
            f.write("    { %d, %d, %d }, /* %s */\n" % (o, l, lp, name))
        f.write("};\n")


# --- output -----------------------------------------------------------------

def write_c(path, mario, levels, info):
    mverts, mtris, mpal = mario
    with open(path, "w") as f:
        f.write("/* Generated by tools/import_rom.py from %s. Derived from your ROM:\n"
                " * do not distribute. */\n#include \"import.h\"\n\n" % info)
        f.write("const u16 gImpMarioPal[32] = {%s};\n" % ", ".join("0x%04x" % c for c in mpal))
        f.write("const struct ImpMVert gImpMarioVerts[%d] = {\n" % len(mverts))
        for part, p in mverts:
            f.write("    {%d, %d, %d, %d},\n" % (p[0], p[1], p[2], part))
        f.write("};\nconst struct ImpMTri gImpMarioTris[%d] = {\n" % len(mtris))
        for t in mtris:
            n = [int(round(x * 16384)) for x in t["n"]]
            n = [max(-16384, min(16384, x)) for x in n]
            f.write("    {{%d, %d, %d}, {%d, %d, %d}, %d, %d},\n" % (tuple(t["v"]) + tuple(n) + (t["mat"], t["part"])))
        f.write("};\nconst u16 gImpMarioNumVerts = %d, gImpMarioNumTris = %d;\n\n" % (len(mverts), len(mtris)))
        for lv, d in zip(LEVELS, levels):
            f.write("static const s16 sVerts_%s[%d][3] = {\n" % (lv, len(d["verts"])))
            for v in d["verts"]:
                f.write("    {%d, %d, %d},\n" % v)
            f.write("};\nstatic const struct ImpTri sTris_%s[%d] = {\n" % (lv, len(d["tris"])))
            for t in d["tris"]:
                f.write("    {{%d, %d, %d}, %d, %d},\n" % (tuple(t["v"]) + (t["color"] * 4, t["flags"])))
            f.write("};\n")
        f.write("\nconst struct ImpLevel gImpLevels[%d] = {\n" % len(LEVELS))
        for lv, d in zip(LEVELS, levels):
            f.write("    { sVerts_%s, sTris_%s, %d, %d, %d,\n      {%s},\n      {%s} },\n" % (
                lv, lv, len(d["verts"]), len(d["tris"]), d["ground"],
                ", ".join("0x%04x" % c for c in d["pal"]),
                ", ".join("0x%04x" % c for c in d["sky"])))
        f.write("};\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rom")
    ap.add_argument("--decomp", default="sm64")
    ap.add_argument("--out", default="build/import")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--assets-only", action="store_true", help="extract the full library without building demo data")
    mode.add_argument("--demo-only", action="store_true", help="convert only the demo's supported assets")
    args = ap.parse_args()

    rom, order = normalize_rom(open(args.rom, "rb").read())
    ver, sha = identify(rom, args.decomp)
    print("ROM: %s byte order, version %s, SHA-1 %s" % (order, ver, sha))
    if not args.demo_only:
        from asset_library import import_library
        import_library(rom, ver, sha, args.decomp, args.out)
    if args.assets_only:
        return
    assets = Assets(rom, ver, args.decomp)

    mario = convert_mario(args.decomp, assets)
    print("Mario: %d vertices, %d triangles, %d materials" % (len(mario[0]), len(mario[1]), MARIO_MATERIALS))
    levels = []
    for lv in LEVELS:
        d = convert_level(args.decomp, assets, lv)
        print("%-6s %4d vertices, %4d triangles, %d colors" % (lv, len(d["verts"]), len(d["tris"]), LEVEL_COLORS))
        levels.append(d)
    os.makedirs(args.out, exist_ok=True)
    # Size the renderer's mesh/cache arrays for the imported geometry. The
    # collision-mesh defaults reserve too much EWRAM alongside real Mario.
    with open(os.path.join(args.out, "import_limits.h"), "w") as f:
        f.write("/* Generated by tools/import_rom.py; imported mesh capacities. */\n")
        f.write("#define IMP_MAX_LEVEL_VERTS %d\n" % max(len(d["verts"]) for d in levels))
        f.write("#define IMP_MAX_LEVEL_TRIS %d\n" % max(len(d["tris"]) for d in levels))
    write_c(os.path.join(args.out, "import_data.c"), mario, levels, "SM64 %s (%s)" % (ver.upper(), sha[:12]))
    print("wrote %s" % os.path.join(args.out, "import_data.c"))
    coin = convert_coin([assets.texture(t) for t in COIN_TEXTURES])
    tree = palettize([bubbly_tree(assets)])
    meter = palettize(power_meter(assets))
    write_sprite_c(os.path.join(args.out, "sprite_art.c"), coin, tree, meter, "SM64 %s (%s)" % (ver.upper(), sha[:12]))
    print("wrote %s" % os.path.join(args.out, "sprite_art.c"))
    from bake_enemies import bake
    bake(assets, args.decomp, args.out)
    import n64audio
    sound = n64audio.Sound(rom, ver, args.decomp)
    songs = convert_music(sound)
    for name, chip, notes, loop in songs:
        if chip:
            print("music: %s, %d notes, loop %.1f..%.1f s" % (name, len(notes), loop[0], loop[1]))
    write_music_c(os.path.join(args.out, "music_data.c"), songs, "SM64 %s (%s)" % (ver.upper(), sha[:12]))
    print("wrote %s" % os.path.join(args.out, "music_data.c"))
    write_music_pcm(args.out, sound, songs, "SM64 %s (%s)" % (ver.upper(), sha[:12]))
    print("wrote %s" % os.path.join(args.out, "music_pcm.bin"))


if __name__ == "__main__":
    main()

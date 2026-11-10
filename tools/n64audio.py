#!/usr/bin/env python3
"""SM64's sound data from your ROM, for the demo's music import.

- Banks and samples: the ROM's sound ctl/tbl (located with the decomp's
  assets.json), parsed with the decomp's own tools/disassemble_sound.py.
- Samples are VADPCM: vadpcm_decode() is the N64 SDK decoder of the decomp's
  tools/sdk-tools/adpcm (vdecode.c, vpredictor.c) in Python, bit for bit
  (tools/test_music.py checks it against the SDK's vadpcm_dec).
- Sequences: the .m64 files at their assets.json offsets, played by
  tools/n64seq.py.
"""
import importlib.util
import json
import os
import struct


def vadpcm_decode(data, book_table, order=2, npredictors=2):
    """VADPCM frames (9 bytes: header, 16 4-bit residuals) -> s16 samples, as
    vdecodeframe() does it (no clamping, inner products rounded down)."""
    # readaifccodebook(): per predictor, 8 rows of (order + 8) coefficients
    coef = []
    ts = list(book_table)
    for p in range(npredictors):
        rows = [[0] * (order + 8) for _ in range(8)]
        for j in range(order):
            for k in range(8):
                rows[k][j] = ts[p * order * 8 + j * 8 + k]
        for k in range(1, 8):
            rows[k][order] = rows[k - 1][order - 1]
        rows[0][order] = 1 << 11
        for k in range(1, 8):
            for j in range(k):
                rows[j][k + order] = 0
            for j in range(k, 8):
                rows[j][k + order] = rows[j - k][order]
        coef.append(rows)
    out = []
    prev = [0] * 16
    for f in range(len(data) // 9):
        fr = data[f * 9:(f + 1) * 9]
        scale = 1 << (fr[0] >> 4)
        pred = fr[0] & 0xF
        ix = []
        for c in fr[1:]:
            for v in (c >> 4, c & 0xF):
                ix.append(v * scale if v <= 7 else (v - 16) * scale)
        cur = [0] * 16
        for j in range(2):
            in_vec = [0] * (order + 8)
            for i in range(8):
                in_vec[i + order] = ix[j * 8 + i]
            src = prev if j == 0 else cur
            base = 16 if j == 0 else 8
            for i in range(order):
                in_vec[i] = src[base - order + i]
            for i in range(8):
                acc = sum(a * b for a, b in zip(coef[pred][i], in_vec))
                cur[i + j * 8] = acc // 2048  # rounded down, like inner_product()
        out.extend(cur)
        prev = cur
    return out


def _load_disassembler(decomp):
    path = os.path.join(decomp, "tools", "disassemble_sound.py")
    spec = importlib.util.spec_from_file_location("disassemble_sound", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Sound:
    """The ROM's banks, samples and sequences."""

    def __init__(self, rom, ver, decomp):
        self.rom, self.ver, self.decomp = rom, ver, decomp
        self.map = json.load(open(os.path.join(decomp, "assets.json")))
        ds = _load_disassembler(decomp)
        sver = "sh" if ver == "cn" else ver
        ctl_size, ctl_at = self.map["@sound ctl " + sver]
        tbl_size, tbl_at = self.map["@sound tbl " + sver]
        ctl = rom[ctl_at[ver][0]:ctl_at[ver][0] + ctl_size]
        tbl = rom[tbl_at[ver][0]:tbl_at[ver][0] + tbl_size]
        self.banks = []
        if sver == "sh":
            hs, ha = self.map["@sound ctl header sh"]
            ths, tha = self.map["@sound tbl header sh"]
            ctl_entries = ds.parse_sh_header(rom[ha[ver][0]:ha[ver][0] + hs], ds.TYPE_CTL)
            tbl_entries = ds.parse_sh_header(rom[tha[ver][0]:tha[ver][0] + ths], ds.TYPE_TBL)
            sample_banks = ds.parse_tbl(tbl, tbl_entries)[1]
            for i, (off, length, meta) in enumerate(ctl_entries):
                self.banks.append(ds.parse_ctl((meta[1], meta[2], "0000-00-00"), ctl[off:off + length],
                                               sample_banks[meta[0]], i, True))
        else:
            ctl_entries = ds.parse_seqfile(ctl, ds.TYPE_CTL)
            tbl_entries = ds.parse_seqfile(tbl, ds.TYPE_TBL)
            tbls, _, bank_map = ds.parse_tbl(tbl, tbl_entries)
            for i, ((off, length), name) in enumerate(zip(ctl_entries, tbls)):
                entry = ctl[off:off + length]
                self.banks.append(ds.parse_ctl(ds.parse_ctl_header(entry[:16]), entry[16:],
                                               bank_map[name], i, False))
        self.cache = {}

    def sequence(self, name):
        """Raw .m64 bytes of a sequence, e.g. '03_level_grass'."""
        sver = "sh" if self.ver in ("sh", "cn") else self.ver
        for v in (sver, "us", "jp", "eu"):
            key = "sound/sequences/%s/%s.m64" % (v, name)
            if key in self.map and self.ver in self.map[key][1]:
                size, at = self.map[key]
                return self.rom[at[self.ver][0]:at[self.ver][0] + size]
        raise KeyError(name)

    def sequence_banks(self, name):
        """The banks a sequence uses (sound/sequences.json), as indices."""
        seqs = json.load(open(os.path.join(self.decomp, "sound", "sequences.json")))
        return [int(b.split("_")[0], 16) for b in seqs[name]]

    def instrument(self, bank, index):
        """(Inst, or None) of a bank's instrument number."""
        b = self.banks[bank]
        if index >= len(b.inst_list) or b.inst_list[index] is None:
            return None
        addr = b.inst_list[index]
        return next(i for i in b.insts if i.addr == addr)

    def drum(self, bank, index):
        b = self.banks[bank]
        if not b.drums:
            return None
        return b.drums[min(index, len(b.drums) - 1)]

    def envelope(self, bank, addr):
        return self.banks[bank].envelopes[addr].entries

    def sample(self, bank, sample_addr):
        """(pcm s16 list, loop (start, end, count)) of a bank's sample."""
        key = (bank, sample_addr)
        if key not in self.cache:
            e = self.banks[bank].samples[sample_addr]
            pcm = vadpcm_decode(e.data, e.book.table, e.book.order, e.book.npredictors)
            self.cache[key] = (pcm, (e.loop.start, e.loop.end, e.loop.count))
        return self.cache[key]

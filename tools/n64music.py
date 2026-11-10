#!/usr/bin/env python3
"""The demo's music from SM64's sequences (tools/n64seq.py notes):

- chip(): a 4-voice arrangement for the GBA's Game Boy sound channels, as
  event streams at 60 Hz for demo/music.c's player. Melody on square 2,
  harmony on square 1, bass on the wave channel, drums on noise. Each voice
  is monophonic: at each moment it plays the highest (melody, harmony) or
  lowest (bass) note sounding among the channels it takes.

Channel roles are chosen per song from the notes themselves: the drum kit
(instrument 0x7F) is the drums; of the other channels, the one with the
lowest average pitch is the bass, the busiest of the high ones the melody,
and the next one the harmony.
"""
FPS = 59.7275  # the GBA's refresh rate: the player steps once per VBlank


def _roles(notes):
    by_chan = {}
    for n in notes:
        by_chan.setdefault(n.chan, []).append(n)
    drums = [c for c, ns in by_chan.items() if all(n.drum for n in ns)]
    tonal = {c: ns for c, ns in by_chan.items() if c not in drums}
    if not tonal:
        return [], [], [], drums
    avg = {c: sum(n.note for n in ns) / len(ns) for c, ns in tonal.items()}
    weight = {c: sum(n.length * n.velocity * n.volume for n in ns) for c, ns in tonal.items()}
    if len(tonal) == 1:
        return list(tonal), [], [], drums
    bass = min(avg, key=lambda c: avg[c])
    rest = sorted((c for c in tonal if c != bass), key=lambda c: (-avg[c] * weight[c]))
    melody = rest[:1]
    harmony = rest[1:2]
    return melody, harmony, [bass], drums


def _mono(notes, chans, pick_high, t_end):
    """Monophonic timeline [(t_on, t_off, note, level)] from overlapping notes:
    at each moment the highest (or lowest) sounding note wins."""
    ns = [n for n in notes if n.chan in chans and n.t < t_end]
    cuts = sorted(set([n.t for n in ns] + [min(n.t + n.length, t_end) for n in ns]))
    out = []
    for a, b in zip(cuts, cuts[1:]):
        live = [n for n in ns if n.t <= a < n.t + n.length]
        if not live:
            continue
        n = max(live, key=lambda n: n.note) if pick_high else min(live, key=lambda n: n.note)
        level = max(1, min(15, int(round(15 * (n.velocity / 127.0) ** 2 * n.volume * 1.4))))
        if out and out[-1][2] == n.note and out[-1][1] == a and out[-1][4] is n:
            out[-1] = (out[-1][0], b, n.note, out[-1][3], n)
        else:
            out.append((a, b, n.note, level, n))
    return [(a, b, note, lv) for a, b, note, lv, _ in out]


def _events(timeline, loop_start, loop_end, drum=False):
    """60 Hz event stream [(delay frames before it, note, level)]: note 0 =
    silence, -1 = no change (long waits are split into 255-frame steps).
    Returns (events, loop_index, tail): after the last event the player waits
    tail frames, then jumps back to events[loop_index], which is at the
    loop start and restates what plays there."""
    ls, le = int(round(loop_start * FPS)), int(round(loop_end * FPS))
    points = []
    for a, b, note, lv in timeline:
        fa, fb = int(round(a * FPS)), int(round(b * FPS))
        if fb <= fa:
            fb = fa + 1
        if fa >= le:
            continue
        points.append((fa, 1, note, lv))
        points.append((min(fb, le), 0, 0, 0))
    points.append((ls, 2, None, None))  # the loop start
    # at equal frames: note offs first, then the loop marker, then note ons
    points.sort(key=lambda p: (p[0], {0: 0, 2: 1, 1: 2}[p[1]]))
    out, loop_index, now, state = [], 0, 0, (0, 0)

    def emit(f, note, lv):
        nonlocal now
        d = f - now
        while d > 255:
            out.append((255, -1, 0))
            d -= 255
        out.append((d, note, lv))
        now = f

    for f, kind, note, lv in points:
        if kind == 2:
            emit(f, -1, 0)
            loop_index = len(out) - 1
            out[loop_index] = (out[loop_index][0], state[0], state[1])
            continue
        if kind == 0:
            # an off only ends the note that's playing if nothing replaced it
            if state[0] == 0:
                continue
            # (offs are emitted when the note they end is still the state)
        if kind == 1 and (note, lv) == state:
            continue
        emit(f, note if kind == 1 else 0, lv if kind == 1 else 0)
        state = (note, lv) if kind == 1 else (0, 0)
    # the loop index must point at the restating event: its delay counts from
    # the previous event, so when jumping back the player skips that delay
    return out, loop_index, max(0, le - now)


def chip(notes, loop):
    """{voice: (events, loop_index, tail_frames)} for the voices that have notes."""
    loop_start, loop_end = loop
    melody, harmony, bass, drums = _roles(notes)
    voices = {}
    for name, chans, high in (("melody", melody, True), ("harmony", harmony, True), ("bass", bass, False)):
        if chans:
            voices[name] = _events(_mono(notes, chans, high, loop_end), loop_start, loop_end)
    if drums:
        hits = []
        for n in notes:
            if n.chan in drums and n.t < loop_end:
                # drum kit notes: low ones kicks, middle snares, high hi-hats
                kind = 1 if n.note < 24 else 2 if n.note < 40 else 3
                level = max(1, min(15, int(round(15 * (n.velocity / 127.0) ** 2 * n.volume * 1.4))))
                hits.append((n.t, n.t + 1.0 / FPS, kind, level))
        voices["drums"] = _events(hits, loop_start, loop_end, drum=True)
    return voices


# --- the true build: the song rendered with the ROM's own samples -----------

PCM_RATE = 16777216 // 1254  # 13378.9 Hz: GBA timer 0 at 1254 cycles, 224 samples a frame
UPDATES = 240.0              # envelope steps a second (US: 4 audio updates a frame)
NOTE_FREQ = [2.0 ** ((k - 39) / 12.0) for k in range(117)] + [0.5 * 2.0 ** ((k - 39) / 12.0)
                                                              for k in range(117, 128)]


def _envelope(entries, held, release_rate):
    """Envelope levels (0..1) per update: the entries as adsr_update() runs
    them (ramps of `delay` updates to `arg`, hang, goto, restart), held for
    `held` updates, then the release (releaseRate * 24 per update)."""
    out, cur, i, steps = [], 0.0, 0, 0
    while len(out) < held and steps < 100000:
        steps += 1
        if i >= len(entries):
            out.append(cur)
            continue
        delay, arg = entries[i]
        delay = delay - 0x10000 if delay >= 0x8000 else delay
        if delay == 0:            # disable
            break
        if delay == -1:           # hang
            out.extend([cur] * (held - len(out)))
            break
        if delay == -2:           # goto
            i = arg
            continue
        if delay == -3:           # restart
            i = 0
            continue
        target = float(arg)
        step = (target - cur) / delay
        for _ in range(delay):
            if len(out) >= held:
                break
            cur += step
            out.append(cur)
        i += 1
    rate = max(1, release_rate) * 24
    while cur >= 100 and len(out) < held + 20000:
        cur -= rate
        out.append(max(0.0, cur))
    return [v / 32767.0 for v in out]


def render(notes, loop, sound, banks, rate=PCM_RATE):
    """(samples: bytes of int8, loop_start sample): one pass of the song up to
    its loop end, plus a copy of the loop's start as padding, so the GBA's
    streaming can run past the end a little before it jumps back."""
    loop_start, loop_end = loop
    total = int(loop_end * rate)
    mix = [0.0] * (total + rate)  # a second of room for tails
    per_update = rate / UPDATES
    for n in notes:
        if n.t >= loop_end:
            continue
        bank = banks[n.bank] if n.bank < len(banks) else banks[0]
        if n.drum:
            d = sound.drum(bank, n.note)
            if d is None or d.sound is None:
                continue
            snd, env_addr, release, freq = d.sound, d.envelope, d.release_rate, d.sound.tuning
        else:
            inst = sound.instrument(bank, n.instr)
            if inst is None:
                continue
            snd = (inst.sound_lo if n.note < inst.normal_range_lo and inst.sound_lo
                   else inst.sound_hi if n.note > inst.normal_range_hi and inst.sound_hi else inst.sound_med)
            if snd is None:
                continue
            env_addr, release, freq = inst.envelope, inst.release_rate, NOTE_FREQ[n.note] * snd.tuning
        pcm, (ls, le, count) = sound.sample(bank, snd.sample_addr)
        if not pcm:
            continue
        env = _envelope(sound.envelope(bank, env_addr), max(1, int(n.length * UPDATES)), release)
        amp = (n.velocity / 127.0) ** 2 * n.volume / 32768.0
        step = freq * 32000.0 / rate   # output at 32 kHz on the N64
        start = int(n.t * rate)
        length = min(int(len(env) * per_update), len(mix) - start)
        pos = 0.0
        looping = count != 0 and le > ls
        end = le if looping else len(pcm)
        for k in range(length):
            p = int(pos)
            if p >= end:
                if not looping:
                    break
                pos -= (le - ls)
                p = int(pos)
            mix[start + k] += pcm[p] * amp * env[int(k / per_update)]
            pos += step
    # the loop: what plays after loop_end is the loop start again (tails wrap)
    ls_i = int(loop_start * rate)
    for k in range(total, len(mix)):
        j = ls_i + (k - total)
        if j < total:
            mix[j] += mix[k]
    mix = mix[:total]
    peak = max(1e-9, max(abs(v) for v in mix))
    scale = 120.0 / peak
    data = bytes((max(-127, min(127, int(round(v * scale)))) & 0xFF) for v in mix)
    pad = data[ls_i:ls_i + 2048]
    return data + pad, ls_i

#!/usr/bin/env python3
"""SM64 music sequences (.m64) to timed notes, for the demo's music import.

Plays a sequence the way the decomp's src/audio/seqplayer.c (US) does, one
tick at a time: the sequence script, then each channel's script, then the
channel's note layers. Delays, loops, calls, jumps, branches on the script
value, transposition, short and large notes, play percentages and gate
times follow seqplayer.c; what only shapes the sound (vibrato, reverb,
portamento curves, envelopes set by script) is recorded or skipped, since
the synthesizers that use these notes are approximations anyway.

Timing: ticks run at tempo * 48 / 60 per second (48 tatums per beat).

    notes, loop = play(seq_bytes)
      notes: [Note], sorted by start time
      loop:  (loop_start_s, loop_end_s) when the sequence jumps back on itself,
             else (0, end_s)

Note numbers are the game's: 0 = A0, 39 = C4 (MIDI = number + 21).
"""
import sys

TATUMS_PER_BEAT = 48
CHANNELS, LAYERS = 16, 4


class Note:
    __slots__ = ("t", "length", "chan", "bank", "instr", "note", "velocity", "volume", "pan", "drum")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def __repr__(self):
        return "Note(t=%.3f len=%.3f ch=%d inst=%d note=%d vel=%d vol=%.2f%s)" % (
            self.t, self.length, self.chan, self.instr, self.note, self.velocity, self.volume,
            " drum" if self.drum else "")


class Script:
    def __init__(self, pc):
        self.pc, self.stack, self.loops = pc, [], []


class Layer:
    def __init__(self, pc):
        self.s = Script(pc)
        self.delay = 0
        self.enabled = True
        self.transpose = 0
        self.instr = None              # None: the channel's
        self.velocity = 127            # short-note velocity
        self.note_duration = 0x80      # gate: 0..255, part of the play percentage held off
        self.play_pct = 0
        self.short_default_pct = 0x80
        self.pan = None


class Channel:
    def __init__(self, pc):
        self.s = Script(pc)
        self.enabled = True
        self.delay = 0
        self.stop_script = False
        self.layers = [None] * LAYERS
        self.instr = 0
        self.has_instr = False
        self.bank = 0
        self.transpose = 0
        self.large = False
        self.volume = 127
        self.vol_scale = 128
        self.pan = 64
        self.value = 0
        self.dyntable = None


class SeqError(Exception):
    pass


def play(data, max_seconds=600.0, bank=0):
    data = bytearray(data)  # chan_writeseq writes into it, as on the N64

    def u8(s):
        v = data[s.pc]
        s.pc += 1
        return v

    def s8(s):
        v = u8(s)
        return v - 256 if v >= 128 else v

    def u16(s):
        v = (data[s.pc] << 8) | data[s.pc + 1]
        s.pc += 2
        return v

    def var(s):  # m64_read_compressed_u16
        v = u8(s)
        if v & 0x80:
            v = ((v << 8) & 0x7F00) | u8(s)
        return v

    def common(s, cmd, value):
        """Flow-control commands shared by all three script levels; returns
        (handled, keep_going)."""
        if cmd == 0xFC:      # call
            a = u16(s)
            s.stack.append(s.pc)
            s.pc = a
        elif cmd == 0xFB:    # jump
            s.pc = u16(s)
        elif cmd == 0xF8:    # loop start, N iterations (0 = 256)
            n = u8(s)
            s.loops.append([n or 256, s.pc])
        elif cmd == 0xF7:    # loop end
            lp = s.loops[-1]
            lp[0] -= 1
            if lp[0] > 0:
                s.pc = lp[1]
            else:
                s.loops.pop()
        elif cmd in (0xFA, 0xF9, 0xF5):  # beqz, bltz, bgez on the script value
            a = u16(s)
            if (cmd == 0xFA and value == 0) or (cmd == 0xF9 and value < 0) or (cmd == 0xF5 and value >= 0):
                s.pc = a
        else:
            return False
        return True

    seq = Script(0)
    seq_delay = 0
    seq_value = 0
    seq_transpose = 0
    tempo = 120
    seq_volume = 127
    channels = [None] * CHANNELS
    short_vel = [0] * 16
    short_dur = [0] * 16
    notes = []
    t = 0.0
    ticks = 0
    first_run = {}  # sequence script address -> when it first ran
    loop = None
    seq_done = False

    def note_on(ch, ci, ly, cmd_note, gate_ticks, velocity):
        nonlocal notes
        drum = (ch.instr if ly.instr is None else ly.instr) == 0x7F  # the bank's drum kit
        n = cmd_note + ch.transpose + ly.transpose + (0 if drum else seq_transpose)
        if n >= 0x80 or n < 0:
            return
        notes.append(Note(t=t, length=gate_ticks * 60.0 / (max(1, tempo) * TATUMS_PER_BEAT), chan=ci, bank=ch.bank,
                          instr=ch.instr if ly.instr is None else ly.instr, note=n,
                          velocity=velocity, volume=(ch.volume / 127.0) * (ch.vol_scale / 128.0)
                          * (seq_volume / 127.0), pan=ch.pan if ly.pan is None else ly.pan,
                          drum=drum))

    def run_layer(ch, ci, ly):
        if not ly.enabled:
            return
        if ly.delay > 1:
            ly.delay -= 1
            return
        s = ly.s
        while True:
            cmd = u8(s)
            if cmd <= 0xC0:
                break
            if cmd == 0xFF:
                if not s.stack:
                    ly.enabled = False
                    return
                s.pc = s.stack.pop()
            elif common(s, cmd, ch.value):
                pass
            elif cmd == 0xF4:
                off = s8(s)
                s.pc += off
            elif cmd == 0xC1:
                ly.velocity = u8(s)
            elif cmd == 0xCA:
                ly.pan = u8(s)
            elif cmd == 0xC2:
                ly.transpose = s8(s)
            elif cmd == 0xC9:
                ly.note_duration = u8(s)
            elif cmd in (0xC4, 0xC5, 0xC8, 0xCC):
                pass
            elif cmd == 0xC3:
                ly.short_default_pct = var(s)
            elif cmd == 0xC6:
                ly.instr = u8(s)
            elif cmd == 0xC7:            # portamento: mode, target, time
                mode = u8(s)
                u8(s)
                if mode & 0x80:
                    u8(s)
                else:
                    var(s)
            elif cmd == 0xCB:            # envelope addr, release rate
                u16(s)
                u8(s)
            elif cmd & 0xF0 == 0xD0:
                ly.velocity = short_vel[cmd & 0xF]
            elif cmd & 0xF0 == 0xE0:
                ly.note_duration = short_dur[cmd & 0xF]
            else:
                raise SeqError("layer command %02x at %04x" % (cmd, s.pc - 1))
        if cmd == 0xC0:                  # delay: a rest
            ly.delay = var(s)
            return
        kind = cmd & 0xC0
        vel = ly.velocity
        if ch.large:
            if kind == 0x00:
                pct, vel, ly.note_duration = var(s), u8(s), u8(s)
                ly.play_pct = pct
            elif kind == 0x40:
                pct, vel = var(s), u8(s)
                ly.note_duration = 0
                ly.play_pct = pct
            else:
                pct = ly.play_pct
                vel, ly.note_duration = u8(s), u8(s)
        else:
            if kind == 0x00:
                pct = var(s)
                ly.play_pct = pct
            elif kind == 0x40:
                pct = ly.short_default_pct
            else:
                pct = ly.play_pct
        ly.delay = pct
        duration = ly.note_duration * pct // 256   # released this many ticks before the next command
        if ch.has_instr:
            note_on(ch, ci, ly, cmd - kind, max(1, pct - duration), vel)

    def run_channel(ch, ci):
        if not ch.enabled:
            return
        if ch.stop_script:
            for ly in ch.layers:
                if ly:
                    run_layer(ch, ci, ly)
            return
        if ch.delay:
            ch.delay -= 1
        s = ch.s
        if ch.delay == 0:
            while True:
                cmd = u8(s)
                if cmd == 0xFF:
                    if not s.stack:
                        ch.enabled = False
                        break
                    s.pc = s.stack.pop()
                    continue
                if cmd == 0xFE:
                    break
                if cmd == 0xFD:
                    ch.delay = var(s)
                    break
                if cmd == 0xF3:
                    ch.stop_script = True
                    break
                if cmd > 0xC0:
                    if common(s, cmd, ch.value):
                        pass
                    elif cmd == 0xF6:        # break out of a loop
                        s.loops.pop()
                    elif cmd in (0xF2, 0xE3, 0xD8, 0xD7, 0xD6, 0xD4, 0xD2, 0xD1, 0xD0, 0xD9, 0xCA):
                        u8(s)
                    elif cmd == 0xF1:
                        pass
                    elif cmd in (0xE2, 0xE1):
                        u8(s), u8(s), u8(s)
                    elif cmd == 0xE0:
                        ch.vol_scale = u8(s)
                    elif cmd == 0xDF:
                        ch.volume = u8(s)
                    elif cmd == 0xDE:
                        u16(s)
                    elif cmd == 0xDD:
                        ch.pan = u8(s)
                    elif cmd == 0xDC:
                        u8(s)
                    elif cmd == 0xDB:
                        ch.transpose = s8(s)
                    elif cmd == 0xDA:
                        u16(s)
                    elif cmd == 0xD3:
                        s8(s)
                    elif cmd == 0xCC:
                        ch.value = s8(s)
                    elif cmd == 0xC9:
                        ch.value &= u8(s)
                    elif cmd == 0xC8:
                        ch.value -= u8(s)
                    elif cmd == 0xCB:        # readseq: value = data[addr + value]
                        a = u16(s)
                        v = data[(a + ch.value) & 0xFFFF]
                        ch.value = v - 256 if v >= 128 else v
                    elif cmd == 0xC7:        # writeseq: data[addr + value] = u8
                        v = u8(s)
                        a = u16(s)
                        data[(a + ch.value) & 0xFFFF] = v
                    elif cmd == 0xC6:
                        ch.bank = u8(s)
                    elif cmd == 0xC5:
                        a = ch.dyntable + 2 * ch.value
                        ch.dyntable = (data[a] << 8) | data[a + 1]
                    elif cmd == 0xC4:
                        ch.large = True
                    elif cmd == 0xC3:
                        ch.large = False
                    elif cmd == 0xC2:
                        ch.dyntable = u16(s)
                    elif cmd == 0xC1:
                        ch.instr = u8(s)
                        ch.has_instr = True
                    elif cmd == 0xE4:        # dyncall
                        a = ch.dyntable + 2 * ch.value
                        s.stack.append(s.pc)
                        s.pc = (data[a] << 8) | data[a + 1]
                    else:
                        raise SeqError("channel command %02x at %04x" % (cmd, s.pc - 1))
                else:
                    op, lo = cmd & 0xF0, cmd & 0x0F
                    if op == 0x00:           # testlayerfinished
                        ly = ch.layers[lo]
                        ch.value = 1 if (ly is None or not ly.enabled) else 0
                    elif op == 0x10:         # startchannel
                        a = u16(s)
                        channels[lo] = Channel(a)
                    elif op == 0x20:         # disablechannel
                        if channels[lo]:
                            channels[lo].enabled = False
                    elif op == 0x30:
                        u8(s)
                    elif op == 0x40:
                        u8(s)
                        ch.value = 0
                    elif op in (0x50, 0x80):  # io reads: nothing written them
                        ch.value = -1 if op == 0x80 else ch.value
                    elif op in (0x60, 0x70):
                        pass
                    elif op == 0x90:         # setlayer
                        ch.layers[lo] = Layer(u16(s))
                    elif op == 0xA0:         # freelayer
                        ch.layers[lo] = None
                    elif op == 0xB0:         # dynsetlayer
                        a = ch.dyntable + 2 * ch.value
                        ch.layers[lo] = Layer((data[a] << 8) | data[a + 1])
                    else:
                        raise SeqError("channel command %02x at %04x" % (cmd, s.pc - 1))
        for ly in ch.layers:
            if ly:
                run_layer(ch, ci, ly)

    while t < max_seconds and not seq_done:
        # the sequence script
        if seq_delay > 1:
            seq_delay -= 1
        else:
            while True:
                first_run.setdefault(seq.pc, t)
                cmd = u8(seq)
                if cmd == 0xFF:
                    if not seq.stack:
                        seq_done = True
                        break
                    seq.pc = seq.stack.pop()
                elif cmd == 0xFE:
                    seq_delay = 1
                    break
                elif cmd == 0xFD:
                    seq_delay = var(seq)
                    break
                elif cmd == 0xFB:               # jump: loop detection
                    a = (data[seq.pc] << 8) | data[seq.pc + 1]
                    if a < seq.pc and a in first_run:   # back to where it's been: the loop
                        loop = (first_run[a], t)
                        seq_done = True
                        break
                    seq.pc = a
                elif common(seq, cmd, seq_value):
                    pass
                elif cmd in (0xF2, 0xD5, 0xD3, 0xD0):
                    u8(seq)
                elif cmd in (0xF1, 0xD4):
                    pass
                elif cmd == 0xDF:
                    seq_transpose = s8(seq)
                elif cmd == 0xDE:
                    seq_transpose += s8(seq)
                elif cmd == 0xDD:
                    tempo = u8(seq)
                elif cmd == 0xDC:
                    tempo += s8(seq)
                elif cmd == 0xDB:
                    seq_volume = u8(seq)
                elif cmd == 0xDA:
                    seq_volume += s8(seq)
                elif cmd in (0xD7, 0xD6):
                    u16(seq)
                elif cmd == 0xD2:
                    a = u16(seq)
                    short_vel[:] = data[a:a + 16]
                elif cmd == 0xD1:
                    a = u16(seq)
                    short_dur[:] = data[a:a + 16]
                elif cmd == 0xCC:
                    seq_value = s8(seq)
                elif cmd == 0xC9:
                    seq_value &= u8(seq)
                elif cmd == 0xC8:
                    seq_value -= u8(seq)
                elif cmd & 0xF0 == 0x00:        # testchdisabled
                    c = channels[cmd & 0xF]
                    seq_value = 1 if (c is None or not c.enabled) else 0
                elif cmd & 0xF0 in (0x50, 0x70, 0x80):
                    if cmd & 0xF0 == 0x80:
                        seq_value = 0
                elif cmd & 0xF0 == 0x90:        # startchannel
                    channels[cmd & 0xF] = Channel(u16(seq))
                else:
                    raise SeqError("sequence command %02x at %04x" % (cmd, seq.pc - 1))
        if seq_done:
            break
        for i, ch in enumerate(channels):
            if ch:
                run_channel(ch, i)
        ticks += 1
        t += 60.0 / (max(1, tempo) * TATUMS_PER_BEAT)

    if loop is None:
        loop = (0.0, t)
    return sorted(notes, key=lambda n: n.t), loop


if __name__ == "__main__":
    notes, loop = play(open(sys.argv[1], "rb").read())
    print("%d notes, loop %.2f..%.2f s" % (len(notes), loop[0], loop[1]))
    for n in notes[:40]:
        print(n)

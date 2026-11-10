#!/usr/bin/env python3
"""Exercise title/save controls across separate boots of the real GBA ROM."""
import argparse
from contextlib import nullcontext
import struct
import subprocess
import zlib
from pathlib import Path

OFFSET, STRIDE, SIZE = 4096, 128, 96


def decode(blob):
    records = []
    for slot in range(2):
        b = blob[OFFSET + slot * STRIDE:OFFSET + slot * STRIDE + SIZE]
        if len(b) != SIZE or b[:8] != b"SMGB\x01\0\0\0":
            continue
        if zlib.crc32(b[4:92]) != struct.unpack_from("<I", b, 92)[0]:
            continue
        sequence = struct.unpack_from("<I", b, 8)[0]
        records.append(dict(slot=slot, sequence=sequence, level=b[12], lives=b[13], visited=b[14],
                            coins=b[16:64], best=struct.unpack_from("<4H", b, 64)))
    if not records:
        return None
    return max(records, key=lambda r: r["sequence"])


def fixture():
    ram = bytearray(b"\xFF" * 32768)
    b = bytearray(SIZE)
    b[:8] = b"SMGB\x01\0\0\0"
    struct.pack_into("<I", b, 8, 10)
    b[12:15] = bytes([2, 3, 7])
    b[16] = 5
    struct.pack_into("<4H", b, 64, 17, 8, 0, 0)
    struct.pack_into("<I", b, 92, zlib.crc32(b[4:92]))
    ram[OFFSET:OFFSET + SIZE] = b
    return ram


def run(args, directory, name, keys, save=None, frames=420):
    key_path, out = directory / (name + ".keys"), directory / (name + ".sav")
    key_path.write_text(keys)
    command = [args.runner, args.rom, "--title-keys", "--frames", str(frames), "--keys", str(key_path), "--save-out", str(out)]
    if save:
        command += ["--save-in", str(save)]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    (directory / (name + ".log")).write_text(result.stdout)
    return out, decode(out.read_bytes()), result.stdout


def check(ok, message):
    if not ok:
        raise SystemExit("FAIL: " + message)
    print("PASS: " + message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", default="build/mgba_runner")
    parser.add_argument("--rom", default="build/demo/sm64demo.gba")
    parser.add_argument("--out", default="build/save-check")
    args = parser.parse_args()
    with nullcontext(args.out) as tmp:
        d = Path(tmp)
        d.mkdir(parents=True, exist_ok=True)
        out, state, log = run(args, d, "new", "30 36 S\n")
        check("title ready" in log and "game new" in log and state is not None and state["level"] == 0,
              "Start begins and saves a fresh game")
        out, resumed, log = run(args, d, "roundtrip", "30 36 A\n", out, frames=260)
        check("game continue" in log and resumed["level"] == state["level"] and resumed["lives"] == state["lives"],
              "a save created by the ROM continues in a separate emulator process")
        out, state, log = run(args, d, "return-title", "30 36 S\n220 230 LRS\n340 346 A\n", frames=600)
        check(log.count("title ready") == 2 and "game continue" in log and state["level"] == 0,
              "L+R+Start returns to the title and Continue resumes the checkpoint")
        seed = d / "seed.sav"
        seed.write_bytes(fixture())
        out, state, log = run(args, d, "continue", "30 36 A\n", seed, frames=260)
        check("game continue" in log and state["level"] == 2 and state["lives"] == 3,
              "Continue restores the last level and lives after a power cycle")
        check(state["coins"][0] == 5 and state["best"][0] == 17,
              "collected coins and best coin counts survive another boot")
        out, state, log = run(args, d, "cancel", "30 36 S\n50 56 B\n80 86 A\n", seed, frames=300)
        check("title confirm" in log and "game continue" in log and "game new" not in log and state["level"] == 2,
              "canceling New Game preserves the existing checkpoint")
        out, state, log = run(args, d, "replace", "30 36 S\n50 56 A\n", seed)
        check("title confirm" in log and "game new" in log and state["level"] == 0
              and state["lives"] == 4 and not any(state["coins"]) and state["best"] == (0, 0, 0, 0),
              "confirmed New Game resets the whole saved profile")
        # Hold Start through loading: the title press must not also advance
        # to the next demo level on the first gameplay frame.
        out, state, log = run(args, d, "held-start", "30 250 S\n", frames=350)
        check(state["level"] == 0, "holding Start through loading does not skip the first level")
        # The oldest complete slot remains valid if the newer copy is torn.
        blob = bytearray(out.read_bytes())
        newest = decode(blob)
        blob[OFFSET + newest["slot"] * STRIDE + 20] ^= 0x80
        damaged = d / "damaged.sav"
        damaged.write_bytes(blob)
        out, state, log = run(args, d, "recover", "30 36 A\n", damaged)
        check("game continue" in log and state is not None and state["level"] == 0,
              "a damaged newest record falls back to the previous complete save")
    print("PASS: title and save integration checks")


if __name__ == "__main__":
    main()

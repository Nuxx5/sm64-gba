#!/usr/bin/env python3
"""End-to-end physics check for the playable demo.

Plays a key script in the demo ROM (mGBA), takes the exact controller inputs
the demo fed Mario each frame (its "i ..." debug lines: stick, buttons, camera
yaw) and replays them through the host reference harness. Mario's position
after every frame must match bit for bit.

With --expect hurt / --expect stomp the run must also contain that event
(Mario's health drops / a Goomba is removed while Mario is near it), so a key
script whose route drifts (it is timed in GBA frames, and the demo's frame
rate changes with its code) fails instead of quietly testing nothing.

Usage: demo_physics_check.py --runner R --rom ROM --harness H --keys F --frames N [--level bob]
                             [--expect hurt|stomp ...]
"""
import argparse
import os
import subprocess
import sys
import tempfile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner", required=True)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--harness", required=True)
    ap.add_argument("--keys", required=True)
    ap.add_argument("--frames", type=int, default=1800)
    ap.add_argument("--level", default="bob")
    ap.add_argument("--expect", action="append", default=[], choices=["hurt", "stomp"])
    args = ap.parse_args()

    run = subprocess.run([args.runner, args.rom, "--frames", str(args.frames), "--keys", args.keys],
                         capture_output=True, text=True, timeout=1800)
    inputs, demo_pos, health, goombas = [], [], [], []
    for line in run.stdout.splitlines():
        if line.startswith("f "):
            kv = line.split()
            stats = dict(zip(kv[0::2], kv[1::2]))
            if "H" in stats:
                health.append(int(stats["H"], 16))
            if "G" in stats:
                goombas.append(int(stats["G"], 16))
        if line.startswith("i "):
            left, right = line[2:].split("|")
            raw_x, raw_y, buttons, cam_yaw = left.split()
            inputs.append(f"{raw_x} {raw_y} {buttons} {cam_yaw}")
            demo_pos.append(right.split())
    if not inputs:
        sys.exit("no input lines from the demo (is it a debug-enabled mGBA run?)")

    with tempfile.NamedTemporaryFile("w", suffix=".inp", delete=False) as f:
        f.write(f"level {args.level}\n" + "\n".join(inputs) + "\n")
        inp = f.name
    with open(inp) as f:
        ref = subprocess.run([args.harness], stdin=f, capture_output=True, text=True).stdout
    os.unlink(inp)
    ref_pos = [l.split()[4:7] for l in ref.splitlines() if l and l[0].isdigit()][1:]

    moved = sum(1 for i in range(1, len(demo_pos)) if demo_pos[i] != demo_pos[i - 1])
    for i, (d, r) in enumerate(zip(demo_pos, ref_pos)):
        if d != r:
            print(f"FAIL: frame {i}: demo {d} reference {r} (input {inputs[i]})")
            sys.exit(1)
    events = []
    for e in args.expect:
        if e == "hurt":
            ok = any(b < a for a, b in zip(health, health[1:]))
            what = "Mario's health never dropped"
        else:
            ok = any(b < a for a, b in zip(goombas, goombas[1:]))
            what = "no Goomba was removed"
        if not ok:
            print(f"FAIL: expected '{e}' but {what}: the key script's route missed the enemy")
            sys.exit(1)
        events.append(e)
    print(f"PASS: {len(demo_pos)} demo frames, Mario's position bit-identical to the reference "
          f"harness on every frame ({moved} frames with movement)"
          + (f", events seen: {', '.join(events)}" if events else ""))


if __name__ == "__main__":
    main()

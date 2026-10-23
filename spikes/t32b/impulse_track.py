#!/usr/bin/env python3
"""Génère la piste d'impulsions du protocole de latence double saut (#8) : N clics espacés de `period` secondes.

La piste est jouée par la SOURCE (PC) vers btmux ; un enregistreur externe stéréo capte (canal 0) la sortie directe de la source et
(canal 1) la sortie du casque ; `analyze_latency.py` calcule le délai entre les deux canaux pour chaque clic.
Usage : impulse_track.py --out clicks.wav [--count 20] [--period 2.0] [--rate 48000]
Provisoire — à valider avec les dongles UB500 (T3.2b).
"""

from __future__ import annotations

import argparse
import array
import math
import wave


def make_clicks(count: int, period: float, rate: int) -> array.array:
    samples = array.array("h", [0] * int(rate * period * (count + 1)))
    click = [
        int(20000 * math.sin(2 * math.pi * 2000 * i / rate) * (1 - i / 120)) for i in range(120)
    ]
    for n in range(count):
        start = int(rate * period * (n + 1))
        samples[start : start + len(click)] = array.array("h", click)
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--period", type=float, default=2.0)
    parser.add_argument("--rate", type=int, default=48000)
    args = parser.parse_args()
    samples = make_clicks(args.count, args.period, args.rate)
    with wave.open(args.out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(args.rate)
        wav.writeframes(samples.tobytes())
    print(f"{args.count} clics toutes les {args.period} s -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

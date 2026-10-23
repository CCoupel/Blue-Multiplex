#!/usr/bin/env python3
"""Mesure la latence entre deux canaux d'un enregistrement stéréo : canal 0 = référence (sortie directe), canal 1 = sortie casque.

Détecte l'attaque de chaque impulsion (seuil relatif au pic, période réfractaire 0,5 s), apparie les clics par ordre et calcule le
délai en ms. Usage : analyze_latency.py enregistrement.wav [--threshold 0.3] [--out stats.json]. Provisoire — T3.2b.
"""

from __future__ import annotations

import argparse
import array
import json
import statistics
import wave


def onsets(
    samples: list[int], rate: int, threshold: float = 0.3, refractory: float = 0.5
) -> list[float]:
    peak = max((abs(s) for s in samples), default=0)
    if peak == 0:
        return []
    limit, gap, found, last = threshold * peak, int(refractory * rate), [], -(10**12)
    for i, value in enumerate(samples):
        if abs(value) >= limit and i - last >= gap:
            found.append(i / rate)
            last = i
    return found


def delays_ms(reference: list[float], delayed: list[float]) -> list[float]:
    """Pour chaque clic de référence, délai jusqu'au clic suivant du second canal (ms)."""
    out = []
    for t in reference:
        later = [d for d in delayed if d >= t - 0.001]
        if later:
            out.append((later[0] - t) * 1000)
    return out


def stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
    return {
        "n": len(values),
        "min": ordered[0],
        "median": statistics.median(values),
        "p95": p95,
        "max": ordered[-1],
    }


def analyze(path: str, threshold: float = 0.3) -> dict[str, float]:
    with wave.open(path, "rb") as wav:
        channels, rate, frames = (
            wav.getnchannels(),
            wav.getframerate(),
            wav.readframes(wav.getnframes()),
        )
    if channels < 2:
        raise SystemExit(
            "l'enregistrement doit être stéréo (canal 0 = référence, canal 1 = casque)"
        )
    data = array.array("h")
    data.frombytes(frames)
    ref = onsets(list(data[0::channels]), rate, threshold)
    out = onsets(list(data[1::channels]), rate, threshold)
    return stats(delays_ms(ref, out))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav")
    parser.add_argument("--threshold", type=float, default=0.3)
    parser.add_argument("--out")
    args = parser.parse_args()
    result = analyze(args.wav, args.threshold)
    print(json.dumps(result, indent=1))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

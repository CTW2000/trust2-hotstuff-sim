"""The threshold of the leader rule, from 10^2 to 10^4, on both sides of the trade (DESIGN.md 15.45): the runs of
probe51.py (lateness by sender, threshold 10^2), probe52.py (the same at 10^4; three silent leaders at both) and
probe53.py (300 and 10^3 on both sides, with 10^2 again for the silent leaders).
- Lateness by sender, per share and threshold: honest leads, AT per thousand leads, honest leaders convicted, leads
  per conviction, the highest CUSUM against the threshold, the voting weight cut from honest members at the end.
- Silent leaders, per batch and threshold: timeouts, rounds per second, latencies, accusations and exclusions of the
  silent nodes; each threshold against the 10^2 of its own batch (exact rank-sum test, relative difference of the
  medians, bootstrap 95%).
With tarballs of kept logs as further arguments: when each exclusion of a run happened (round, seconds from the
first block), from node 0's log. Standard library only.
Run from prototype/benchmark/:  python3 thrstat.py [results-probe52/threshold_logs/silent-*.tgz]
"""
import csv
import os
import random
import re
import sys
import tarfile
from datetime import datetime
from statistics import median

import cmpgstat as C
import stats_a4 as A

LN = {"0": ("10^2", 4_605_170), "5703782": ("300", 5_703_782), "6907755": ("10^3", 6_907_755),
      "9210340": ("10^4", 9_210_340)}
BATCHES = ("results-probe51/slots_rate.csv", "results-probe52/threshold.csv", "results-probe53/threshold.csv")


def num(rows, key):
    return [float(r.get(key) or 0) for r in rows]


def mr(xs, d=0):
    lo, hi, m = min(xs), max(xs), median(xs)
    return f"{m:.{d}f}" if lo == hi else f"{m:.{d}f} [{lo:.{d}f}-{hi:.{d}f}]"


def load(path):
    return list(csv.DictReader(open(path))) if os.path.exists(path) else []


def tables():
    rows = [r for path in BATCHES for r in load(path)]
    slots = [r for r in rows if r["scenario"].startswith("slots")]
    print(f"## Lateness by sender: {len(slots)} runs\n")
    print("| late share | threshold | runs | rounds/s | honest leads | AT per 1000 leads | convictions (per run) | "
          "leads per conviction | CUSUM peak / threshold | honest cut % |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for share in sorted({float(r["late_p"]) for r in slots}):
        for key, (name, threshold) in LN.items():
            g = [r for r in slots if float(r["late_p"]) == share and (r.get("g2_threshold") or "0") == key]
            if not g:
                continue
            leads, at, conv = sum(num(g, "honest_leads")), sum(num(g, "honest_accusations")), sum(num(g, "honest_convictions"))
            per = f"{leads / conv:.0f}" if conv else f"none in {leads:.0f}"
            print(f"| {100 * share:.0f}% | {name} | {len(g)} | {mr(num(g, 'rounds_per_s'), 1)} | {leads:.0f} | "
                  f"{1000 * at / leads:.1f} | {conv:.0f} ({mr(num(g, 'honest_convictions'))}) | {per} | "
                  f"{mr([x / threshold for x in num(g, 'honest_cusum_peak_ppm')], 2)} | "
                  f"{mr([100 * x for x in num(g, 'honest_cut')], 2)} |")
    keys = (("timeouts", 0), ("rounds_per_s", 1), ("consensus_latency_ms", 0), ("e2e_latency_ms", 0),
            ("accusations_faulty", 0), ("g2_excluded_faulty", 0), ("honest_accusations", 0), ("honest_convictions", 0))
    rnd = random.Random(7)
    for path in BATCHES:
        silent = [r for r in load(path) if r["scenario"] == "silent"]
        if not silent:
            continue
        arm = {key: [r for r in silent if (r.get("g2_threshold") or "0") == key] for key in LN}
        others = [key for key in LN if key != "0" and arm[key]]
        print(f"\n## Three silent leaders, {path}: {len(silent)} runs\n")
        print("| metric | 10^2 | " + " | ".join(f"{LN[k][0]} | p | against 10^2" for k in others) + " |")
        print("|---|---|" + "---|---|---|" * len(others))
        for key, d in keys:
            a = num(arm["0"], key)
            cells = []
            for other in others:
                b = num(arm[other], key)
                rel = ""
                if median(a) > 0:
                    try:
                        lo, hi = A.boot([(b, a)], rnd)
                        rel = f"{100 * A.rel(b, a):+.1f}% [{100 * lo:+.1f}%, {100 * hi:+.1f}%]"
                    except ZeroDivisionError:
                        rel = f"{100 * A.rel(b, a):+.1f}%"
                cells.append(f"{mr(b, d)} | {C.ranksum_p(a, b):.3f} | {rel}")
            print(f"| {key} | {mr(a, d)} | " + " | ".join(cells) + " |")


def when(paths):
    stamp = lambda line: datetime.strptime(line[1:24], "%Y-%m-%dT%H:%M:%S.%f").timestamp()
    print("\n## When the exclusions happened (round, seconds from the first block; node 0's log)\n")
    for path in sorted(paths):
        with tarfile.open(path) as tar:
            text = tar.extractfile("logs/node-0.log").read().decode(errors="replace")
        first, out = None, []
        for line in text.splitlines():
            if first is None and "Committed B" in line:
                first = stamp(line)
            m = re.search(r"G2: (\S+) excluded from leading at round (\d+)", line)
            if m and first is not None:
                out.append(f"{m.group(2)} / {stamp(line) - first:.0f} s")
        print(f"- {os.path.basename(path)}: " + (", ".join(out) or "none"))


if __name__ == "__main__":
    tables()
    if len(sys.argv) > 1:
        when(sys.argv[1:])

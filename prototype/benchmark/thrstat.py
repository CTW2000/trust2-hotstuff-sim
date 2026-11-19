"""The threshold of the leader rule, 10^2 against 10^4, on both sides of the trade (DESIGN.md 15.45): the runs of
probe51.py (lateness by sender, threshold 10^2) and probe52.py (the same at 10^4; three silent leaders at both).
- Lateness by sender, per share and threshold: honest leads, AT per thousand leads, honest leaders convicted, leads
  per conviction, the highest CUSUM against the threshold, the voting weight cut from honest members at the end.
- Silent leaders, per threshold: timeouts, rounds per second, latencies, accusations and exclusions of the silent
  nodes; then 10^4 against 10^2 (exact rank-sum test, relative difference of the medians, bootstrap 95%).
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

LN = {"0": ("10^2", 4_605_170), "9210340": ("10^4", 9_210_340)}


def num(rows, key):
    return [float(r.get(key) or 0) for r in rows]


def mr(xs, d=0):
    lo, hi, m = min(xs), max(xs), median(xs)
    return f"{m:.{d}f}" if lo == hi else f"{m:.{d}f} [{lo:.{d}f}-{hi:.{d}f}]"


def load(path):
    return list(csv.DictReader(open(path))) if os.path.exists(path) else []


def tables():
    rows = load("results-probe51/slots_rate.csv") + load("results-probe52/threshold.csv")
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
    silent = [r for r in rows if r["scenario"] == "silent"]
    if not silent:
        return
    print(f"\n## Three silent leaders: {len(silent)} runs\n")
    keys = (("timeouts", 0), ("rounds_per_s", 1), ("consensus_latency_ms", 0), ("e2e_latency_ms", 0),
            ("accusations_faulty", 0), ("g2_excluded_faulty", 0), ("honest_accusations", 0), ("honest_convictions", 0))
    arm = {key: [r for r in silent if (r.get("g2_threshold") or "0") == key] for key in LN}
    print("| metric | 10^2 | 10^4 | p | 10^4 against 10^2 |")
    print("|---|---|---|---|---|")
    rnd = random.Random(7)
    for key, d in keys:
        a, b = num(arm["0"], key), num(arm["9210340"], key)
        if not a or not b:
            continue
        rel = ""
        if median(a) > 0:
            try:
                lo, hi = A.boot([(b, a)], rnd)
                rel = f"{100 * A.rel(b, a):+.1f}% [{100 * lo:+.1f}%, {100 * hi:+.1f}%]"
            except ZeroDivisionError:
                rel = f"{100 * A.rel(b, a):+.1f}%"
        print(f"| {key} | {mr(a, d)} | {mr(b, d)} | {C.ranksum_p(a, b):.3f} | {rel} |")


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

"""The runs of probe54.py (DESIGN.md 15.49): the leader rule with one observation per led view (window 0) against
one per episode (--g2-window 25 and 50). Lateness by sender, per share and window: honest leads, AT per thousand
leads, honest leaders convicted and leads per conviction, the highest CUSUM against the threshold ln 300, the weight
cut from honest members. Three silent leaders, per window: timeouts, rounds per second, latencies, accusations and
exclusions of the silent nodes, each window against 0 (exact rank-sum test, relative difference of the medians).
With tarballs of kept logs of the silent runs as arguments: when each exclusion happened. Standard library only.
Run from prototype/benchmark/:  python3 winstat.py [results-probe54/window_logs/silent-*.tgz]
"""
import csv
import random
import sys
from statistics import median

import cmpgstat as C
import stats_a4 as A
import thrstat as T

THRESHOLD = 5_703_782       # ln 300


def main(path="results-probe54/window.csv"):
    rows = list(csv.DictReader(open(path)))
    win = lambda r: int(float(r.get("g2_window") or 0))
    windows = sorted({win(r) for r in rows})
    slots = [r for r in rows if r["scenario"].startswith("slots")]
    print(f"## Lateness by sender: {len(slots)} runs\n")
    print("| late share | window | runs | rounds/s | honest leads | AT per 1000 leads | convictions (per run) | "
          "leads per conviction | CUSUM peak / threshold | honest cut % |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for share in sorted({float(r["late_p"]) for r in slots}):
        for w in windows:
            g = [r for r in slots if float(r["late_p"]) == share and win(r) == w]
            if not g:
                continue
            leads, at, conv = (sum(T.num(g, k)) for k in ("honest_leads", "honest_accusations", "honest_convictions"))
            per = f"{leads / conv:.0f}" if conv else f"none in {leads:.0f}"
            print(f"| {100 * share:.0f}% | {w} | {len(g)} | {T.mr(T.num(g, 'rounds_per_s'), 1)} | {leads:.0f} | "
                  f"{1000 * at / leads:.1f} | {conv:.0f} ({T.mr(T.num(g, 'honest_convictions'))}) | {per} | "
                  f"{T.mr([x / THRESHOLD for x in T.num(g, 'honest_cusum_peak_ppm')], 2)} | "
                  f"{T.mr([100 * x for x in T.num(g, 'honest_cut')], 2)} |")
    silent = [r for r in rows if r["scenario"] == "silent"]
    if silent:
        keys = (("timeouts", 0), ("rounds_per_s", 1), ("consensus_latency_ms", 0), ("e2e_latency_ms", 0),
                ("accusations_faulty", 0), ("g2_excluded_faulty", 0), ("honest_convictions", 0))
        arm = {w: [r for r in silent if win(r) == w] for w in windows}
        others = [w for w in windows if w != 0 and arm[w]]
        rnd = random.Random(7)
        print(f"\n## Three silent leaders: {len(silent)} runs\n")
        print("| metric | window 0 | " + " | ".join(f"window {w} | p | against 0" for w in others) + " |")
        print("|---|---|" + "---|---|---|" * len(others))
        for key, d in keys:
            a = T.num(arm[0], key)
            cells = []
            for w in others:
                b = T.num(arm[w], key)
                rel = ""
                if median(a) > 0:
                    try:
                        lo, hi = A.boot([(b, a)], rnd)
                        rel = f"{100 * A.rel(b, a):+.1f}% [{100 * lo:+.1f}%, {100 * hi:+.1f}%]"
                    except ZeroDivisionError:
                        rel = f"{100 * A.rel(b, a):+.1f}%"
                cells.append(f"{T.mr(b, d)} | {C.ranksum_p(a, b):.3f} | {rel}")
            print(f"| {key} | {T.mr(a, d)} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
    if len(sys.argv) > 1:
        T.when(sys.argv[1:])

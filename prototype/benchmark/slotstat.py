"""From which share of lateness by sender on does the leader rule exclude honest leaders (DESIGN.md 15.45)? The runs
of probe51.py, per share: rounds per second and timeouts, the leads of honest nodes, the AT accusations against
them per thousand leads, the convictions and the leads per conviction, the highest value a CUSUM reached against the
threshold ln 10^2 = 4.605, and the voting weight cut from honest members at the end. Standard library only.
Run from prototype/benchmark/:  python3 slotstat.py [results-probe51/slots_rate.csv]
"""
import csv
import sys
from statistics import median

THRESHOLD = 4_605_170      # ln 10^2, the protocol's threshold when probe51.py ran (ln 300 since 2026-11-22)


def num(rows, key):
    return [float(r.get(key) or 0) for r in rows]


def mr(xs, d=0):
    lo, hi, m = min(xs), max(xs), median(xs)
    return f"{m:.{d}f}" if lo == hi else f"{m:.{d}f} [{lo:.{d}f}-{hi:.{d}f}]"


def main(path):
    rows = list(csv.DictReader(open(path)))
    print(f"## {path}: {len(rows)} runs\n")
    print("| late share | runs | rounds/s | timeouts | e2e ms | honest leads | AT per 1000 leads | convictions "
          "(per run) | nodes convicted (per run) | leads per conviction | CUSUM peak / threshold | honest cut % |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for share in sorted({float(r["late_p"]) for r in rows}):
        g = [r for r in rows if float(r["late_p"]) == share]
        leads, at, conv = sum(num(g, "honest_leads")), sum(num(g, "honest_accusations")), sum(num(g, "honest_convictions"))
        per_conv = f"{leads / conv:.0f}" if conv else f"none in {leads:.0f}"
        print(f"| {100 * share:.0f}% | {len(g)} | {mr(num(g, 'rounds_per_s'), 1)} | {mr(num(g, 'timeouts'))} | "
              f"{mr(num(g, 'e2e_latency_ms'))} | {leads:.0f} | {1000 * at / leads:.1f} | {conv:.0f} "
              f"({mr(num(g, 'honest_convictions'))}) | {mr(num(g, 'honest_convicted_nodes'))} | {per_conv} | "
              f"{mr([x / THRESHOLD for x in num(g, 'honest_cusum_peak_ppm')], 2)} | "
              f"{mr([100 * x for x in num(g, 'honest_cut')], 2)} |")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results-probe51/slots_rate.csv")

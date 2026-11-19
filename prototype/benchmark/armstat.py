"""Three ways of sending votes, side by side (DESIGN.md 15.45): to the next leader, to all members, to all members
with the QC forwarded to the next leader. Reads a batch whose rows carry broadcast_votes and forward_qc (probe49.py,
probe50.py). Per scenario and rule: medians [range] of each arm, then the pairs, with the exact two-sided rank-sum
test and the relative difference of the medians with a bootstrap 95% interval. Standard library only.
Run from prototype/benchmark/:  python3 armstat.py results-probe49/cmp_corr.csv
"""
import csv
import random
import sys
from statistics import median

import cmpgstat as C
import stats_a4 as A

ARMS = (("next", ("False", "False")), ("all", ("True", "False")), ("fwd", ("True", "True")))
METRICS = (("timeouts", 0), ("rounds_per_s", 1), ("consensus_latency_ms", 0), ("e2e_latency_ms", 0),
           ("accusations_honest", 0), ("g2_excluded_honest", 0), ("cores", 2), ("throttled_pct", 1), ("lo_mb_s", 1))
ZERO = ("accusations_honest", "g2_excluded_honest")      # an empty cell is a count of zero


def col(rows, key):
    if key in ZERO:
        return [float(r.get(key) or 0) for r in rows]
    return C.col(rows, key)


def main(path):
    rows = list(csv.DictReader(open(path)))
    cells = sorted({(r["scenario"], r["leader_rule"]) for r in rows})
    rnd = random.Random(7)
    print(f"## {path}: {len(rows)} runs\n")
    for sc, rule in cells:
        arm = {name: [r for r in rows if r["scenario"] == sc and r["leader_rule"] == rule
                      and (r["broadcast_votes"], r.get("forward_qc") or "False") == flags] for name, flags in ARMS}
        metrics = [(k, d) for k, d in METRICS if any(col(g, k) for g in arm.values()) or k in ZERO]
        print(f"### {sc}, rule {rule} ({' / '.join(str(len(arm[a])) for a, _ in ARMS)} runs)\n")
        print("| metric | next | all | fwd |")
        print("|---|---|---|---|")
        for key, d in metrics:
            print(f"| {key} | " + " | ".join(C.mr(col(arm[a], key), d) for a, _ in ARMS) + " |")
        print()
        for ref, other in (("next", "all"), ("next", "fwd"), ("all", "fwd")):
            parts = []
            for key, d in metrics:
                a, b = col(arm[ref], key), col(arm[other], key)
                if not a or not b:
                    continue
                part = f"{key} p={C.ranksum_p(a, b):.3f}"
                if median(a) > 0:
                    try:
                        lo, hi = A.boot([(b, a)], rnd)
                        part += f" {100 * A.rel(b, a):+.1f}% [{100 * lo:+.1f}%, {100 * hi:+.1f}%]"
                    except ZeroDivisionError:
                        part += f" {100 * A.rel(b, a):+.1f}%"
                parts.append(part)
            print(f"- {other} against {ref}: " + "; ".join(parts))
        print()


if __name__ == "__main__":
    main(sys.argv[1])

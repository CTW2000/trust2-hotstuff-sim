"""The numbers of the paper's leader-rule comparison (Table 4 and its paragraph) from a cmpg run.

Per scenario and rule: timeouts, rounds per second and end-to-end latency (median and range of the runs), and what
each rule did to honest leaders -- for the Aptos-style rule the share of honest (and faulty) member-epochs at the
failed weight, for the other rules the facts recorded against honest leaders and the leaders excluded. Then the
comparisons the text cites: exact two-sided rank-sum tests against Trust 2.0, and the relative difference of the
medians with a bootstrap 95% interval (as stats_a4.py). Standard library only.
Run from prototype/benchmark/:  python3 cmpgstat.py [results-p5/cmpg.csv]
"""
import csv
import random
import sys
from itertools import combinations
from statistics import mean, median

import stats_a4 as A

NODES = 31
FAULTY = {"silent": 3, "late": 0, "framers+late": 6}
EARLIER = {"9210340": "@1e4", "4605170": "@1e2"}      # the protocol's threshold until 2026-11-05 and 2026-11-22


def col(rows, key):
    return [float(r[key]) for r in rows if r.get(key) not in (None, "")]


def mr(xs, d=0):
    if not xs:
        return "-"
    lo, hi, m = min(xs), max(xs), median(xs)
    return f"{m:.{d}f}" if lo == hi else f"{m:.{d}f} [{lo:.{d}f}-{hi:.{d}f}]"


def ranksum_p(a, b):
    """Exact two-sided rank-sum test (midranks for ties): the share of the splits of the pooled sample whose rank sum
    is at least as far from its mean as the observed one."""
    pool = sorted(a + b)
    rank = {}
    for v in set(pool):
        idx = [i + 1 for i, x in enumerate(pool) if x == v]
        rank[v] = sum(idx) / len(idx)
    ranks = [rank[v] for v in a] + [rank[v] for v in b]
    centre = len(a) * (len(ranks) + 1) / 2
    obs = abs(sum(ranks[:len(a)]) - centre)
    hits = total = 0
    for pick in combinations(range(len(ranks)), len(a)):
        total += 1
        hits += abs(sum(ranks[i] for i in pick) - centre) >= obs - 1e-9
    return hits / total


def main(path):
    rows = list(csv.DictReader(open(path)))
    cell = {}
    for r in rows:
        rule = r["leader_rule"] + EARLIER.get(r["g2_threshold"], "")
        cell.setdefault((r["scenario"], rule), []).append(r)
    print(f"## {path}: {len(rows)} runs\n")
    print("| scenario | rule | timeouts | rounds/s | e2e ms | against honest leaders | excluded honest / faulty |")
    print("|---|---|---|---|---|---|---|")
    for (sc, rule), g in cell.items():
        honest = NODES - FAULTY[sc]
        what, excl = "-", "-"
        if rule == "aptos":
            # Member-epochs over members x (epochs - 1): a run builds epochs + 1 tables and the first two come from
            # genesis, where the Aptos history is empty (DESIGN.md §15.12).
            hs = [100 * float(r["aptos_failed_honest"] or 0) / (honest * (float(r["epochs"]) - 1)) for r in g]
            what = f"failed weight: {mr(col(g, 'aptos_failed_honest'))} member-epochs, {mr(hs)}% of honest"
            if FAULTY[sc]:
                fs = [100 * float(r["aptos_failed_faulty"] or 0) / (FAULTY[sc] * (float(r["epochs"]) - 1)) for r in g]
                what += f"; faulty {mr(fs)}%"
        elif rule == "failed":
            what = f"failed proposals {mr([float(r['failed_facts_honest'] or 0) for r in g])}"
        elif rule.startswith("trust2"):
            what = f"AT {mr([float(r['accusations_honest'] or 0) for r in g])}"
        if rule != "none" and rule != "aptos":
            eh = [float(r["g2_excluded_honest"] or 0) for r in g]
            ef = [float(r["g2_excluded_faulty"] or 0) for r in g]
            excl = f"{mr(eh)} / {mr(ef)} (means {mean(eh):.1f} / {mean(ef):.1f}); honest cut {mr([100 * x for x in col(g, 'honest_cut')], 2)}%"
        print(f"| {sc} | {rule} | {mr(col(g, 'timeouts'))} | {mr(col(g, 'rounds_per_s'), 1)} | "
              f"{mr(col(g, 'e2e_latency_ms'))} | {what} | {excl} |")
    print("\n## Against Trust 2.0 (exact two-sided rank-sum test; relative difference of medians, bootstrap 95%)\n")
    rnd = random.Random(7)
    for sc in FAULTY:
        if (sc, "trust2") not in cell:      # a batch with fewer scenarios (probe48.py)
            continue
        ref = cell[(sc, "trust2")]
        for rule in ("none", "aptos", "failed", "trust2@1e2", "trust2@1e4"):
            g = cell.get((sc, rule))
            if not g:
                continue
            parts = []
            for key in ("timeouts", "rounds_per_s", "e2e_latency_ms"):
                t, b = col(ref, key), col(g, key)
                lo, hi = A.boot([(t, b)], rnd)
                parts.append(f"{key} p={ranksum_p(t, b):.3f}, trust2 {100 * A.rel(t, b):+.1f}% [{100 * lo:+.1f}%, {100 * hi:+.1f}%]")
            print(f"- {sc}, trust2 vs {rule}: " + "; ".join(parts))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results-p5/cmpg.csv")

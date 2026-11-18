"""Two arms of a comparison of leader rules, side by side. By default the two ways of sending votes (DESIGN.md
15.42): the runs of probe47.py, where votes go to the next leader only (as cmpg) or to every member (as cmpb, the
default of aptos-core), alternating inside each repetition. With a column and two names, any other switch: for
probe48.py (DESIGN.md 15.44), votes to all members without and with the QC forwarded to the next leader.

Prints the table and the comparisons of cmpgstat.py for each arm, then, cell by cell, what the broadcast changes:
performance (timeouts, rounds per second, end-to-end latency) and what each rule did to honest leaders. For each:
the medians of both arms, the exact two-sided rank-sum test and the relative difference of the medians with a
bootstrap 95% interval; the performance is also pooled over the rules of a scenario (the rules weigh equally and the
permutation test shuffles within a rule). Standard library only.
Run from prototype/benchmark/:  python3 votestat.py [results-probe47/cmp_votes.csv]
                                python3 votestat.py results-probe48/cmp_forward.csv forward_qc broadcast forward
"""
import csv
import os
import random
import sys
import tempfile
from statistics import median

import cmpgstat as C
import stats_a4 as A

RULES = ("none", "aptos", "failed", "trust2")


def harm(scenario, rule, rows):
    """What the rule did to honest leaders, per run: a list of (label, values)."""
    honest = C.NODES - C.FAULTY[scenario]
    num = lambda key: [float(r.get(key) or 0) for r in rows]
    if rule == "aptos":
        share = [100 * float(r.get("aptos_failed_honest") or 0) / (honest * (float(r["epochs"]) - 1)) for r in rows]
        return [("honest member-epochs at the failed weight, %", share)]
    if rule == "failed":
        return [("failed proposals of honest leaders", num("failed_facts_honest")),
                ("honest leaders excluded", num("g2_excluded_honest")), ("honest cut, %", [100 * x for x in num("honest_cut")])]
    if rule == "trust2":
        return [("AT against honest leaders", num("accusations_honest")),
                ("honest leaders excluded", num("g2_excluded_honest")), ("honest cut, %", [100 * x for x in num("honest_cut")])]
    return []


def versus(label, a, b, rnd, names, d=1):
    """One line: medians of both arms, rank-sum p, relative difference (when the reference median is not 0)."""
    if not a or not b:
        return f"  - {label}: -"
    off, on = names
    p = C.ranksum_p(a, b) if len(a) + len(b) <= 20 else float("nan")
    line = f"  - {label}: {off} {C.mr(a, d)} / {on} {C.mr(b, d)}, p={p:.3f}"
    if median(a) > 0:
        try:
            lo, hi = A.boot([(b, a)], rnd)
            line += f", {on} {100 * A.rel(b, a):+.1f}% [{100 * lo:+.1f}%, {100 * hi:+.1f}%]"
        except ZeroDivisionError:
            line += f", {on} {100 * A.rel(b, a):+.1f}%"
    return line


def main(path, column="broadcast_votes", names=("next leader", "broadcast")):
    rows = list(csv.DictReader(open(path)))
    ARMS = (("False", names[0]), ("True", names[1]))
    arm = {flag: [r for r in rows if r[column] == flag] for flag, _ in ARMS}
    for flag, name in ARMS:
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(arm[flag])
        print(f"# Votes to: {name}\n")
        C.main(fh.name)
        os.unlink(fh.name)
        print()
    print(f"# {names[1]} against {names[0]}, cell by cell\n")
    rnd = random.Random(7)
    for sc in C.FAULTY:
        if not any(r["scenario"] == sc for r in rows):
            continue
        print(f"## {sc}\n")
        for rule in RULES:
            a = [r for r in arm["False"] if r["scenario"] == sc and r["leader_rule"] == rule]
            b = [r for r in arm["True"] if r["scenario"] == sc and r["leader_rule"] == rule]
            if not a or not b:
                continue
            print(f"- {rule} ({len(a)} v {len(b)} runs)")
            for key, d in (("timeouts", 0), ("rounds_per_s", 1), ("e2e_latency_ms", 0)):
                print(versus(key, C.col(a, key), C.col(b, key), rnd, names, d))
            for (label, x), (_, y) in zip(harm(sc, rule, a), harm(sc, rule, b)):
                print(versus(label, x, y, rnd, names, 2))
        print(f"\n- pooled over the rules of {sc} ({names[1]} against {names[0]}; bootstrap 95%, permutation test "
              "within a rule):")
        for key in ("timeouts", "rounds_per_s", "e2e_latency_ms"):
            batches = []
            for rule in RULES:
                a = C.col([r for r in arm["False"] if r["scenario"] == sc and r["leader_rule"] == rule], key)
                b = C.col([r for r in arm["True"] if r["scenario"] == sc and r["leader_rule"] == rule], key)
                if a and b:
                    batches.append((b, a))
            lo, hi = A.boot(batches, rnd)
            print(f"  - {key}: {100 * A.stat(batches):+.1f}% [{100 * lo:+.1f}%, {100 * hi:+.1f}%], p={A.perm(batches, rnd):.4f}")
        print()


if __name__ == "__main__":
    if len(sys.argv) > 4:
        main(sys.argv[1], sys.argv[2], (sys.argv[3], sys.argv[4]))
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else "results-probe47/cmp_votes.csv")

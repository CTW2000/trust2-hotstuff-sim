"""Further aggregates of the batch of DESIGN.md 15.53, written after the batch had ended and its results were seen.

rmainstat.py holds what was fixed before the runs. This file adds, with the same metrics and the same paired method:
who is convicted (runs, members, weight cut), what the rules do to the Byzantine members of part B, totals by model,
the thresholds of part D against ln 300, and the four rules against each other in the scenarios of part B.
Run from prototype/benchmark/:  python3 rmainextra.py > results-rmain/rmainextra.md"""
import random
from statistics import median

import rmainstat as s

out = "results-rmain"
rows = s.load(out)
pick = lambda sc, rule=None: [r for r in rows if r["scenario"] == sc and (rule is None or r["leader_rule"] == rule)]

print("## honest convictions: runs with at least one, convicted members, per scenario and rule")
scen = [f"{m}{s.fmt(x)}" for m, xs in s.MODELS.items() for x in xs] + [
    "silent-next", "silent-all", "late-all", "framers-next", "framers-all"]
for sc in scen:
    for rule in ("failed", "trust2"):
        rs = pick(sc, rule)
        conv = [s.num(r, "honest_convictions") for r in rs]
        nodes = [s.num(r, "honest_convicted_nodes") for r in rs]
        cut = [100 * s.num(r, "honest_cut") for r in rs]
        if sum(conv):
            print(f"{sc:13s} {rule:6s} runs {len(rs)} convictions {sum(conv):.0f} in {sum(1 for c in conv if c)} runs; "
                  f"members {sum(nodes):.0f}; max per run {max(conv):.0f}; cut max {max(cut):.2f}%; "
                  f"leads {sum(s.num(r, 'honest_leads') for r in rs):.0f}")

print("\n## byzantine members: restricted share (aptos: member-epochs at failed weight; others: exclusions)")
for sc in ("silent-next", "silent-all", "framers-next", "framers-all"):
    for rule in ("aptos", "failed", "trust2"):
        shares, counts = [], []
        for r in pick(sc, rule):
            f = s.facts_of(out, r)
            byz = {name for node, name in f["names"].items() if int(node) in set(f["byzantine"])}
            if rule == "aptos":
                hit = sum(1 for _, name, kind in f["aptos"] if kind == "failed" and name in byz)
                shares.append(100 * hit / (len(byz) * (len(f["epochs"]) + 1)))
            else:
                counts.append(sum(1 for _, name, kind in f["excluded"] if name in byz and kind == "excluded"))
        if shares:
            print(f"{sc:13s} {rule:6s} byzantine member-epochs at failed weight: median {median(shares):.1f}% "
                  f"[{min(shares):.1f}, {max(shares):.1f}]")
        else:
            print(f"{sc:13s} {rule:6s} exclusions of byzantine members per run: median {median(counts):.1f} "
                  f"[{min(counts)}, {max(counts)}], total {sum(counts)}")

print("\n## totals of the trust2 and failed arms by model (part A)")
for model, shares in s.MODELS.items():
    for rule in ("failed", "trust2"):
        rs = [r for share in shares for r in pick(f"{model}{s.fmt(share)}", rule)]
        print(f"{model} {rule:6s} runs {len(rs)} honest leads {sum(s.num(r, 'honest_leads') for r in rs):.0f} "
              f"accusations {sum(s.num(r, 'honest_accusations') for r in rs):.0f} "
              f"convictions {sum(s.num(r, 'honest_convictions') for r in rs):.0f}")

print("\n## throughput and timeouts per run (part A, trust2): committed tps median, runs without commits")
for sc in scen[:16]:
    for rule in s.RULES:
        rs = pick(sc, rule)
        tps = [s.num(r, "e2e_tps") for r in rs]
        dead = sum(1 for r in rs if not s.num(r, "e2e_latency_ms"))
        if rule == "trust2" or dead:
            print(f"{sc:5s} {rule:6s} e2e tps median {median(tps):.0f} [{min(tps):.0f}, {max(tps):.0f}]; "
                  f"runs without a latency {dead}; ledger conflicts {sum(s.num(r, 'ledger_conflicts') for r in rs):.0f}")

print("\n## ledger conflicts over all runs:", sum(s.num(r, "ledger_conflicts") for r in rows),
      "; runs", len(rows), "; blocks", sorted({int(r['rep']) for r in rows}))

print("\n## selection set: silent runs, M1 and rounds/s medians by threshold, blocks 1-5 and 6-10")
silent = [("ln 10^2", pick("silent-1e2")), ("ln 300", pick("silent-next", "trust2")),
          ("ln 10^3", pick("silent-1e3")), ("ln 10^4", pick("silent-1e4"))]
for label, rs in silent:
    for name, want in (("1-5", range(1, 6)), ("6-10", range(6, 11))):
        ms = [s.metrics(out, r) for r in rs if int(r["rep"]) in want]
        print(f"{label:8s} blocks {name}: M1 {median(m['m1'] for m in ms):.1f} rounds/s {median(m['rps'] for m in ms):.1f} "
              f"M5 {median(m['m5'] for m in ms):.0f} honest convictions {sum(m['convictions'] for m in ms):.0f}")

print("\n## paired comparisons of the thresholds with silent leaders (against ln 300)")
rnd = random.Random(53)
s.compare(out, "silent leaders: thresholds against ln 300",
          [(f"{label} against ln 300", rs, silent[1][1]) for label, rs in silent if label != "ln 300"], rnd)
s.compare(out, "silent leaders, votes to the next leader: trust2 against the other rules",
          [(f"trust2 against {rule}", pick("silent-next", "trust2"), pick("silent-next", rule)) for rule in s.RULES[:3]], rnd)
s.compare(out, "silent leaders, votes to all: trust2 against the other rules",
          [(f"trust2 against {rule}", pick("silent-all", "trust2"), pick("silent-all", rule)) for rule in s.RULES[:3]], rnd)
s.compare(out, "framers, votes to the next leader: trust2 against the other rules",
          [(f"trust2 against {rule}", pick("framers-next", "trust2"), pick("framers-next", rule)) for rule in s.RULES[:3]], rnd)
s.compare(out, "framers, votes to all: trust2 against the other rules",
          [(f"trust2 against {rule}", pick("framers-all", "trust2"), pick("framers-all", rule)) for rule in s.RULES[:3]], rnd)
s.compare(out, "late, votes to all: trust2 against the other rules",
          [(f"trust2 against {rule}", pick("late-all", "trust2"), pick("late-all", rule)) for rule in s.RULES[:3]], rnd)

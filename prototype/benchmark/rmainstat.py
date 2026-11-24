"""Statistics of the batch of DESIGN.md 15.53 (rmain.py), as fixed there before the runs.

Metrics, the same for the four leader rules: M1 timed-out rounds per 1000 rounds; M2 end-to-end latency; M3 the
share of honest member-time under a restriction on leading (excluded under trust2 and failed, by rounds; at the
failed weight under aptos, by member-epochs; none: 0); M4 the voting power cut from honest members; M5, with silent
leaders, the round by which all of them are restricted.

Comparisons are paired by block: the median of the paired relative differences, its 90% bootstrap interval, the exact
signed-rank test, Holm's correction within a scenario. Two arms are called equivalent on a metric only if the whole
interval lies within +-15%.

The G2 threshold (R7): the candidates ln 10^2, ln 300, ln 10^3, ln 10^4 are replayed offline on the accusations of
the `none` arm, where nothing is excluded: per honest leader, over the rounds it led, an accused round counts as
adverse. Selection set: blocks 1-5, models P and S at 5% and 10%, and the runs with silent leaders of those blocks;
evaluation set: blocks 6-10, every model and share. A round whose leader neither proposed nor was accused is not in
the sequence, so the replay sees slightly fewer normal observations than the protocol does.

The sequences (R8): lag-1 autocorrelation, run lengths, a two-state chain fitted to the transitions, and for every
threshold the convictions expected if the facts were independent, expected under the fitted chain (both by
simulation on sequences of the observed lengths), and replayed.

Run from prototype/benchmark/:  python3 rmainstat.py [results-rmain] [simulations] > results-rmain/rmainstat.md
                                python3 rmainstat.py selftest
Standard library only."""
import csv
import json
import os
import random
import sys
from collections import defaultdict
from statistics import median

UP, DOWN = 1_609_438, 587_787                    # ln 5 and ln(9/5), in ppm
THRESHOLDS = (("ln 10^2", 4_605_170), ("ln 300", 5_703_782), ("ln 10^3", 6_907_755), ("ln 10^4", 9_210_340))
BOUND = 0.15
RULES = ("none", "aptos", "failed", "trust2")
MODELS = {"P": (2, 5, 10, 20), "S": (2, 5, 10, 20), "B": (2, 5, 10, 20), "Q": (0.5, 1, 2, 3)}
NAN = float("nan")


def fmt(x):
    return f"{x:g}"


def load(out):
    rows = []
    for part in "ABCD":
        path = f"{out}/part{part}.csv"
        if os.path.exists(path):
            with open(path) as fh:
                for r in csv.DictReader(fh):
                    r["part"] = part
                    rows.append(r)
    return rows


def num(r, key):
    try:
        return float(r.get(key) or 0)
    except ValueError:
        return 0.0


def facts_of(out, row, cache={}):
    path = f"{out}/facts/{row.get('facts', '')}"
    if path not in cache:
        cache[path] = json.load(open(path)) if os.path.isfile(path) else None
    return cache[path]


def honest_names(f):
    byz = {str(b) for b in f["byzantine"]}
    return {name for node, name in f["names"].items() if node not in byz}


def top_round(f):
    return max((max(v) for v in f["led"].values() if v), default=0)


def restricted(f, rule):
    """M3: the share of honest member-time under a restriction on leading."""
    honest, top = honest_names(f), top_round(f)
    if not honest or top == 0:
        return NAN
    if rule == "aptos":
        hit = sum(1 for _, name, kind in f["aptos"] if kind == "failed" and name in honest)
        return hit / (len(honest) * (len(f["epochs"]) + 1))
    released = defaultdict(list)
    for rnd, name in f["released"]:
        released[name].append(rnd)
    rounds = 0
    for rnd, name, kind in f["excluded"]:
        if name in honest and kind == "excluded":
            end = min([x for x in released[name] if x > rnd] + [rnd + 500, top])
            rounds += max(0, end - rnd)
    return rounds / (len(honest) * top)


def all_restricted_by(f, rule):
    """M5: the round by which every silent (Byzantine) member is restricted from leading; nan if one never is."""
    silent = {name for node, name in f["names"].items() if int(node) in set(f["byzantine"])}
    if not silent:
        return NAN
    first = {}
    if rule == "aptos":
        start = {e: rnd for e, rnd, _ in f["epochs"]}
        for e, name, kind in f["aptos"]:
            if kind == "failed" and name in silent and e in start:
                first[name] = min(first.get(name, 10**9), start[e])
    else:
        for rnd, name, kind in f["excluded"]:
            if name in silent and kind == "excluded":
                first[name] = min(first.get(name, 10**9), rnd)
    return max(first.values()) if len(first) == len(silent) else NAN


def metrics(out, r):
    top = num(r, "top_round")
    f = facts_of(out, r)
    rule = r["leader_rule"]
    return dict(m1=1000 * num(r, "timeout_rounds") / top if top else NAN,
                m2=num(r, "e2e_latency_ms") or NAN, rps=num(r, "rounds_per_s") if top else 0.0,
                m3=100 * restricted(f, rule) if f else NAN, m4=100 * num(r, "honest_cut"),
                m5=all_restricted_by(f, rule) if f else NAN,
                leads=num(r, "honest_leads"), accusations=num(r, "honest_accusations"),
                convictions=num(r, "honest_convictions"))


def sequences(f):
    """Per honest member, the 0/1 sequence of accusations over the rounds it led, in round order."""
    byz = {str(b) for b in f["byzantine"]}
    accused = defaultdict(set)
    for rnd, name in f["accusations"]:
        accused[name].add(rnd)
    out = []
    for node, name in f["names"].items():
        if node not in byz:
            rounds = sorted(set(f["led"].get(node, [])) | accused[name])
            out.append([1 if rnd in accused[name] else 0 for rnd in rounds])
    return out


def convictions(seq, threshold):
    """How often the CUSUM of the protocol convicts on `seq` (the statistic is reset on a conviction)."""
    s = n = 0
    for x in seq:
        s = s + UP if x else max(0, s - DOWN)
        if s >= threshold:
            n, s = n + 1, 0
    return n


def fit(seqs):
    """The share of adverse facts, the transition probabilities of a two-state chain, and the lag-1 autocorrelation."""
    n = [[0, 0], [0, 0]]
    total = ones = 0
    for s in seqs:
        total, ones = total + len(s), ones + sum(s)
        for a, b in zip(s, s[1:]):
            n[a][b] += 1
    p = ones / total if total else 0.0
    p01 = n[0][1] / (n[0][0] + n[0][1]) if n[0][0] + n[0][1] else 0.0
    p11 = n[1][1] / (n[1][0] + n[1][1]) if n[1][0] + n[1][1] else 0.0
    num_, den = 0.0, 0.0
    for s in seqs:
        den += sum((x - p) ** 2 for x in s)
        num_ += sum((a - p) * (b - p) for a, b in zip(s, s[1:]))
    return dict(n=total, ones=ones, p=p, p01=p01, p11=p11, acf=num_ / den if den else 0.0)


def run_lengths(seqs):
    """How many runs of adverse facts have length 1, 2, 3 and 4 or more."""
    out = [0, 0, 0, 0]
    for s in seqs:
        k = 0
        for x in s + [0]:
            if x:
                k += 1
            elif k:
                out[min(k, 4) - 1] += 1
                k = 0
    return out


def expected(lengths, p01, p11, reps, rnd):
    """Mean convictions per threshold over `reps` simulated sets of sequences of the given lengths."""
    pi = p01 / (p01 + 1 - p11) if p01 + 1 - p11 > 0 else 0.0
    hs = [h for _, h in THRESHOLDS]
    totals = [0] * len(hs)
    for _ in range(reps):
        for length in lengths:
            x = rnd.random() < pi
            state = [0] * len(hs)
            for _ in range(length):
                for i, h in enumerate(hs):
                    v = state[i] + UP if x else max(0, state[i] - DOWN)
                    if v >= h:
                        totals[i] += 1
                        v = 0
                    state[i] = v
                x = rnd.random() < (p11 if x else p01)
    return [t / reps for t in totals]


def signed_rank(d):
    """The exact two-sided signed-rank test: (sum of the ranks of the positive differences, p, n without zeros)."""
    d = [x for x in d if x != 0 and x == x]
    n = len(d)
    if n == 0:
        return 0.0, 1.0, 0
    order = sorted(range(n), key=lambda i: abs(d[i]))
    rank = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(d[order[j + 1]]) == abs(d[order[i]]):
            j += 1
        for k in range(i, j + 1):
            rank[order[k]] = (i + j) / 2 + 1
        i = j + 1
    w = sum(r for r, x in zip(rank, d) if x > 0)
    dist = defaultdict(int)
    dist[0.0] = 1
    for r in rank:
        new = defaultdict(int)
        for s, c in dist.items():
            new[s] += c
            new[s + r] += c
        dist = new
    total = 2 ** n
    lower = sum(c for s, c in dist.items() if s <= w + 1e-9) / total
    upper = sum(c for s, c in dist.items() if s >= w - 1e-9) / total
    return w, min(1.0, 2 * min(lower, upper)), n


def interval(d, rnd, reps=5000, level=0.90):
    d = [x for x in d if x == x]
    if not d:
        return NAN, NAN, NAN
    meds = sorted(median(rnd.choice(d) for _ in d) for _ in range(reps))
    lo, hi = meds[int((1 - level) / 2 * reps)], meds[int((1 + level) / 2 * reps) - 1]
    return median(d), lo, hi


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    out, worst = [0.0] * len(ps), 0.0
    for k, i in enumerate(order):
        worst = max(worst, min(1.0, (len(ps) - k) * ps[i]))
        out[i] = worst
    return out


def mr(xs, d=1):
    xs = sorted(x for x in xs if x == x)
    if not xs:
        return "-"
    return f"{median(xs):.{d}f} [{xs[0]:.{d}f}, {xs[-1]:.{d}f}]"


def table(out, title, groups):
    """One line per arm: `groups` maps a label to its rows."""
    print(f"\n### {title}\n")
    print("| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | "
          "M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for label, rows in groups:
        ms = [metrics(out, r) for r in rows]
        if not ms:
            continue
        leads, acc = sum(m["leads"] for m in ms), sum(m["accusations"] for m in ms)
        print(f"| {label} | {len(ms)} | {mr([m['rps'] for m in ms])} | {mr([m['m1'] for m in ms])} | "
              f"{mr([m['m2'] for m in ms], 0)} | {mr([m['m3'] for m in ms], 2)} | {mr([m['m4'] for m in ms], 2)} | "
              f"{leads:.0f} | {1000 * acc / leads if leads else 0:.1f} | {sum(m['convictions'] for m in ms):.0f} |")


def compare(out, title, pairs, rnd):
    """Paired comparisons. `pairs`: (label, rows of arm a, rows of arm b); the difference is (a - b) / b."""
    lines, ps = [], []
    for label, a, b in pairs:
        by_block = lambda rows: {r["rep"]: metrics(out, r) for r in rows}
        ma, mb = by_block(a), by_block(b)
        blocks = sorted(set(ma) & set(mb), key=int)
        for key, name in (("m1", "M1"), ("m2", "M2"), ("rps", "rounds/s")):
            d = [(ma[k][key] - mb[k][key]) / mb[k][key] if mb[k][key] else (0.0 if ma[k][key] == 0 else NAN)
                 for k in blocks]
            d = [x for x in d if x == x]
            if len(d) < 2:
                continue
            med, lo, hi = interval(d, rnd)
            w, p, n = signed_rank(d)
            ps.append(p)
            lines.append((label, name, len(d), med, lo, hi, w, n, p))
    if not lines:
        return
    adj = holm(ps)
    print(f"\n### {title}\n")
    print("| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | "
          "p (Holm) | within +-15% |")
    print("|---|---|---|---|---|---|---|---|---|")
    for (label, name, k, med, lo, hi, w, n, p), q in zip(lines, adj):
        inside = "yes" if -BOUND <= lo and hi <= BOUND else "no"
        print(f"| {label} | {name} | {k} | {100 * med:+.1f}% | [{100 * lo:+.1f}%, {100 * hi:+.1f}%] | {w:g} ({n}) | "
              f"{p:.3f} | {q:.3f} | {inside} |")


def report(out, sims):
    rnd = random.Random(53)
    rows = load(out)
    pick = lambda scenario, rule=None, **kw: [
        r for r in rows if r["scenario"] == scenario and (rule is None or r["leader_rule"] == rule)
        and all(str(r.get(k, "")) == str(v) for k, v in kw.items())]
    blocks = sorted({int(r["rep"]) for r in rows})
    print(f"# The leader rules under lateness (DESIGN.md 15.53): {len(rows)} runs, blocks {blocks}\n")
    print("Median [min, max] over the runs of an arm unless stated. A run in which nothing commits after the warm-up "
          "has no latency and counts 0 rounds per second.")

    print("\n## A. Four rules, four models of lateness\n")
    for model, shares in MODELS.items():
        for share in shares:
            name = f"{model}{fmt(share)}"
            table(out, f"{name}: model {model}, {fmt(share)}% late", [(rule, pick(name, rule)) for rule in RULES])
    for model, shares in MODELS.items():
        pairs = [(f"{model}{fmt(share)}: trust2 against {rule}", pick(f"{model}{fmt(share)}", "trust2"),
                  pick(f"{model}{fmt(share)}", rule)) for share in shares for rule in RULES[:3]]
        compare(out, f"Model {model}: trust2 against the other rules", pairs, rnd)

    print("\n## B. Vote routing and leader rule\n")
    for name in ("silent", "late", "framers"):
        for votes in ("next", "all"):
            scenario = "P10" if (name, votes) == ("late", "next") else f"{name}-{votes}"
            table(out, f"{name}, votes to {votes}", [(rule, pick(scenario, rule)) for rule in RULES])
        pairs = [(f"{name}, {rule}: votes to all against the next leader", pick(f"{name}-all", rule),
                  pick("P10" if name == "late" else f"{name}-next", rule)) for rule in RULES]
        compare(out, f"{name}: votes to all against votes to the next leader", pairs, rnd)
    print("\n### Silent leaders: the round by which all three are restricted (M5)\n")
    print("| votes | rule | runs | runs in which all are restricted | M5 |")
    print("|---|---|---|---|---|")
    for votes in ("next", "all"):
        for rule in RULES:
            ms = [metrics(out, r)["m5"] for r in pick(f"silent-{votes}", rule)]
            done = [x for x in ms if x == x]
            print(f"| {votes} | {rule} | {len(ms)} | {len(done)} | {mr(done, 0)} |")

    print("\n## C. The failure threshold of the Aptos-style rule\n")
    for model in ("P", "S"):
        groups = [("10% (default)", pick(f"{model}10", "aptos"))]
        groups += [(f"{pc}%", pick(f"{model}10-aptos{pc}")) for pc in (5, 20, 30)]
        table(out, f"{model}10, by failure threshold", sorted(groups, key=lambda g: float(g[0].split("%")[0])))

    print("\n## D. The G2 threshold\n")
    silent = [("ln 10^2", pick("silent-1e2")), ("ln 300", pick("silent-next", "trust2")),
              ("ln 10^3", pick("silent-1e3")), ("ln 10^4", pick("silent-1e4"))]
    table(out, "Three silent leaders, by threshold (votes to the next leader)", silent)
    print("\n| threshold | runs | M5 round by which all three are excluded |")
    print("|---|---|---|")
    for label, rs in silent:
        print(f"| {label} | {len(rs)} | {mr([metrics(out, r)['m5'] for r in rs], 0)} |")

    def replay(scenarios, wanted):
        """Per threshold: (convictions, leads) replayed on the `none` arm of the scenarios, blocks in `wanted`."""
        counts, leads = [0] * len(THRESHOLDS), 0
        for scenario in scenarios:
            for r in pick(scenario, "none"):
                f = facts_of(out, r)
                if f is None or int(r["rep"]) not in wanted:
                    continue
                for seq in sequences(f):
                    leads += len(seq)
                    for i, (_, h) in enumerate(THRESHOLDS):
                        counts[i] += convictions(seq, h)
        return counts, leads

    print("\n### Selection (blocks 1-5)\n")
    first = set(range(1, 6))
    counts, leads = replay(("P5", "P10"), first)
    costs = {label: median([metrics(out, r)["m1"] for r in rs if int(r["rep"]) in first] or [NAN])
             for label, rs in silent}
    print("| threshold | replayed honest convictions, P at 5% and 10% | honest leads | M1 with silent leaders (median) |")
    print("|---|---|---|---|")
    for (label, _), c in zip(THRESHOLDS, counts):
        print(f"| {label} | {c} | {leads} | {costs[label]:.1f} |")
    ok = [label for (label, _), c in zip(THRESHOLDS, counts) if c == 0 and costs[label] == costs[label]]
    chosen = min(ok, key=lambda label: costs[label]) if ok and leads else None
    print(f"\nThe rule fixed before the runs (no replayed conviction under P, then the fewest timeouts with silent "
          f"leaders) selects: **{chosen or 'nothing yet'}**. The protocol uses ln 300, set on 2026-11-22.")
    counts, leads = replay(("S5", "S10"), first)
    print(f"\nFor reference, model S at 5% and 10% on the same blocks: "
          + ", ".join(f"{label} {c}" for (label, _), c in zip(THRESHOLDS, counts)) + f" in {leads} honest leads.")

    print("\n### Evaluation (blocks 6-10)\n")
    last = set(range(6, 11))
    print("| scenario | honest leads (none arm) | " + " | ".join(f"replayed, {label}" for label, _ in THRESHOLDS)
          + " | trust2 arm: convictions / honest leads |")
    print("|---|---|" + "---|" * (len(THRESHOLDS) + 1))
    for model, shares in MODELS.items():
        for share in shares:
            name = f"{model}{fmt(share)}"
            counts, leads = replay((name,), last)
            closed = [metrics(out, r) for r in pick(name, "trust2") if int(r["rep"]) in last]
            print(f"| {name} | {leads} | " + " | ".join(str(c) for c in counts)
                  + f" | {sum(m['convictions'] for m in closed):.0f} / {sum(m['leads'] for m in closed):.0f} |")

    print("\n## The sequences of adverse facts (R8; `none` arm, all blocks)\n")
    print("| scenario | honest leads | adverse share | P(adverse after normal) | P(adverse after adverse) | lag-1 "
          "autocorrelation | runs of 1 / 2 / 3 / 4+ |")
    print("|---|---|---|---|---|---|---|")
    fits = {}
    for model, shares in MODELS.items():
        for share in shares:
            name = f"{model}{fmt(share)}"
            seqs = [s for r in pick(name, "none") if facts_of(out, r) for s in sequences(facts_of(out, r))]
            if not seqs:
                continue
            f = fits[name] = dict(fit(seqs), seqs=seqs)
            print(f"| {name} | {f['n']} | {f['p']:.4f} | {f['p01']:.4f} | {f['p11']:.4f} | {f['acf']:+.3f} | "
                  + " / ".join(map(str, run_lengths(seqs))) + " |")
    print(f"\nConvictions per threshold: expected if the facts were independent, expected under the fitted two-state "
          f"chain ({sims} simulated sets of sequences each), and replayed.\n")
    print("| scenario | honest leads | " + " | ".join(f"{label}: independent / chain / replayed" for label, _ in THRESHOLDS)
          + " |")
    print("|---|---|" + "---|" * len(THRESHOLDS))
    for name, f in fits.items():
        lengths = [len(s) for s in f["seqs"]]
        iid = expected(lengths, f["p"], f["p"], sims, rnd)
        chain = expected(lengths, f["p01"], f["p11"], sims, rnd)
        seen = [sum(convictions(s, h) for s in f["seqs"]) for _, h in THRESHOLDS]
        print(f"| {name} | {f['n']} | "
              + " | ".join(f"{a:.2f} / {b:.2f} / {c}" for a, b, c in zip(iid, chain, seen)) + " |")


def selftest():
    assert convictions([1, 1, 1, 1], 5_703_782) == 1 and convictions([1, 1, 1], 5_703_782) == 0
    assert convictions([1, 1, 1], 4_605_170) == 1 and convictions([1, 1, 1, 1, 1, 1], 9_210_340) == 1
    assert convictions([1, 1, 1, 0, 1, 1], 5_703_782) == 1          # 3 up, 1 down, 1 up crosses ln 300
    assert convictions([1, 0, 0, 0, 1, 1, 1], 5_703_782) == 0
    w, p, n = signed_rank([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert (w, n) == (55, 10) and abs(p - 2 / 1024) < 1e-12
    w, p, n = signed_rank([1, -1, 2, -2])
    assert abs(p - 1.0) < 1e-12 and n == 4
    assert signed_rank([0, 0])[2] == 0
    assert holm([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]
    f = fit([[1, 1, 0, 0, 1], [0, 0]])
    assert f["n"] == 7 and f["ones"] == 3 and abs(f["p01"] - 1 / 3) < 1e-12 and abs(f["p11"] - 0.5) < 1e-12
    assert run_lengths([[1, 1, 0, 1], [1, 1, 1, 1, 1]]) == [1, 1, 0, 1]
    rnd = random.Random(1)
    assert expected([50] * 20, 0.0, 0.0, 5, rnd) == [0.0] * 4
    always = expected([12], 1.0, 1.0, 3, rnd)
    assert always == [4.0, 3.0, 2.0, 2.0], always                   # 3, 4, 5 and 6 adverse facts in a row convict
    facts = dict(names={"0": "a", "1": "b", "2": "z"}, byzantine=[2], led={"0": [1, 4], "1": [2, 5], "2": []},
                 accusations=[[3, "a"], [6, "z"]], excluded=[[10, "a", "excluded"], [3, "z", "excluded"]],
                 released=[[14, "a"]], aptos=[], epochs=[[1, 5, 3]])
    assert sorted(sequences(facts)) == [[0, 0], [0, 1, 0]]
    facts["led"]["0"].append(20)
    assert abs(restricted(facts, "trust2") - 4 / (2 * 20)) < 1e-12
    assert all_restricted_by(facts, "trust2") == 3
    print("selftest ok")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
    else:
        report(sys.argv[1] if len(sys.argv) > 1 else "results-rmain", int(sys.argv[2]) if len(sys.argv) > 2 else 200)

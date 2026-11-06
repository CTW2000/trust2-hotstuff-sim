"""Effect sizes for the prototype comparisons (the mock review's A4; DESIGN.md §15.17).

For each comparison: the relative difference of medians (Trust 2.0 against the reference) with a bootstrap 95%
interval (resampling within each group of each batch; batches weigh equally), a batch-stratified permutation test
(labels shuffled only within a batch, so batch effects cancel), and whether the interval lies inside +-10%
(equivalence at that margin). Standard library only.
Run from prototype/benchmark/:  python3 stats_a4.py"""
import csv
import random
import statistics as st

R = "results-p5"
B, P = 20_000, 20_000


def load(path, **match):
    rows = list(csv.DictReader(open(f"{R}/{path}")))
    return [r for r in rows if all(r.get(k) == v for k, v in match.items())]


def col(rows, metric):
    return [float(r[metric]) for r in rows if r.get(metric) not in (None, "")]


def rel(t, b):
    return st.median(t) / st.median(b) - 1


def stat(batches):
    return sum(rel(t, b) for t, b in batches) / len(batches)


def boot(batches, rnd):
    out = []
    for _ in range(B):
        out.append(stat([([rnd.choice(t) for _ in t], [rnd.choice(b) for _ in b]) for t, b in batches]))
    out.sort()
    return out[int(0.025 * B)], out[int(0.975 * B)]


def perm(batches, rnd):
    obs = abs(stat(batches))
    hits = 0
    for _ in range(P):
        shuffled = []
        for t, b in batches:
            pool = t + b
            rnd.shuffle(pool)
            shuffled.append((pool[:len(t)], pool[len(t):]))
        hits += abs(stat(shuffled)) >= obs - 1e-12
    return (hits + 1) / (P + 1)


def report(name, batches, margin=0.10):
    rnd = random.Random(7)
    est = stat(batches)
    lo, hi = boot(batches, rnd)
    p = perm(batches, rnd)
    eq = "yes" if -margin < lo and hi < margin else "no"
    n = " + ".join(f"{len(t)}v{len(b)}" for t, b in batches)
    print(f"{name}: {est:+.1%} [{lo:+.1%}, {hi:+.1%}], stratified permutation p = {p:.3f}, "
          f"inside +-{margin:.0%}: {eq}  (n = {n})")


def main():
    for metric in ("e2e_latency_ms", "rounds_per_s", "timeouts"):
        a = (col(load("f25_late.csv", build="trust2"), metric), col(load("f25_late.csv", build="baseline"), metric))
        b = (col(load("lc.csv", build="trust2", epoch_length="25"), metric), col(load("lc.csv", build="baseline"), metric))
        report(f"10% late, Trust 2.0 vs baseline, {metric} (batches f25_late, lc)", [a, b])
    for metric in ("e2e_latency_ms", "rounds_per_s", "timeouts"):
        b = (col(load("lc.csv", build="trust2", epoch_length="0"), metric), col(load("lc.csv", build="baseline"), metric))
        report(f"10% late, Trust 2.0 single epoch vs baseline, {metric} (lc)", [b])
    for metric in ("timeouts", "rounds_per_s", "e2e_latency_ms"):
        t = col(load("cmpg.csv", scenario="silent", leader_rule="trust2", g2_threshold="0"), metric)
        a = col(load("cmpg.csv", scenario="silent", leader_rule="aptos"), metric)
        report(f"silent leaders, Trust 2.0 vs Aptos-style, {metric} (cmpg)", [(t, a)], margin=0.20)
    for metric in ("e2e_tps", "e2e_latency_ms"):
        t = col(load("cmpg.csv", scenario="framers+late", leader_rule="trust2"), metric)
        a = col(load("cmpg.csv", scenario="framers+late", leader_rule="aptos"), metric)
        report(f"framers + late, Trust 2.0 vs Aptos-style, {metric} (cmpg)", [(t, a)])


if __name__ == "__main__":
    main()

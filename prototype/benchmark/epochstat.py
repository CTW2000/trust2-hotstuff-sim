"""Statistics of the batch of DESIGN.md 15.56 (epochlen.py): what the epoch length costs and what it buys.

Per arm, median [min, max] over the blocks: rounds per second, timed-out rounds per 1000 rounds, end-to-end latency,
stalls (rounds in which f+1 nodes timed out), stalls next to a handover and per handover; with silent leaders also the
round by which all three are convicted and the round from which the table in force excludes all three (a conviction
enters the table computed at the next epoch change whose terminal block is at least `lag` rounds past it, and that
table takes effect one epoch later).

Paired by block (rmainstat.py: median of the relative differences, 90% bootstrap interval, exact signed-rank test,
Holm within a table; equivalent only if the interval lies within +-15%): under late messages every epoch length
against the baseline and against the single epoch; with silent leaders H5 on against off at each length, and each
length against 25 rounds with H5 on. With fewer than two blocks only the tables of the arms are printed.

Run from prototype/benchmark/:  python3 epochstat.py [results-epoch] > results-epoch/epochstat.md
Standard library only."""
import csv
import json
import os
import random
import sys
from statistics import median

import rmainstat as s

NAN = float("nan")
LAG = 10
LENGTHS = ("25", "50", "100", "400")


def num(r, key):
    try:
        return float(r.get(key) or 0)
    except ValueError:
        return 0.0


def arm(r):
    if r["scenario"] == "late":
        return "baseline" if r["build"] == "baseline" else f"e{r['epoch_length']}"
    return f"e{r['epoch_length']}-{'off' if r.get('no_h5') == 'True' else 'on'}"


def exclusion(out, r):
    """(round by which all silent leaders are convicted, round from which the table excludes all of them)."""
    path = f"{out}/facts/{r.get('facts', '')}"
    if not os.path.isfile(path):
        return NAN, NAN
    f = json.load(open(path))
    if not f.get("byzantine"):
        return NAN, NAN
    silent = {name for node, name in f["names"].items() if int(node) in set(f["byzantine"])}
    first = {}
    for rnd, name, kind in f["excluded"]:
        if name in silent and kind == "excluded":
            first[name] = min(first.get(name, 10**9), rnd)
    if len(first) < len(silent):
        return NAN, NAN
    epochs = sorted(f["epochs"])                             # [epoch, round it was entered at, terminal round]
    effective = []
    for u in first.values():
        k = next((i for i, (_, _, terminal) in enumerate(epochs) if terminal + 1 - LAG >= u), None)
        if k is None or k + 1 >= len(epochs):
            return max(first.values()), NAN                  # convicted, but the table was not in force in the run
        effective.append(epochs[k + 1][1])
    return max(first.values()), max(effective)


def metrics(out, r):
    top = num(r, "top_round")
    handovers = num(r, "epochs") if r["build"] == "trust2" else 0
    convicted, effective = exclusion(out, r) if r["scenario"] == "silent" else (NAN, NAN)
    return dict(rps=num(r, "rounds_per_s"), m1=1000 * num(r, "timeout_rounds") / top if top else NAN,
                e2e=num(r, "e2e_latency_ms") or NAN, tps=num(r, "e2e_tps"), stalls=num(r, "stalls"),
                near=num(r, "stalls_near"), handovers=handovers,
                per_handover=num(r, "stalls_near") / handovers if handovers else NAN,
                convicted=convicted, effective=effective, top=top)


def table(out, title, groups, silent=False):
    print(f"\n### {title}\n")
    head = "| arm | runs | rounds/s | timed-out rounds per 1000 | end-to-end ms | stalls | stalls next to a handover | handovers | per handover |"
    if silent:
        head += " all three convicted by round | excluded by the table from round | top round |"
    print(head)
    print("|" + "---|" * head.count("|", 1))
    for label, rows in groups:
        ms = [metrics(out, r) for r in rows]
        if not ms:
            continue
        line = (f"| {label} | {len(ms)} | {s.mr([m['rps'] for m in ms])} | {s.mr([m['m1'] for m in ms])} | "
                f"{s.mr([m['e2e'] for m in ms], 0)} | {s.mr([m['stalls'] for m in ms], 0)} | "
                f"{s.mr([m['near'] for m in ms], 0)} | {s.mr([m['handovers'] for m in ms], 0)} | "
                f"{s.mr([m['per_handover'] for m in ms], 2)} |")
        if silent:
            done = [m["effective"] for m in ms if m["effective"] == m["effective"]]
            line += (f" {s.mr([m['convicted'] for m in ms], 0)} | {s.mr(done, 0)} ({len(done)} of {len(ms)} runs) | "
                     f"{s.mr([m['top'] for m in ms], 0)} |")
        print(line)


def compare(out, title, pairs, rnd):
    lines, ps = [], []
    for label, a, b in pairs:
        ma = {r["rep"]: metrics(out, r) for r in a}
        mb = {r["rep"]: metrics(out, r) for r in b}
        blocks = sorted(set(ma) & set(mb), key=int)
        for key, name in (("e2e", "end-to-end latency"), ("rps", "rounds/s"), ("m1", "timed-out rounds per 1000")):
            d = [(ma[k][key] - mb[k][key]) / mb[k][key] for k in blocks if mb[k][key] and mb[k][key] == mb[k][key]
                 and ma[k][key] == ma[k][key]]
            if len(d) < 2:
                continue
            med, lo, hi = s.interval(d, rnd)
            w, p, n = s.signed_rank(d)
            ps.append(p)
            lines.append((label, name, len(d), med, lo, hi, w, n, p))
    if not lines:
        return
    adj = s.holm(ps)
    print(f"\n### {title}\n")
    print("| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |")
    print("|---|---|---|---|---|---|---|---|---|")
    for (label, name, k, med, lo, hi, w, n, p), q in zip(lines, adj):
        inside = "yes" if -s.BOUND <= lo and hi <= s.BOUND else "no"
        print(f"| {label} | {name} | {k} | {100 * med:+.1f}% | [{100 * lo:+.1f}%, {100 * hi:+.1f}%] | {w:g} ({n}) | "
              f"{p:.3f} | {q:.3f} | {inside} |")


def report(out):
    rnd = random.Random(56)
    with open(f"{out}/epoch.csv") as fh:
        rows = list(csv.DictReader(fh))
    pick = lambda scenario, name: [r for r in rows if r["scenario"] == scenario and arm(r) == name]
    blocks = sorted({int(r["rep"]) for r in rows})
    print(f"# The epoch length (DESIGN.md 15.56): {len(rows)} runs, blocks {blocks}\n")
    print("Median [min, max] over the runs of an arm.")

    print("\n## 10% late messages\n")
    late = ["baseline"] + [f"e{length}" for length in LENGTHS] + ["e0"]
    table(out, "The baseline, and Trust 2.0 by epoch length (e0: a single epoch)", [(a, pick("late", a)) for a in late])
    compare(out, "Trust 2.0 against the baseline",
            [(f"{a} against the baseline", pick("late", a), pick("late", "baseline")) for a in late[1:]], rnd)
    compare(out, "Trust 2.0 with handovers against a single epoch",
            [(f"{a} against e0", pick("late", a), pick("late", "e0")) for a in late[1:-1]], rnd)

    print("\n## Three silent leaders\n")
    arms = [f"e{length}-{h5}" for length in LENGTHS for h5 in ("on", "off")]
    table(out, "Trust 2.0 by epoch length, with H5 and without", [(a, pick("silent", a)) for a in arms], silent=True)
    compare(out, "H5 on against off, by epoch length",
            [(f"e{length}: on against off", pick("silent", f"e{length}-on"), pick("silent", f"e{length}-off"))
             for length in LENGTHS], rnd)
    compare(out, "With H5: longer epochs against 25 rounds",
            [(f"e{length} against e25", pick("silent", f"e{length}-on"), pick("silent", "e25-on"))
             for length in LENGTHS[1:]], rnd)


if __name__ == "__main__":
    report(sys.argv[1] if len(sys.argv) > 1 else "results-epoch")

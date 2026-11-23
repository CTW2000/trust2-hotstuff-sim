"""Unresponsive weight that builds up while the chain is live (paper §5.1 and the proposition on the tolerance of
unresponsive weight in the extended version; prototype DESIGN.md §15.52). What the reputation budget buys beyond the
exclusion from leader election: quorums are counted in voting power, so with a cut D_N on the replicas that do not
vote and D_O on the others, the others hold a quorum iff the base share u of the former is below (1 + 2 D_N - D_O)/3.

Equal base weights, n = 31. Replicas go down one after another (DOWN): 9 from view 1 (29.0%), a 10th (32.3%), an
11th (35.5%), a 12th (38.7%), a 13th (41.9%). A replica that is down sends no proposal and no vote (adversary.Offline;
its timeouts are still sent). Every run is done twice on the same seed: with B_rep = 0.10 and with B_rep = 0, where
convictions still exclude from leading and nothing is cut from the voting power.

Per phase and run: the share of views whose block commits; the largest share of the down replicas on the epoch
tables and the number of epochs in which it is not below 1/3 (the others have no quorum then); the smallest margin
(1 + 2 D_N - D_O)/3 - u. The simulator computes the tables from the facts of all views, committed or not, while the
protocol changes tables only through commits: a phase of the B_rep = 0.10 arm with epochs without a quorum is not a
phase the protocol would get through, and the report says so.

Run from the repository root:
    SIM_SCHEME=h1p python -m sim2.experiments.dirTtruMargin [run|report|all]
Out: results/dirTtru_margin<suffix>.csv and results/dirTtru_margin<suffix>.md."""
import csv
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

from sim2 import adversary as A
from sim2 import engine_event
from sim2 import ttru
from sim2.common import State
from sim2.experiments import dirTtruV12 as V
from sim2.experiments.ttru_perf import perf
from sim2.net import NetConfig, Network

N = V.N
DOWN = ((1, 9), (2000, 10), (4000, 11), (7000, 12), (9000, 13))    # (first view, replicas down from it on)
VIEWS = 10500
SEEDS = int(os.environ.get("SIM_SEEDS", "10"))
ARMS = (0.10, 0.0)


def tolerated(d_n, d_o):
    """The base share of the replicas that do not vote below which the others hold a quorum."""
    return (1.0 + 2.0 * d_n - d_o) / 3.0


def phases(views=None):
    """(first view, end view (exclusive), replicas down) of each phase."""
    end = (views or VIEWS) - 10
    firsts = [v for v, _ in DOWN if v < end]
    return [(v, (firsts[i + 1] if i + 1 < len(firsts) else end), c) for i, (v, c) in enumerate(DOWN[:len(firsts)])]


def starts_of(seed):
    """The replicas that go down, in the order in which they do, and the view from which each is down."""
    order = np.random.default_rng([seed, 97]).permutation(N)[:DOWN[-1][1]]
    starts, done = {}, 0
    for view, count in DOWN:
        for k in order[done:count]:
            starts[int(k)] = view
        done = count
    return starts


def job(args):
    b_rep, seed, views = args
    V.B_REP = b_rep                                   # V.build reads it (one job at a time per worker)
    base = np.full(N, 1.0 / N)
    starts = starts_of(seed)
    byz = np.zeros(N, bool)
    byz[list(starts)] = True
    rule, vw = V.build(None, None, base, graded=False)
    cfg = V.config(seed, rule, vw, byz, A.Offline(starts), views)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, **V.NETS["base"])), st, 1, views)
    c = V.tables(st, vw)
    tabs, cuts = c["tables"], c.get("cuts", [np.zeros(N)] * len(c["tables"]))
    epoch = vw.epoch
    honest_conv = V.honest_conv(st, views - 10)
    rows = []
    for lo, hi, count in phases(views):
        down = np.zeros(N, bool)
        down[[k for k, s in starts.items() if s <= lo]] = True
        u = float(base[down].sum())
        es = [e for e in range(len(tabs)) if lo <= e * epoch + 1 < hi]
        share = [float(tabs[e][down].sum()) for e in es]
        margin = [tolerated(float(cuts[e][down].sum()), float(cuts[e][~down].sum())) - u for e in es]
        rows.append(dict(b_rep=b_rep, seed=seed, first=lo, end=hi, down=count, u=u,
                         commit=perf(st, lo, hi)["commit"], share_max=max(share), share_end=share[-1],
                         epochs=len(es), epochs_no_quorum=sum(1 for x in share if x >= 1 / 3 - 1e-9),
                         margin_min=min(margin), cut_down_end=float(cuts[es[-1]][down].sum()),
                         honest_conv=sum(1 for v in honest_conv if lo <= v < hi)))
    return rows


def name(ext="csv"):
    return os.path.join(V.OUT, f"dirTtru_margin{ttru.suffix()}.{ext}")


def run(views=VIEWS, seeds=SEEDS):
    t0 = time.time()
    jobs = [(b, s, views) for s in range(seeds) for b in ARMS]
    with Pool(V.PROCS) as pool:
        rows = [r for rs in pool.map(job, jobs, chunksize=1) for r in rs]
    with open(name(), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"margin: {len(jobs)} runs, {time.time() - t0:.0f}s", flush=True)


def load():
    rows = []
    for r in csv.DictReader(open(name())):
        rows.append({k: (float(v) if k not in ("seed", "first", "end", "down", "epochs", "epochs_no_quorum",
                                               "honest_conv") else int(float(v))) for k, v in r.items()})
    return rows


def med(xs, d=3):
    xs = sorted(xs)
    return f"{float(np.median(xs)):.{d}f} [{xs[0]:.{d}f}, {xs[-1]:.{d}f}]"


def report():
    rows = load()
    seeds = len({r["seed"] for r in rows})
    out = [f"# Unresponsive weight that builds up (dirTtruMargin, {seeds} seeds, n = {N}, equal base weights)", "",
           "Median [min, max] over the seeds. `commit`: share of the views of the phase whose block commits. "
           "`share of the down replicas`: their largest share on the epoch tables of the phase (a quorum of the "
           "others needs it below 0.333). `epochs without a quorum`: epochs of the phase in which it is not, summed "
           "over the seeds. `margin`: the smallest (1 + 2 D_N - D_O)/3 - u over the epochs of the phase.", "",
           "| views | down | u | B_rep | commit | share of the down replicas | epochs without a quorum | margin | "
           "honest convictions |", "|---|---|---|---|---|---|---|---|---|"]
    for lo, hi, count in phases():
        for b in ARMS:
            g = [r for r in rows if r["first"] == lo and abs(r["b_rep"] - b) < 1e-12]
            if not g:
                continue
            out.append(f"| {lo}-{hi - 1} | {count} | {g[0]['u']:.3f} | {b:.2f} | {med([r['commit'] for r in g])} | "
                       f"{med([r['share_max'] for r in g])} | {sum(r['epochs_no_quorum'] for r in g)} of "
                       f"{sum(r['epochs'] for r in g)} | {med([r['margin_min'] for r in g])} | "
                       f"{sum(r['honest_conv'] for r in g)} |")
    out += ["", "The tables of the simulator follow the facts of all views, committed or not; the protocol changes "
            "tables only through commits. A phase of the B_rep = 0.10 arm that has epochs without a quorum is "
            "therefore one the protocol would not get through: read its commit share as an upper bound."]
    with open(name("md"), "w") as fh:
        fh.write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("run", "all"):
        run()
    if what in ("report", "all"):
        report()

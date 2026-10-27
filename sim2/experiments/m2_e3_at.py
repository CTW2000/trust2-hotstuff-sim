"""M2 / E3: AT soundness and completeness vs the failed-proposer signal (abstract models only).

For each protocol, timing model and adversary, measure per honest-led view and per colluder-led
view: (a) the failed-proposer rate (the evidence used in M1), (b) the AT accusation rate
(2f+1 timeouts with NR=1). Colluders claim NR=1 for honest leaders and NR=0 for colluding ones.
Theory (阶段1 Theorem AT, TR, generalised to f0 colluders): an honest leader can be accused only
if at least q - f0 honest replicas time out without its proposal (with f0 = f this is f+1); a
silent leader is always accused; a partial sender is never accused once it reaches at least
(n - f0) - q + 1 honest replicas (with f0 = f and n = 3f+1 this is 1, i.e. k_max = 0).
Modes:  (default) the main table;  "stress": heavy independent lateness eps = 0.1..0.5, where the
accusation rate of honest leaders is compared with the bound P(Bin(n - f0 - 1, eps) >= q - f0).
Run from the repository root:  python -m sim2.experiments.m2_e3_at [stress]
"""
import csv
import math
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

from sim2 import adversary as A
from sim2 import engine_fast
from sim2 import schedule as S
from sim2.common import RunConfig
from sim2.net import NetConfig, Network

OUT = os.path.join(os.path.dirname(__file__), "..", "results")


def partial_k(n, f0):
    """Smallest number of honest recipients that keeps a partial sender unaccused: the honest
    replicas that miss the proposal (n - f0 - k) must be fewer than q (colluders claim NR=0)."""
    q = (n + (n - 1) // 3) // 2 + 1
    return max(1, (n - f0) - q + 1)


def adversary(proto, kind, n, f0):
    frame = A.CollectorFraming() if proto == "P1" else A.WithholdVotesOnHonest()
    if kind == "framing":
        return A.Compose([frame, A.LieNR()])
    if kind == "silent":
        return A.Compose([frame, A.LieNR(), A.SilentLeader(1.0)])
    if kind == "partial_k1":
        return A.Compose([frame, A.LieNR(), A.PartialSend(1)])
    return A.Compose([frame, A.LieNR(), A.PartialSend(partial_k(n, f0))])


def job(args):
    proto, n, kind, eps, seed, views = args
    f0 = (n - 1) // 3 - 1 if n == 31 else 30
    net = Network(NetConfig(n=n, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps))
    cfg = RunConfig(n=n, views=views, seed=seed, protocol=proto, leader_rule=S.Uniform(),
                    byzantine=list(range(n - f0, n)), adversary=adversary(proto, kind, n, f0))
    t0 = time.time()
    r = engine_fast.run(cfg, net)
    V = views
    out = dict(protocol=proto, n=n, f0=f0, adversary=kind, eps=eps, seed=seed)
    for who, mask in (("honest", r.honest), ("byz", r.roles == 2)):
        us = [u for u in range(1, V - 10) if mask[r.leaders[u]]]
        out[f"{who}_views"] = len(us)
        out[f"{who}_failed"] = float(np.mean([not S.succeeded(r.prop_parent, u, V) for u in us]))
        out[f"{who}_accused"] = float(np.mean([r.nr_count[u] >= r.quorum for u in us]))
    out["secs"] = time.time() - t0
    return out


def stress_job(args):
    proto, f0, eps, seed = args
    n, views = 31, 3000
    q = (n + (n - 1) // 3) // 2 + 1
    net = Network(NetConfig(n=n, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps))
    cfg = RunConfig(n=n, views=views, seed=seed, protocol=proto, leader_rule=S.Uniform(),
                    byzantine=list(range(n - f0, n)), adversary=adversary(proto, "framing", n, f0))
    r = engine_fast.run(cfg, net)
    us = [u for u in range(1, views - 10) if r.honest[r.leaders[u]]]
    acc = np.array([r.nr_count[u] >= q for u in us])
    tc = np.array([bool(r.tc_exists[u]) for u in us])
    m, need = n - f0 - 1, q - f0
    bound = sum(math.comb(m, k) * eps ** k * (1 - eps) ** (m - k) for k in range(need, m + 1))
    return dict(protocol=proto, f0=f0, eps=eps, seed=seed, honest_views=len(us), tc_views=int(tc.sum()),
                accused=float(acc.mean()), accused_given_tc=float(acc[tc].mean()) if tc.any() else 0.0,
                bound=bound)


def stress():
    jobs = [(p, f0, e, s) for p in ("P1", "P2") for f0 in (9, 10) for e in (0.1, 0.2, 0.3, 0.5) for s in range(2)]
    with Pool(8) as pool:
        rows = pool.map(stress_job, jobs)
    with open(os.path.join(OUT, "m2_e3_at_stress.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("| 协议 | 同伙 f0（f=10） | ε | 诚实领导者被 AT 指控率 | 其中以 TC 结束的视图中 | 上界 P(Bin(n-f0-1,ε) ≥ q-f0) |")
    print("|---|---|---|---|---|---|")
    for k in sorted({(r["protocol"], r["f0"], r["eps"]) for r in rows}):
        g = [r for r in rows if (r["protocol"], r["f0"], r["eps"]) == k]
        print(f"| {k[0]} | {k[1]} | {k[2]} | {np.mean([r['accused'] for r in g]):.4f} | "
              f"{np.mean([r['accused_given_tc'] for r in g]):.4f} | {g[0]['bound']:.4f} |")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "stress":
        return stress()
    jobs = [(p, n, k, e, s, 4000) for p in ("P1", "P2") for n in (31, 100)
            for k in ("framing", "silent", "partial_k1", "partial_kmin") for e in (0.0, 0.01) for s in range(2)]
    with Pool(8) as pool:
        rows = pool.map(job, jobs)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "m2_e3_at.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("| 协议 | n | 对手（另加陷害与谎报 NR） | ε | 诚实：失败提议者率 | 诚实：AT 指控率 | 同伙：失败提议者率 | 同伙：AT 指控率 |")
    print("|---|---|---|---|---|---|---|---|")
    keys = sorted({(r["protocol"], r["n"], r["adversary"], r["eps"]) for r in rows})
    for k in keys:
        g = [r for r in rows if (r["protocol"], r["n"], r["adversary"], r["eps"]) == k]
        m = lambda c: np.mean([r[c] for r in g])
        print(f"| {k[0]} | {k[1]} | {k[2]} | {k[3]:g} | {m('honest_failed'):.3f} | {m('honest_accused'):.4f} | "
              f"{m('byz_failed'):.3f} | {m('byz_accused'):.3f} |")
    print(f"compute {sum(r['secs'] for r in rows):.0f}s")


if __name__ == "__main__":
    main()

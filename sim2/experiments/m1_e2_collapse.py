"""M1 / E2: collapse of failure-rate reputation rules under framing, at protocol level.

Setting (matches the abstract model of T3-dyn D4 / D4-W): P1 (votes to the next leader), adversary
A1 (a colluder next leader withholds the QC of an honest leader), natural failures rho_nat = 0.01
for every leader, so an honest leader fails w.p. rho(lambda) = rho_nat + (1 - rho_nat) * lambda with
lambda the colluder share of next leaders, and colluder leaders fail only naturally. Rules use the
same estimator as sim/d4_sim.py (per-replica forgetting failure rate, memory W, prior rho_nat):
  exponential profile  weight exp(-eta r_hat), sensitivity s = eta (1 - rho_nat)
  threshold profile    weight 1000 if r_hat < theta else 1
Predictions: mean field (D4, W = infinity) and finite memory (D4-W), from sim/d4_*.py.
Measured: colluder leader share over the second half of each run.
Run from the repository root:  python -m sim2.experiments.m1_e2_collapse [exp|thr|all]
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

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "..", "sim"))
import d4_finite_memory as D4W  # noqa: E402
import d4_sim as D4  # noqa: E402

RHO_NAT = D4.RHO_NAT
OUT = os.path.join(HERE, "..", "results")


def job(args):
    kind, n, f0, param, W, seed, views = args
    if kind == "exp":
        rule = S.ForgetExp(eta=param / (1 - RHO_NAT), W=W, prior=RHO_NAT)
    else:
        rule = S.ForgetThreshold(theta=param, W=W, K=1000.0, prior=RHO_NAT)
    net = Network(NetConfig(n=n, seed=seed, regions=3, jitter_max_ms=2.0))
    cfg = RunConfig(n=n, views=views, seed=seed, protocol="P1", leader_rule=rule, rho_nat=RHO_NAT,
                    byzantine=list(range(n - f0, n)), adversary=A.CollectorFraming())
    t0 = time.time()
    r = engine_fast.run(cfg, net)
    share = (r.roles[r.leaders[1:views + 1]] == 2).astype(float)
    half = share[views // 2:]
    q = len(half) // 10
    return dict(kind=kind, n=n, f0=f0, beta0=f0 / n, param=param, W=W, seed=seed, views=views,
                lam_half=half.mean(), lam_last10=half[-q:].mean(), secs=time.time() - t0,
                fallback=r.fallback_views, tc_kernel=r.tc_kernel_views)


def predictions(kind, beta0, param, W, cache={}):
    if kind == "exp":
        mf = D4.mean_field_exp(beta0, param)
        dw = D4W.fixed_point(beta0, lambda r: D4W.G_time_exp(r, W, param))
    else:
        mf = D4.mean_field_threshold(beta0, param)
        key = (W, param)
        if key not in cache:
            cache[key] = D4W.ThresholdProfile(W, param)
        dw = D4W.fixed_point(beta0, cache[key].G)
    return mf, dw


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    jobs = []
    if which in ("exp", "all"):
        for f0 in (3, 6, 9):
            for s in (0.0, 1.0, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0):
                for seed in range(2):
                    jobs.append(("exp", 31, f0, s, 200, seed, 60000))
    if which in ("thr", "all"):
        for W, views in ((50, 100000), (200, 200000)):
            for f0 in (1, 2, 3, 4, 5, 6, 8, 10):
                for seed in range(2):
                    jobs.append(("thr", 100, f0, 0.1, W, seed, views))
    t0 = time.time()
    with Pool(8) as pool:
        rows = pool.map(job, jobs, chunksize=1)
    for r in rows:
        r["pred_meanfield"], r["pred_d4w"] = predictions(r["kind"], r["beta0"], r["param"], r["W"])
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"m1_e2_collapse_{which}.csv")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path}; wall {time.time() - t0:.0f}s, compute {sum(r['secs'] for r in rows):.0f}s")
    keys = sorted({(r["kind"], r["n"], r["f0"], r["param"], r["W"]) for r in rows})
    print("| 剖面 | n | β0 | 参数 | W | 同伙领导份额（后半段） | 最后 10% | 平均场 D4 | 有限记忆 D4-W |")
    print("|---|---|---|---|---|---|---|---|---|")
    for k in keys:
        g = [r for r in rows if (r["kind"], r["n"], r["f0"], r["param"], r["W"]) == k]
        print(f"| {k[0]} | {k[1]} | {k[2] / k[1]:.3f} | {k[3]:g} | {k[4]} | "
              f"{np.mean([r['lam_half'] for r in g]):.3f} | {np.mean([r['lam_last10'] for r in g]):.3f} | "
              f"{g[0]['pred_meanfield']:.3f} | {g[0]['pred_d4w']:.3f} |")


if __name__ == "__main__":
    main()

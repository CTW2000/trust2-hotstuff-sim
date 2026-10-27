"""M1 / E1: protocol-level framing rates vs theory (abstract models only).

For P1 (votes to the next leader) under A1 collector framing and P2 (vote broadcast) under A2 vote
withholding, with a uniform random leader each view (so the colluder share of every role is the
base share), measure the failure rate of honest leaders and split it by whether the next leader
is a colluder.

Theory (阶段1 Theorem P, §1.8):
  P1, model S: an honest leader fails iff the next leader is a colluder: rho = lambda (kappa = 1).
  P2, model S: rho = 0.
  P2, model P: an honest leader fails iff more than (n - f0) - q of the other honest replicas miss
               its proposal: rho = P(Binomial(n - f0 - 1, eps) >= n - f0 - q + 1); independent of
               the roles colluders hold.
Run from the repository root:  python -m sim2.experiments.m1_e1_framing
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


def honest_outcomes(r):
    V = r.know.shape[0] - 1
    rows = []
    for u in range(1, V - 10):
        L = r.leaders[u]
        if not r.honest[L]:
            continue
        rows.append((not S.succeeded(r.prop_parent, u, V), r.roles[r.leaders[u + 1]] == 2))
    a = np.array(rows, dtype=bool)
    return a[:, 0], a[:, 1]


def theory(proto, n, f0, eps):
    q = (n + (n - 1) // 3) // 2 + 1
    if proto == "P1":
        return None  # = lambda, compared per run with the measured colluder share of next leaders
    if eps == 0:
        return 0.0
    m, need = n - f0 - 1, n - f0 - q + 1
    return sum(math.comb(m, k) * eps ** k * (1 - eps) ** (m - k) for k in range(need, m + 1))


def job(args):
    proto, n, beta0, eps, seed, views = args
    f0 = int(math.floor(beta0 * n + 0.5))
    adv = A.CollectorFraming() if proto == "P1" else A.WithholdVotesOnHonest()
    net = Network(NetConfig(n=n, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps))
    cfg = RunConfig(n=n, views=views, seed=seed, protocol=proto, leader_rule=S.Uniform(),
                    byzantine=list(range(n - f0, n)), adversary=adv)
    t0 = time.time()
    r = engine_fast.run(cfg, net)
    fail, next_byz = honest_outcomes(r)
    return dict(protocol=proto, n=n, f0=f0, beta0=f0 / n, eps=eps, seed=seed,
                honest_views=len(fail), rho=fail.mean(), lam_next=next_byz.mean(),
                rho_given_next_byz=fail[next_byz].mean() if next_byz.any() else float("nan"),
                rho_given_next_honest=fail[~next_byz].mean() if (~next_byz).any() else float("nan"),
                theory=theory(proto, n, f0, eps), secs=time.time() - t0)


def main():
    views = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
    jobs = [(p, n, b, e, s, views) for p in ("P1", "P2") for n in (31, 100) for b in (0.1, 0.2, 0.3)
            for e in (0.0, 1e-3, 1e-2) for s in range(3)]
    with Pool(8) as pool:
        rows = pool.map(job, jobs)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "m1_e1_framing.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    # aggregate over seeds
    print("| 协议 | n | β0 | ε | 诚实领导者失败率 ρ | 理论 | P(失败∣下一任是同伙) | P(失败∣下一任诚实) | 下一任是同伙的比例 |")
    print("|---|---|---|---|---|---|---|---|---|")
    keys = sorted({(r["protocol"], r["n"], r["f0"], r["eps"]) for r in rows})
    for p, n, f0, e in keys:
        g = [r for r in rows if (r["protocol"], r["n"], r["f0"], r["eps"]) == (p, n, f0, e)]
        rho = np.mean([r["rho"] for r in g])
        lam = np.mean([r["lam_next"] for r in g])
        th = lam if p == "P1" else g[0]["theory"]
        print(f"| {p} | {n} | {f0 / n:.2f} | {e:g} | {rho:.4f} | {th:.4f} | "
              f"{np.nanmean([r['rho_given_next_byz'] for r in g]):.3f} | "
              f"{np.nanmean([r['rho_given_next_honest'] for r in g]):.4f} | {lam:.3f} |")
    print(f"total compute {sum(r['secs'] for r in rows):.0f}s")


if __name__ == "__main__":
    main()

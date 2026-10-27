"""Direction A: vote-carrying timeouts in P1 (collector accountability). Abstract models only.

With cfg.timeout_votes, a replica that times out puts its vote of that view into its timeout; anyone
who collects 2f+1 such votes reconstructs QC(v). The Jolteon TC rule still lets a colluding collector
orphan the block (the TC's highQC predates the reconstruction), so direction A is used as EVIDENCE:
  leader exonerated:  evidence "failed_A" = failed proposer unless QC(v) was reconstructed;
  collector blamed:   collector_fault(v) = QC(v) reconstructed from timeouts but the block orphaned.
Runs use the reference engine (engine_fast delegates; see engine_fast.run).

Part "attr": P1, n = 31, uniform leaders, colluders frame as collectors (and omit their votes from
their timeouts) and frame honest collectors (vote, but not to the collector). Per honest-led view:
old failed-proposer rate vs direction-A rate; per collector: blame rate (honest vs colluding).
Part "collapse": the M1/E2 threshold-profile collapse, now with direction-A evidence and blaming
collectors, vs the old evidence.
Run from the repository root:  python -m sim2.experiments.dirA [attr|collapse]
"""
import csv
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
N = 31


def attr_job(args):
    f0, eps, seed = args
    views = 3000
    byz = list(range(N - f0, N))
    adv = A.Compose([A.CollectorFraming(omit_tmo_votes=True), A.FrameCollector()])
    net = Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps))
    cfg = RunConfig(n=N, views=views, seed=seed, protocol="P1", leader_rule=S.Uniform(), byzantine=byz,
                    adversary=adv, timeout_votes=True)
    r = engine_fast.run(cfg, net)
    us = range(1, views - 10)
    old, newf, blame_h, blame_b = [], [], [], []
    for u in us:
        L, C = r.leaders[u], r.leaders[u + 1]
        failed = not S.succeeded(r.prop_parent, u, views)
        fault = bool(r.qc_via_tmo[u]) and failed
        if r.honest[L]:
            old.append(failed)
            newf.append(failed and not r.qc_via_tmo[u])
        (blame_h if r.honest[C] else blame_b).append(fault)
    return dict(f0=f0, eps=eps, seed=seed, leader_failed_old=float(np.mean(old)),
                leader_failed_A=float(np.mean(newf)), honest_collector_blamed=float(np.mean(blame_h)),
                colluder_collector_blamed=float(np.mean(blame_b)))


def collapse_job(args):
    evidence, f0, seed = args
    views = 20000
    byz = list(range(N - f0, N))
    if evidence == "old":
        rule = S.ForgetThreshold(theta=0.1, W=50, K=1000.0, prior=0.01, evidence="failed")
    else:
        rule = S.ForgetThreshold(theta=0.1, W=50, K=1000.0, prior=0.01, evidence="failed_A", blame_collector=True)
    net = Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0))
    cfg = RunConfig(n=N, views=views, seed=seed, protocol="P1", leader_rule=rule, rho_nat=0.01, byzantine=byz,
                    adversary=A.CollectorFraming(omit_tmo_votes=True), timeout_votes=True)
    t0 = time.time()
    r = engine_fast.run(cfg, net)
    share = (r.roles[r.leaders[1:views + 1]] == 2).astype(float)
    half = share[views // 2:]
    return dict(evidence=evidence, f0=f0, beta0=f0 / N, seed=seed, lam_half=float(half.mean()),
                lam_last10=float(half[-len(half) // 10:].mean()), secs=time.time() - t0)


def main():
    part = sys.argv[1] if len(sys.argv) > 1 else "attr"
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    if part == "attr":
        jobs = [(f0, e, s) for f0 in (9, 10) for e in (0.0, 0.01, 0.05) for s in range(2)]
        with Pool(8) as pool:
            rows = pool.map(attr_job, jobs)
        print("| 同伙 f0（f=10） | ε | 诚实领导者被记失败：旧证据 | 方向 A 证据 | 诚实收集者被追究 | 同伙收集者被追究 |")
        print("|---|---|---|---|---|---|")
        for k in sorted({(r["f0"], r["eps"]) for r in rows}):
            g = [r for r in rows if (r["f0"], r["eps"]) == k]
            m = lambda c: np.mean([r[c] for r in g])
            print(f"| {k[0]} | {k[1]} | {m('leader_failed_old'):.3f} | {m('leader_failed_A'):.4f} | "
                  f"{m('honest_collector_blamed'):.4f} | {m('colluder_collector_blamed'):.3f} |")
    else:
        jobs = [(ev, f0, s) for ev in ("old", "A") for f0 in (1, 2, 3, 4, 6, 9) for s in range(2)]
        with Pool(8) as pool:
            rows = pool.map(collapse_job, jobs, chunksize=1)
        print("| β0 | 旧证据：同伙领导份额（后半段 / 最后 10%） | 方向 A 证据 + 追究收集者 |")
        print("|---|---|---|")
        for f0 in (1, 2, 3, 4, 6, 9):
            cell = lambda ev: (lambda g: f"{np.mean([r['lam_half'] for r in g]):.3f} / {np.mean([r['lam_last10'] for r in g]):.3f}")(
                [r for r in rows if r["evidence"] == ev and r["f0"] == f0])
            print(f"| {f0 / N:.3f} | {cell('old')} | {cell('A')} |")
    with open(os.path.join(OUT, f"dirA_{part}.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wall {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

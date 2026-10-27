"""M3 / E6: the performance layer (slot-duration score + bounded tilt) under attack; abstract models only.

Network: 6 regions spread over a large area (heterogeneous latency), P2, n = 31, tau = 2000 ms.
Colluders: f0 replicas; in every scenario they lie in slot-duration reports (+inf for honest
leaders, 0 for their own) and pick reports when they assemble a certificate.
Scenarios:
  behave       colluders follow the protocol (measures their leader share = "exposure")
  slowX        colluders withhold votes on honest leaders and delay their own proposals by X ms
               (X = 150, 300, 600, 1500; 1500 is close to the timeout)
  partial      colluders withhold votes, lie in NR bits, and send each own proposal to just enough
               honest replicas to stay unaccused (the view fails, not attributable)
  partialP     as partial, in P% of their views (P = 10, 30)
The worst case of a rule is the maximum over these fixed strategies (not a proven best response).
Rules: static (uniform), R5 (AT + CUSUM exclusion, constant share, cap 0.5), R6 = R5 + tilt with
L per ms and K. Measured after a warm-up: mean slot time (first honest entry to the next), failed
views, colluder leader share, mean slot time of honest-led views.
Run from the repository root:  python -m sim2.experiments.m3_e6_perf [f0]
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
from sim2.experiments.m2_e3_at import partial_k
from sim2.net import NetConfig, Network

OUT = os.path.join(os.path.dirname(__file__), "..", "results")
N, VIEWS, WARM, TAU = 31, 6000, 1000, 2000.0
NET = dict(regions=6, region_c0_ms=8.0, region_c1_ms=120.0, jitter_max_ms=10.0)


def rules():
    r = {"static": None, "R5": "R5"}
    for L in (1 / 800, 1 / 400, 1 / 200, 1 / 100):
        for K in (10, 50):
            r[f"R6 L=1/{round(1 / L)} K={K}"] = (L, K)
    return r


def make_rule(spec):
    excl = S.CusumExclusion(evidence="at", D=500, cap=0.5, Wq=500)
    if spec is None:
        return S.Uniform()
    if spec == "R5":
        return excl
    L, K = spec
    return S.PerfTilt(L=L, K=K, W=20, V=2000, exclusion=excl)


def adversary(name, f0):
    k = partial_k(N, f0)
    if name == "behave":
        return A.Adversary()
    if name.startswith("slow"):
        return A.Compose([A.WithholdVotesOnHonest(), A.SlowLeader(float(name[4:]))])
    if name == "data1":
        return A.Compose([A.WithholdVotesOnHonest(), A.LieNR(), A.DataWithhold(k=1)])
    if name == "data0":
        return A.Compose([A.WithholdVotesOnHonest(), A.LieNR(), A.DataWithhold(k=0)])
    if name == "data0_30":
        return A.Compose([A.WithholdVotesOnHonest(), A.LieNR(), A.DataWithhold(k=0, p=0.3)])
    if name == "skew":
        return A.Compose([A.SkewVotes(g=5), A.LieNR()])
    if name == "skew+data1":
        return A.Compose([A.SkewVotes(g=5), A.LieNR(), A.DataWithhold(k=1)])
    p = 1.0 if name == "partial" else int(name[7:]) / 100.0
    return A.Compose([A.WithholdVotesOnHonest(), A.LieNR(), A.PartialSend(k, p=p)])


SCEN = ("behave", "slow150", "slow300", "slow600", "slow1500", "partial10", "partial30", "partial",
        "data1", "data0", "data0_30", "skew", "skew+data1")
CONFIGS = {"base": dict(vote_needs_parent=False, nr_requires_data=False),
           "parent": dict(vote_needs_parent=True, nr_requires_data=False),
           "parent+nrdata": dict(vote_needs_parent=True, nr_requires_data=True)}


def job(args):
    rname, scen, f0, seed, conf = args
    spec = rules()[rname]
    byz = list(range(N - f0, N))
    net = Network(NetConfig(n=N, seed=seed, **NET))
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol="P2", tau_ms=TAU, leader_rule=make_rule(spec),
                    byzantine=byz, adversary=adversary(scen, f0), **CONFIGS[conf])
    t0 = time.time()
    r = engine_fast.run(cfg, net)
    stale = S.verify_leaders(r, cfg)
    E = r.know[:, r.honest].min(axis=1)
    slot = np.diff(E)[WARM:VIEWS - 10]                 # slot of view v = E(v) - E(v-1)
    us = np.arange(WARM + 1, VIEWS - 9)
    lead = r.leaders[us]
    fail = np.array([not S.succeeded(r.prop_parent, u, VIEWS) for u in us])
    hon = r.honest[lead]
    return dict(rule=rname, scenario=scen, f0=f0, seed=seed, config=conf, slot_ms=float(slot.mean()),
                fail_rate=float(fail.mean()), colluder_share=float(np.mean(r.roles[lead] == 2)),
                honest_slot_ms=float(slot[hon].mean()), stale_leaders=stale, secs=time.time() - t0)


def main():
    f0 = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    conf = sys.argv[2] if len(sys.argv) > 2 else "base"
    jobs = [(rn, sc, f0, s, conf) for rn in rules() for sc in SCEN for s in range(3)]
    t0 = time.time()
    with Pool(8) as pool:
        rows = pool.map(job, jobs, chunksize=2)
    os.makedirs(OUT, exist_ok=True)
    print(f"config {conf}: {CONFIGS[conf]}")
    with open(os.path.join(OUT, f"m3_e6_perf_f{f0}_{conf}.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    assert all(r["stale_leaders"] == 0 for r in rows), "stale facts used by a leader rule"
    m = lambda rn, sc, c: np.mean([r[c] for r in rows if r["rule"] == rn and r["scenario"] == sc])
    print(f"f0 = {f0} of n = {N}; wall {time.time() - t0:.0f}s")
    print("| 规则 | 老实表现：同伙份额（暴露） | 老实表现：平均槽位 | " + " | ".join(SCEN[1:])
          + " | **最坏平均槽位** | 最坏情形的失败率 |")
    print("|" + "---|" * (len(SCEN) + 4))
    for rn in rules():
        worst_sc = max(SCEN[1:], key=lambda sc: m(rn, sc, "slot_ms"))
        print(f"| {rn} | {m(rn, 'behave', 'colluder_share'):.3f} | {m(rn, 'behave', 'slot_ms'):.0f} | "
              + " | ".join(f"{m(rn, sc, 'slot_ms'):.0f}" for sc in SCEN[1:])
              + f" | **{m(rn, worst_sc, 'slot_ms'):.0f}**（{worst_sc}） | {m(rn, worst_sc, 'fail_rate'):.3f} |")


if __name__ == "__main__":
    main()

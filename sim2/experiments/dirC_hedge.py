"""Direction C, first experiment: rewarding fast leaders under a share cap (R7 capped Hedge) vs R6.
Abstract models only. P2, 6-region network, n = 31, tau = 2000 ms, same estimates as M3.
Measured: (1) clean latency gain with no colluders; (2) colluders' exposure (they withhold votes on
honest leaders and lie in reports, never fail themselves) vs the cap bound c*beta0; (3) worst mean
slot time over the M3 attack strategies.
Run from the repository root:  python -m sim2.experiments.dirC_hedge
"""
import csv
import os
import time
from multiprocessing import Pool

import numpy as np

from sim2 import adversary as A
from sim2 import engine_fast
from sim2 import schedule as S
from sim2.common import RunConfig
from sim2.experiments.m3_e6_perf import NET, N, OUT, TAU, VIEWS, WARM, adversary
from sim2.net import NetConfig, Network


def rules():
    r = {"uniform": None, "R6 L=1/200 K=50": ("R6", 1 / 200, 50)}
    for eta in (1 / 50, 1 / 20):
        for c in (1.5, 2.0, 3.0):
            r[f"R7 eta=1/{round(1 / eta)} c={c}"] = ("R7", eta, c)
    return r


def make(spec):
    excl = S.CusumExclusion(evidence="at", D=500, cap=0.5, Wq=500)
    if spec is None:
        return S.Uniform()
    if spec[0] == "R6":
        return S.PerfTilt(L=spec[1], K=spec[2], W=20, V=2000, exclusion=excl)
    return S.CappedHedge(eta=spec[1], a=0.5, c=spec[2], W=20, V=2000, exclusion=excl)


SCEN = {"clean": (0, None), "exposure": (9, "withhold"), "partial": (9, "partial"), "slow600": (9, "slow600"),
        "data0": (9, "data0")}


def job(args):
    rname, scen, seed = args
    f0, adv_name = SCEN[scen]
    if adv_name == "withhold":
        adv = A.WithholdVotesOnHonest()
    elif adv_name is None:
        adv = None
    else:
        adv = adversary(adv_name, f0)
    net = Network(NetConfig(n=N, seed=seed, **NET))
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol="P2", tau_ms=TAU, leader_rule=make(rules()[rname]),
                    byzantine=list(range(N - f0, N)), adversary=adv)
    r = engine_fast.run(cfg, net)
    E = r.know[:, r.honest].min(axis=1)
    slot = np.diff(E)[WARM:VIEWS - 10]
    lead = r.leaders[WARM + 1:VIEWS - 9]
    return dict(rule=rname, scenario=scen, seed=seed, slot_ms=float(slot.mean()),
                colluder_share=float(np.mean(r.roles[lead] == 2)) if f0 else 0.0)


def main():
    jobs = [(rn, sc, s) for rn in rules() for sc in SCEN for s in range(3)]
    t0 = time.time()
    with Pool(8) as pool:
        rows = pool.map(job, jobs, chunksize=2)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "dirC_hedge.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    m = lambda rn, sc, c: np.mean([r[c] for r in rows if r["rule"] == rn and r["scenario"] == sc])
    base = m("uniform", "clean", "slot_ms")
    print(f"wall {time.time() - t0:.0f}s")
    print("| 规则 | 无同伙：平均槽位（相对均匀随机） | 暴露（同伙 9 个，基础 0.29） | 上限 c·β0 | 部分发送 | 拖慢 600 | 扣数据 | 最坏 |")
    print("|---|---|---|---|---|---|---|---|")
    for rn, spec in rules().items():
        cap = f"{spec[2] * 9 / N:.2f}" if spec and spec[0] == "R7" else "—"
        worst = max(m(rn, sc, "slot_ms") for sc in ("partial", "slow600", "data0"))
        print(f"| {rn} | {m(rn, 'clean', 'slot_ms'):.1f}（{100 * (m(rn, 'clean', 'slot_ms') / base - 1):+.1f}%） | "
              f"{m(rn, 'exposure', 'colluder_share'):.3f} | {cap} | {m(rn, 'partial', 'slot_ms'):.0f} | "
              f"{m(rn, 'slow600', 'slot_ms'):.0f} | {m(rn, 'data0', 'slot_ms'):.0f} | {worst:.0f} |")


if __name__ == "__main__":
    main()

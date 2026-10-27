"""M2 / E4: CUSUM exclusion on AT evidence vs on the failed-proposer signal (abstract models only).

Setting: P1, n = 31, f0 = 9 colluders, natural failures rho_nat = 0.01. Colluders frame honest
leaders as collectors (A1), lie in AT bits (framing NR=1 / shielding NR=0), and are silent in
their own views with probability 1/2 (an attributable attack).
Rules (all: constant share before conviction, CUSUM with q = 0.5, gamma = 1e4, h = ln gamma):
  AT       evidence = AT accusation, rho_bar = rho_nat = 0.01
  failed*  evidence = failed proposer, rho_bar tuned to the worst framed rate 0.01 + 0.99 * beta0
  failed   evidence = failed proposer, rho_bar = 0.01 (not tuned to framing)
Measured: each colluder's own leader opportunities before its first exclusion (detection delay),
honest exclusion events per 10^4 honest opportunities (false exclusions), and colluder-led failed
views before exclusion (excess failures, L1).
Theory (T3): delay ~ ln(gamma) / I(q_B, rho), with q_B = 0.505 (silent half the time + natural).
Run from the repository root:  python -m sim2.experiments.m2_e4_cusum
"""
import csv
import math
import os
import time
from multiprocessing import Pool

import numpy as np

from sim2 import adversary as A
from sim2 import engine_fast
from sim2 import schedule as S
from sim2.common import RunConfig
from sim2.net import NetConfig, Network

OUT = os.path.join(os.path.dirname(__file__), "..", "results")
N, F0, RHO_NAT, GAMMA, VIEWS = 31, 9, 0.01, 1e4, 20000
Q_B = 0.5 + 0.5 * RHO_NAT


def kl(a, b):
    return a * math.log(a / b) + (1 - a) * math.log((1 - a) / (1 - b))


def rules():
    worst = RHO_NAT + (1 - RHO_NAT) * F0 / N
    return {"AT": S.CusumExclusion(evidence="at", rho_bar=RHO_NAT, gamma=GAMMA, D=2000),
            "failed*": S.CusumExclusion(evidence="failed", rho_bar=worst, gamma=GAMMA, D=2000),
            "failed": S.CusumExclusion(evidence="failed", rho_bar=RHO_NAT, gamma=GAMMA, D=2000)}


def job(args):
    name, seed = args
    rule = rules()[name]
    byz = list(range(N - F0, N))
    adv = A.Compose([A.CollectorFraming(), A.LieNR(), A.SilentLeader(0.5)])
    net = Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0))
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol="P1", leader_rule=rule, rho_nat=RHO_NAT,
                    byzantine=byz, adversary=adv)
    t0 = time.time()
    r = engine_fast.run(cfg, net)
    assert S.verify_leaders(r, cfg) == 0, "a leader was computed from facts that later changed"
    first_excl = {}
    honest_excl = 0
    for ev, k, u in r.rule_log:
        if ev != "exclude":
            continue
        if r.roles[k] == 2:
            first_excl.setdefault(k, u)
        else:
            honest_excl += 1
    led = r.leaders[1:VIEWS + 1]
    views = np.arange(1, VIEWS + 1)
    delays, excess = [], []
    for k in byz:
        mine = views[led == k]
        cut = first_excl.get(k, VIEWS + 1)
        before = mine[mine <= cut]          # the view that triggers the exclusion is an own opportunity too
        delays.append(len(before) if k in first_excl else np.nan)
        excess.append(sum(not S.succeeded(r.prop_parent, u, VIEWS) for u in before))
    honest_opp = int(np.isin(led, np.flatnonzero(r.honest)).sum())
    return dict(rule=name, seed=seed, byz_detected=int(np.sum(~np.isnan(delays))),
                delay_mean=float(np.nanmean(delays)) if not np.all(np.isnan(delays)) else float("nan"),
                excess_failed=float(np.mean(excess)), honest_exclusions=honest_excl,
                honest_opportunities=honest_opp,
                false_excl_per_1e4=1e4 * honest_excl / max(honest_opp, 1), secs=time.time() - t0)


def main():
    jobs = [(name, s) for name in ("AT", "failed*", "failed") for s in range(20)]
    with Pool(8) as pool:
        rows = pool.map(job, jobs)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "m2_e4_cusum.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    worst = RHO_NAT + (1 - RHO_NAT) * F0 / N
    theory = {"AT": math.log(GAMMA) / kl(Q_B, RHO_NAT), "failed*": math.log(GAMMA) / kl(Q_B, worst),
              "failed": float("nan")}
    print("| 规则 | 检出的同伙（共 9 个/种子） | 检测延迟（含触发的那一次；均值 ± 标准误） | T3 一阶近似 ln γ / I | 被排除前同伙领导的失败视图（原始数） | 诚实误排除（每万次机会） |")
    print("|---|---|---|---|---|---|")
    for name in ("AT", "failed*", "failed"):
        g = [r for r in rows if r["rule"] == name]
        d = np.array([r["delay_mean"] for r in g])
        print(f"| {name} | {np.mean([r['byz_detected'] for r in g]):.1f} | {np.nanmean(d):.2f} ± {np.nanstd(d) / np.sqrt(len(d)):.2f} | "
              f"{theory[name]:.1f} | {np.mean([r['excess_failed'] for r in g]):.1f} | "
              f"{np.mean([r['false_excl_per_1e4'] for r in g]):.1f} |")
    print(f"compute {sum(r['secs'] for r in rows):.0f}s")


if __name__ == "__main__":
    main()

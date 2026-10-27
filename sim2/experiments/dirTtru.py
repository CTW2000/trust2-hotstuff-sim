"""T_tru weighted voting at protocol level (信任2.0_方案重构说明 v0.4 §6 step 3). Abstract models only.

Population: n = 31 (10 licensed, 12 uncertified, 9 small), Pareto stakes; license value K = 0.05
(stake units, total stake 1); base weight = CapNorm(stake + pi*K for licensed), cap 0.10, uncertified
class at most 0.25; voting shares per epoch from ttru.TtruWeights (reputation budget, r_min 0.7).
A node's bribery cost is what it loses when proven guilty: stake + pi*K if licensed.

Part "econ" (E-T1) was removed after review (信任2.0_区域图与加权_审查 #1-#2): silencing the bought
nodes is a liveness attack that leaves no G1 evidence, so pricing it at stake + pi*K was wrong, and
the halting outcome equalled the static test "bought share >= 1/3" in every run. The economic cost
model is evaluated statically in ttru/ttru_region.py.
Part "at" (E-T2): AT + CUSUM under weighted voting vs counting: colluders (base share ~0.24, the
cheapest to bribe) lead silently, partially send to 2 random honest replicas, or send to the k
heaviest honest replicas ("targeted", k the smallest with a share above 1 - beta - x, which evades
AT at threshold 2/3), or frame honest leaders ("lienr": colluders claim NR=1 in honest leaders' views,
on top of late messages); AT threshold x (cfg.at_share) 2/3 or 1/2; network model S, eps up to 0.20.
Weight-based exclusion cap (cap_weights = base).
Part "budget" (E-T3): P1 with collector framing; the leader rule convicts on framable evidence
("failed") or on AT; colluders (base share ~0.24) also misbehave detectably (silent leader, p = 0.3)
or not; colluder voting share over epochs vs the single-table bound base / (1 - b_rep), b_rep in
{0.05, 0.10, 0.20}; reputation does not recover while a replica is excluded.
Environment: SIM_PROCS (default 8), SIM_SEEDS (default 2).
Run from the repository root:  python -m sim2.experiments.dirTtru [at|budget]
"""
import csv
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

from sim2 import adversary as A
from sim2 import engine_event
from sim2 import schedule as S
from sim2 import ttru
from sim2.common import RunConfig, State
from sim2.net import NetConfig, Network

OUT = os.path.join(os.path.dirname(__file__), "..", "results")
N, NL, NU, NA = 31, 10, 12, 9
K, CAP, UMAX = 0.05, 0.10, 0.25          # 10 licensed x 0.10 >= 1: feasible for every pi
Q = (N + (N - 1) // 3) // 2 + 1
PROCS = int(os.environ.get("SIM_PROCS", "8"))
SEEDS = int(os.environ.get("SIM_SEEDS", "8"))


def setup(seed, pi):
    cls, s = ttru.population(NL, NU, NA, seed)
    base = ttru.base_weights(cls, s, K, pi, CAP, UMAX)
    cost = s + np.where(cls == "L", pi * K, 0.0)
    return cls, s, base, cost


def cheapest_set(base, cost, share, max_share=None):
    """Cheapest nodes (by cost per weight) until their base share reaches `share`; with max_share, nodes
    that would push the share above it are skipped (keeps the colluders below 1/3 in whale populations)."""
    byz = np.zeros(len(base), bool)
    acc = 0.0
    for i in np.argsort(cost / base):
        if acc >= share:
            break
        if max_share is not None and acc + base[i] > max_share:
            continue
        byz[i] = True
        acc += base[i]
    return byz


def evade_k(base, byz, x):
    """Smallest k such that the k heaviest honest replicas hold more than 1 - beta - x."""
    beta = float(base[byz].sum())
    hs = np.cumsum(np.sort(base[~byz])[::-1])
    return int(np.argmax(hs > 1 - beta - x + 1e-9)) + 1


def at_job(args):
    weighted, adv_name, x, eps, seed = args
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, 0.2)
    rule = S.CusumExclusion(evidence="at", D=500, cap=0.5, Wq=500, cap_weights=base if weighted else None)
    vw = ttru.TtruWeights(base, epoch=100, rule=rule) if weighted else None
    k = 0
    if adv_name == "silent":
        adv = A.SilentLeader(1.0)
    elif adv_name == "partial":
        adv = A.PartialSend(2)
    elif adv_name == "lienr":
        adv = A.LieNR()                        # framing: colluders claim NR=1 in honest leaders' views
    else:
        k = evade_k(base, byz, 2 / 3)          # evades AT at threshold 2/3
        adv = A.PartialSend(k, targeted=True)
    views = 3000
    cfg = RunConfig(n=N, views=views, seed=seed, protocol="P2", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    adversary=adv, vote_weights=vw, at_share=x if weighted else None)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps)), st, 1, views)
    acc = np.array([S.bad_fact(st, u, u + cfg.lag, "at") for u in range(1, views - 10)])
    lead = st.leaders[1:views - 10]
    bl, hl = st.byz[lead], st.honest[lead]
    excl_views = []
    seen = set()
    for ev, node, u in st.rule_log:
        if ev == "exclude" and st.byz[node] and node not in seen:
            seen.add(node)
            excl_views.append(sum(1 for y in range(1, u + 1) if st.leaders[y] == node))
    hon_conv = sum(1 for ev, node, u in st.rule_log if ev == "exclude" and st.honest[node])
    late = st.leaders[views // 2:views - 10]
    w_late = vw.table(st, (views - 11) // 100) if weighted else np.full(N, 1.0 / N)
    r_min = float(min(rr[byz].min() for rr in st.__dict__["_ttru_cache"][id(vw)]["rs"])) if weighted else 1.0
    return dict(weighted=weighted, adversary=adv_name, at_share=x, eps=eps, seed=seed, k=k,
                byz_base_share=float(base[byz].sum()),
                at_byz=float(acc[bl].mean()) if bl.any() else float("nan"), at_honest=float(acc[hl].mean()),
                convicted=len(seen), n_byz=int(byz.sum()), honest_convictions=hon_conv,
                views_to_conviction=float(np.mean(excl_views)) if excl_views else float("nan"),
                colluder_lead_late=float(np.mean(st.byz[late])), colluder_r_min=r_min,
                colluder_vote_share_end=float(w_late[st.byz].sum()) if weighted else float(st.byz.mean()),
                qc_rate=float(np.mean(st.qc_exists[100:views - 10])), commit=_perf(st, 100, views - 10)["commit"])


def budget_job(args):
    evidence, misbehave, b_rep, seed = args
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, 0.2)
    rule = S.CusumExclusion(evidence=evidence, rho_bar=0.01, D=500, cap=0.5, Wq=500, cap_weights=base)
    vw = ttru.TtruWeights(base, epoch=100, r_min=0.7, b_rep=b_rep, rule=rule)
    advs = [A.CollectorFraming()] + ([A.SilentLeader(0.3)] if misbehave else [])
    views = 4000
    cfg = RunConfig(n=N, views=views, seed=seed, protocol="P1", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    adversary=A.Compose(advs), vote_weights=vw)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0)), st, 1, views)
    cache = st.__dict__["_ttru_cache"][id(vw)]
    shares = np.array([t[byz].sum() for t in cache["tables"]])
    hon_removed = max(float(c[~byz].sum()) for c in cache["cuts"])
    byz_removed = max(float(c[byz].sum()) for c in cache["cuts"])
    excl_hon = 0.0
    excl = np.zeros(N, bool)
    for ev, node, u in st.rule_log:               # largest honest base weight excluded at once
        if ev == "exclude":
            excl[node] = True
        elif ev == "release":
            excl[node] = False
        excl_hon = max(excl_hon, float(base[excl & ~byz].sum()))
    b0 = float(base[byz].sum())
    return dict(evidence=evidence, misbehave=misbehave, b_rep=b_rep, seed=seed, base_share=b0,
                bound=b0 / (1 - b_rep), share_end=float(shares[-5:].mean()), share_max=float(shares.max()),
                honest_removed_max=hon_removed, colluder_removed_max=byz_removed, honest_excluded_max=excl_hon,
                qc_rate=float(np.mean(st.qc_exists[100:views - 10])), commit=_perf(st, 100, views - 10)["commit"])


def _perf(st, lo, hi):
    from sim2.experiments.ttru_perf import perf
    return perf(st, lo, hi)


def write(name, rows):
    with open(os.path.join(OUT, name), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    part = sys.argv[1] if len(sys.argv) > 1 else "at"
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    if part == "at":
        jobs = [(False, a, None, e, s) for a in ("silent", "partial") for e in (0.0, 0.05, 0.10) for s in range(SEEDS)]
        jobs += [(True, a, x, e, s) for a in ("silent", "partial", "targeted") for x in (2 / 3, 1 / 2)
                 for e in (0.0, 0.05, 0.10) for s in range(SEEDS)]
        jobs += [(wt, "lienr", x, e, s) for wt, x in ((False, None), (True, 2 / 3), (True, 1 / 2))
                 for e in (0.0, 0.05, 0.10, 0.20) for s in range(SEEDS)]
        with Pool(PROCS) as pool:
            rows = pool.map(at_job, jobs, chunksize=1)
        write("dirTtru_at.csv", rows)
        print("| 计票 | 对手 | AT 门槛 | ε | 接收者数 k | AT 指控：同伙 / 诚实领导视图 | 被定罪同伙 | 诚实被定罪次数 | 定罪前领导次数 | "
              "后半段同伙领导份额 | 同伙最低 r | 期末同伙投票份额 | 提交比例 |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for wt in (False, True):
            for a in ("silent", "partial", "targeted", "lienr"):
                for x in ((None,) if not wt else (2 / 3, 1 / 2)):
                    for e in (0.0, 0.05, 0.10, 0.20):
                        g = [r for r in rows if (r["weighted"], r["adversary"], r["at_share"], r["eps"]) == (wt, a, x, e)]
                        if not g:
                            continue
                        m = lambda c: float(np.nanmean([r[c] for r in g]))
                        print(f"| {'T_tru 加权' if wt else '按个数'} | {a} | {'q' if x is None else f'{x:.3f}'} | {e} | "
                              f"{m('k'):.1f} | {m('at_byz'):.3f} / {m('at_honest'):.4f} | {m('convicted'):.1f}/{m('n_byz'):.1f} | "
                              f"{m('honest_convictions'):.1f} | "
                              f"{m('views_to_conviction'):.1f} | {m('colluder_lead_late'):.3f} | {m('colluder_r_min'):.2f} | "
                              f"{m('colluder_vote_share_end'):.3f} | {m('commit'):.3f} |")
    else:
        jobs = [(ev, mb, b, s) for ev in ("failed", "at") for mb in (False, True) for b in (0.05, 0.10, 0.20)
                for s in range(SEEDS)]
        with Pool(PROCS) as pool:
            rows = pool.map(budget_job, jobs, chunksize=1)
        write("dirTtru_budget.csv", rows)
        print("| 证据 | 同伙另外作恶 | B_rep | 同伙基础份额 | 单表界 β0/(1−B_rep) | 期末投票份额 | 最高投票份额 | "
              "诚实被降权重（最大） | 同伙被降权重（最大） | 诚实被排除权重（最大） | QC 率 |")
        print("|---|---|---|---|---|---|---|---|---|---|---|")
        for ev in ("failed", "at"):
            for mb in (False, True):
                for b in (0.05, 0.10, 0.20):
                    g = [r for r in rows if (r["evidence"], r["misbehave"], r["b_rep"]) == (ev, mb, b)]
                    m = lambda c: float(np.mean([r[c] for r in g]))
                    mx = lambda c: float(np.max([r[c] for r in g]))
                    print(f"| {'可被陷害（失败提议者）' if ev == 'failed' else '抗陷害（AT）'} | {'是' if mb else '否'} | {b} | "
                          f"{m('base_share'):.3f} | {m('bound'):.3f} | {m('share_end'):.3f} | {m('share_max'):.3f} "
                          f"(最大超界 {max(r['share_max'] - r['bound'] for r in g):+.4f}) | "
                          f"{m('honest_removed_max'):.3f} | {m('colluder_removed_max'):.3f} | {mx('honest_excluded_max'):.3f} | "
                          f"{m('qc_rate'):.3f} |")
    print(f"wall {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

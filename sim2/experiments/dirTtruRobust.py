"""Robustness of the T_tru leader rule (信任2.0_协议级验证 §3.3-§3.4). Abstract only.

Same population, colluders and weights as dirTtru (n = 31, colluders = the cheapest ~0.24 of base weight);
P2; leader rule = CUSUM over AT (x = 2/3, rho_bar = 0.03) plus optionally the soft "noqc" CUSUM
(soft_q = 0.9); T_tru reputation (b_rep 0.10, r_min 0.7) moves on AT convictions only.

Part "async" (before GST): the first A views are asynchronous (every message gets an extra delay uniform
in [0, 3 s] with probability async_p). Colluders either follow the protocol or frame (withhold their
votes in honest leaders' views and claim NR=1). We count honest convictions before / after GST (hard =
AT, soft = noqc), the honest weight removed from VOTING by reputation (bounded by b_rep), the honest
weight excluded from LEADING, the colluder voting share against the single-table bound, and when the
exclusions of honest replicas end after GST (expiry D = 500).
Part "adaptive": a rule-aware colluding leader (adversary.AdaptivePartialSend) keeps its own copy of
the soft CUSUM and attacks only while one more failure keeps it below (1 - margin) h; optionally the
colluders also frame honest leaders (withhold + NR=1). We measure the attack rate it sustains, whether it
is ever excluded, and the throughput, against the analytic p*(rho_s).

Environment: SIM_PROCS (default 8), SIM_SEEDS (default 8).
Run from the repository root:  python -m sim2.experiments.dirTtruRobust [async|adaptive]
Out: results/dirTtru_async.{csv,md}, results/dirTtru_adaptive.{csv,md}
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
from sim2.experiments.dirTtru import N, OUT, cheapest_set, evade_k, setup
from sim2.experiments.ttru_perf import PreGSTNet, adv_targets, perf
from sim2.net import NetConfig, Network

PROCS = int(os.environ.get("SIM_PROCS", "8"))
SEEDS = int(os.environ.get("SIM_SEEDS", "8"))
SOFT_Q, B_REP, D = 0.9, 0.10, 500
VIEWS = 3000
GST = 1000
NETS = ("iid", "outage", "adv")
H = float(np.log(1e4))


def p_star(rho, q=SOFT_Q):
    a, b = np.log(q / rho), np.log((1 - rho) / (1 - q))
    return float(b / (a + b))


def make_rule(base, soft_rho):
    kw = {} if soft_rho is None else dict(soft_evidence="noqc", soft_rho=soft_rho, soft_q=SOFT_Q)
    return S.CusumExclusion(q=0.5, evidence="at", rho_bar=0.03, D=D, cap=0.5, Wq=500, cap_weights=base, **kw)


def framing():
    return A.Compose([A.LieNR(), A.WithholdVotesOnHonest()])


def exclusions(st, base, end):
    """Per view: honest base weight excluded from leading; honest conviction views (hard / soft)."""
    excl = np.zeros(N, bool)
    w = np.zeros(end + 1)
    last, cur = 1, 0.0
    hard, soft = [], []
    for ev, node, u in st.rule_log:
        if ev not in ("exclude", "exclude_soft", "release"):
            continue
        u = min(max(u, 1), end)
        w[last:u] = cur
        last = u
        if ev == "release":
            excl[node] = False
        else:
            excl[node] = True
            if st.honest[node]:
                (hard if ev == "exclude" else soft).append(u)
        cur = float(base[excl & st.honest].sum())
    w[last:] = cur
    return w, hard, soft


def async_job(args):
    frame, netmode, soft_rho, seed = args
    gst = GST
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, 0.2)
    rule = make_rule(base, soft_rho)
    vw = ttru.TtruWeights(base, epoch=100, r_min=0.7, b_rep=B_REP, rule=rule)
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol="P2", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    adversary=framing() if frame else None, vote_weights=vw, at_share=2 / 3)
    st = State(cfg)
    if netmode == "iid":
        net = Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, async_views=gst, async_p=0.5,
                                async_extra_ms=3000.0))
    else:
        ncfg = NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, outage_p=0.02 if netmode == "outage" else 0.0)
        net = PreGSTNet(ncfg, netmode, gst, st, adv_targets(base, byz))
    engine_event.simulate(cfg, net, st, 1, VIEWS)
    end = VIEWS - 10
    w, hard, soft = exclusions(st, base, end)
    cache = st.__dict__["_ttru_cache"][id(vw)]
    cuts = cache["cuts"]
    shares = np.array([t[byz].sum() for t in cache["tables"]])
    hon_vote_cut = max(float(c[~byz].sum()) for c in cuts)
    excl_after = np.flatnonzero(w[gst:] > 1e-12)
    return dict(frame=frame, net=netmode, gst=gst, soft=-1.0 if soft_rho is None else soft_rho, seed=seed,
                beta=float(base[byz].sum()), bound=float(base[byz].sum() / (1 - B_REP)),
                hard_pre=sum(u < gst for u in hard), hard_post=sum(u >= gst for u in hard),
                soft_pre=sum(u < gst for u in soft), soft_post=sum(u >= gst for u in soft),
                honest_vote_cut_max=hon_vote_cut, colluder_share_max=float(shares.max()),
                honest_lead_excl_max=float(w[1:end].max()),
                excl_until=int(gst + excl_after[-1] + 1) if excl_after.size else gst,
                qc_pre=float(np.mean(st.qc_exists[1:gst])), qc_post=float(np.mean(st.qc_exists[gst + D + 20:end])))


def adaptive_job(args):
    soft_rho, margin, frame, eps, seed = args
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, 0.2)
    rule = make_rule(base, soft_rho)
    vw = ttru.TtruWeights(base, epoch=100, rule=rule)
    att = A.AdaptivePartialSend(evade_k(base, byz, 2 / 3), float(np.log(SOFT_Q / soft_rho)),
                                float(np.log((1 - SOFT_Q) / (1 - soft_rho))), H, margin)
    adv = A.Compose([att, framing()]) if frame else att
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol="P2", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    adversary=adv, vote_weights=vw, at_share=2 / 3)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps)), st, 1,
                          VIEWS)
    end = VIEWS - 10
    lead = st.leaders[1:end]
    bl, hl = st.byz[lead], st.honest[lead]
    noqc = ~st.qc_exists[1:end]
    byz_conv = len({node for ev, node, u in st.rule_log if ev in ("exclude", "exclude_soft") and st.byz[node]})
    w, hard, soft = exclusions(st, base, end)
    s_up, s_dn = float(np.log(SOFT_Q / soft_rho)), float(np.log((1 - SOFT_Q) / (1 - soft_rho)))
    n_led = int(bl.sum())
    bound = p_star(soft_rho) * n_led + int(byz.sum()) * H / (s_up - s_dn)   # lemma: failures of an unexcluded colluder set
    pf = perf(st, VIEWS // 2, end)
    return dict(soft=soft_rho, margin=margin, frame=frame, eps=eps, seed=seed, p_star=p_star(soft_rho),
                n_byz=int(byz.sum()), fail_count=int(noqc[bl].sum()), fail_bound=bound,
                commit_late=pf["commit"], bps_late=pf["bps"],
                fail_byz=float(noqc[bl].mean()), fail_honest=float(noqc[hl].mean()),
                byz_excluded=byz_conv / int(byz.sum()), honest_soft=len(soft), honest_hard=len(hard),
                colluder_lead=float(np.mean(st.byz[st.leaders[VIEWS // 2:end]])),
                qc_late=float(np.mean(st.qc_exists[VIEWS // 2:end])))


def write(name, rows):
    with open(os.path.join(OUT, name), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def run_async():
    t0 = time.time()
    seeds = 2 * SEEDS
    jobs = [(fr, nm, sr, s) for fr in (False, True) for nm in NETS for sr in (None, 0.5) for s in range(seeds)]
    with Pool(PROCS) as pool:
        rows = pool.map(async_job, jobs, chunksize=1)
    write("dirTtru_async.csv", rows)
    L = [f"# GST 之前的混乱期（P2；每格 {seeds} 个人群，{VIEWS} 视图，GST = 视图 {GST}）\n",
         "混乱期网络：iid = 每条消息以概率 0.5 额外延迟 0–3 s；outage = 区域故障（每视图以 0.02 的概率开始，"
         "该区域消息 +5 s）；adv = 对抗调度（诚实领导者的提案对刚超过 2/3−β 份额的最重诚实节点延迟 6 s）。\n",
         "| 同伙 | 混乱期网络 | 软证据 | 诚实被 AT 定罪：GST 前 / 后（总数） | 出现硬定罪的人群 | 诚实被软定罪：GST 前 / 后 | "
         "诚实被降投票权重（最大；预算 0.10） | 同伙投票份额最大 / 单表界 | 诚实被排除领导权重（最大） | 诚实排除结束于视图 | "
         "QC 率：GST 前 / GST+D 之后 |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for fr in (False, True):
        for nm in NETS:
            for sr in (-1.0, 0.5):
                G = [o for o in rows if (o["frame"], o["net"], o["soft"]) == (fr, nm, sr)]
                m = lambda c: float(np.mean([o[c] for o in G]))  # noqa: E731
                if True:
                    L.append(f"| {'扣票+谎报' if fr else '守规矩'} | {nm} | {'关闭' if sr < 0 else sr} | "
                             f"{sum(o['hard_pre'] for o in G)} / {sum(o['hard_post'] for o in G)} | "
                             f"{sum(o['hard_pre'] + o['hard_post'] > 0 for o in G)}/{len(G)} | "
                             f"{m('soft_pre'):.1f} / {m('soft_post'):.1f} | "
                             f"{m('honest_vote_cut_max'):.3f} | {m('colluder_share_max'):.3f} / {m('bound'):.3f}"
                             f"（超界 {max(o['colluder_share_max'] - o['bound'] for o in G):+.4f}） | "
                             f"{m('honest_lead_excl_max'):.3f} | {max(o['excl_until'] for o in G)} | "
                             f"{m('qc_pre'):.3f} / {m('qc_post'):.3f} |")
    L.append(f"\nwall {time.time() - t0:.0f}s")
    with open(os.path.join(OUT, "dirTtru_async.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


def run_adaptive():
    t0 = time.time()
    jobs = [(sr, mg, fr, e, s) for sr in (0.3, 0.5, 0.7) for mg in (0.0, 0.2) for fr in (False, True) for e in (0.0, 0.05)
            for s in range(SEEDS)]
    with Pool(PROCS) as pool:
        rows = pool.map(adaptive_job, jobs, chunksize=1)
    write("dirTtru_adaptive.csv", rows)
    L = [f"# 了解规则的自适应部分发送者（P2；每格 {SEEDS} 个人群，{VIEWS} 视图；软 CUSUM q={SOFT_Q}）\n",
         "| ρ̄_s | p*(ρ̄_s) | 安全余量 | 同伙另外陷害 | ε | 同伙领导视图失败率 | 失败数 / 引理上界（未被排除的运行） | 同伙被排除比例 | "
         "诚实领导视图失败率 | 诚实软 / 硬定罪 | 后半段同伙领导份额 | 后半段提交比例 | 后半段每秒提交块数 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for sr in (0.3, 0.5, 0.7):
        for mg in (0.0, 0.2):
            for fr in (False, True):
                for e in (0.0, 0.05):
                    G = [o for o in rows if (o["soft"], o["margin"], o["frame"], o["eps"]) == (sr, mg, fr, e)]
                    m = lambda c: float(np.mean([o[c] for o in G]))  # noqa: E731
                    U = [o for o in G if o["byz_excluded"] == 0]
                    fb = (f"{np.mean([o['fail_count'] for o in U]):.0f} / {np.mean([o['fail_bound'] for o in U]):.0f}"
                          f"（{sum(o['fail_count'] <= o['fail_bound'] for o in U)}/{len(U)} 满足）") if U else "—"
                    L.append(f"| {sr} | {p_star(sr):.2f} | {mg} | {'是' if fr else '否'} | {e} | {m('fail_byz'):.3f} | {fb} | "
                             f"{m('byz_excluded'):.2f} | {m('fail_honest'):.3f} | {m('honest_soft'):.1f} / {m('honest_hard'):.1f} | "
                             f"{m('colluder_lead'):.3f} | {m('commit_late'):.3f} | {m('bps_late'):.2f} |")
    L.append(f"\nwall {time.time() - t0:.0f}s")
    with open(os.path.join(OUT, "dirTtru_adaptive.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    {"async": run_async, "adaptive": run_adaptive}[sys.argv[1] if len(sys.argv) > 1 else "async"]()

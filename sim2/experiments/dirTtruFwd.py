"""Proposal forwarding and the slot-duration evidence under stronger leader attacks (信任2.0_协议级验证 §3.8),
v2 after review 信任2.0_v08_审查_代码与实验 (C1-C5, S1-S4, E1). Abstract only.

Same population, colluders and weights as dirTtru (n = 31; colluders = cheapest set with base share target
0.2 -> ~0.24 or 0.27 -> ~0.28, capped at 0.30). P2. Leader rule: CUSUM over AT (x = 2/3, rho_bar = 0.1)
with or without the soft slot-duration evidence (relative threshold: 3 x the median score of the last 200
views, rho_s = 0.7). Uplink serialization is on (RunConfig.uplink_serial): a sender's copies of a proposal
leave one after another and a holder serves block requests one at a time (bandwidth 1 Gbps; part "net" also
100 Mbps), so the extra bytes of forwarding cost time.
Proposal forwarding (RunConfig.prop_forward): off; "hdr" (honest replicas forward the signed header, replicas
without the block fetch it from honest holders, cascading); "full" (honest replicas forward the whole proposal).
NR bit (RunConfig.nr_requires_data): "header" (NR = no signed header by the timeout) or "header+block"
(NR = no usable proposal, i.e. header and block, by the timeout; the recommended rule).

Modes (colluding leaders):
  none            no adversary
  silent          send nothing
  targeted        send only to the k heaviest honest replicas (evades AT at 2/3); colluders do not vote
  late_partial    the same, and those copies arrive 1.8 s late (just before the 2 s timeout)
  adaptive        rule-aware partial send (keeps its copy of the soft CUSUM below h)
  withhold        header to everybody, block only to colluders (data withholding); colluders do not vote
  timed           timed release: partial send to the k heaviest honest replicas, reaching them ~80 ms before
                  their timeout (part "timed")
  atimed          rule-aware timed release (copy of the soft CUSUM over failures) (part "timed")
  slow            delay the proposal by 1.8 s in every view
  slow_p75        the same in 75% of their views (stays under the soft CUSUM tolerance)
  frame_withhold  colluders withhold votes in honest leaders' views and claim NR=1, on top of late messages
Throughput: committed blocks per second in the second half, relative to (a) no adversary and no forwarding,
and (b) no adversary with the same forwarding, both at the same eps, target, soft and NR settings.
Part "net": honest-led views flagged by the absolute 200 ms threshold vs the relative threshold on wider
networks, and the forwarding cost at 100 Mbps.
Environment: SIM_PROCS (default 8), SIM_SEEDS (default 8).
Run from the repository root:  python -m sim2.experiments.dirTtruFwd [run|net|plot]
Out: results/dirTtru_fwd.{csv,md}, results/dirTtru_fwd_net.{csv,md}, results/fig_fwd.png.
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
from sim2.experiments.ttru_perf import perf
from sim2.net import NetConfig, Network

PROCS = int(os.environ.get("SIM_PROCS", "8"))
SEEDS = int(os.environ.get("SIM_SEEDS", "8"))
SOFT_Q, SLOT_RHO, SLOT_REL = 0.9, 0.7, 3.0
H = float(np.log(1e4))
VIEWS = 2000
FWDS = ("off", "hdr", "full")
MODES = ("none", "silent", "targeted", "late_partial", "adaptive", "withhold", "slow", "slow_p75", "frame_withhold")
EPS = (0.0, 0.05, 0.1)
SOFTS = ("off", "slot")
NETS = {"base": dict(regions=3), "wide": dict(regions=8, region_c1_ms=120.0),
        "wide_jit": dict(regions=8, region_c1_ms=120.0, jitter_max_ms=20.0)}


def build(mode, base, byz, net=None, tau=2000.0):
    k = evade_k(base, byz, 2 / 3)
    if mode in ("timed", "atimed"):
        if mode == "timed":
            return A.TimedRelease(k, 80.0, net.base, tau)
        return A.AdaptiveTimedRelease(k, float(np.log(SOFT_Q / SLOT_RHO)), float(np.log((1 - SOFT_Q) / (1 - SLOT_RHO))),
                                      H, 80.0, net.base, tau)
    adaptive = A.AdaptivePartialSend(k, float(np.log(SOFT_Q / SLOT_RHO)), float(np.log((1 - SOFT_Q) / (1 - SLOT_RHO))), H)
    return {"none": None, "silent": A.SilentLeader(1.0), "targeted": A.PartialSend(k, targeted=True),
            "late_partial": A.Compose([A.PartialSend(k, targeted=True), A.SlowLeader(1800.0)]),
            "adaptive": adaptive, "withhold": A.DataWithhold(k=0), "slow": A.SlowLeader(1800.0),
            "slow_p75": A.SlowLeader(1800.0, p=0.75),
            "frame_withhold": A.Compose([A.LieNR(), A.WithholdVotesOnHonest()])}[mode]


def job(args):
    mode, fwd, soft, nrd, eps, target, seed, net, theta, bw = args
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, target, max_share=0.30)
    kw = {} if soft == "off" else dict(soft_evidence="slot", soft_rho=SLOT_RHO, soft_q=SOFT_Q)
    rule = S.CusumExclusion(q=0.5, evidence="at", rho_bar=0.1, D=500, cap=0.5, Wq=500, cap_weights=base, **kw)
    vw = ttru.TtruWeights(base, epoch=100, rule=rule)
    slot_kw = {} if soft == "off" else (dict(slot_theta_rel=SLOT_REL) if theta == "rel" else dict(slot_theta_ms=float(theta)))
    ncfg = dict(n=N, seed=seed, jitter_max_ms=2.0, eps_late=eps, bw_mbps=bw)
    ncfg.update(NETS[net])
    network = Network(NetConfig(**ncfg))
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol="P2", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    adversary=None, vote_weights=vw, at_share=2 / 3,
                    prop_forward=None if fwd == "off" else fwd, uplink_serial=True, nr_requires_data=nrd, **slot_kw)
    cfg.adversary = build(mode, base, byz, network, cfg.tau_ms)
    st = State(cfg)
    engine_event.simulate(cfg, network, st, 1, VIEWS)
    end = VIEWS - 10
    lead = st.leaders[1:end]
    hl, bl = st.honest[lead], st.byz[lead]
    noqc = ~st.qc_exists[1:end]
    hon_soft = sum(1 for e_, node, u in st.rule_log if e_ == "exclude_soft" and st.honest[node])
    hon_hard = sum(1 for e_, node, u in st.rule_log if e_ == "exclude" and st.honest[node])
    byz_conv = len({node for e_, node, u in st.rule_log if e_ in ("exclude", "exclude_soft") and st.byz[node]})
    slot_flag = float("nan")
    if soft == "slot":
        hv = [u for u in range(VIEWS // 2, end) if st.honest[st.leaders[u]]]
        slot_flag = float(np.mean([S.bad_fact(st, u, u + cfg.lag, "slot") for u in hv]))
    pf = perf(st, VIEWS // 2, end)
    pb = st.__dict__.get("prop_bytes", {})
    mb = float(np.mean([pb[w] for w in range(VIEWS // 2, end) if w in pb])) / 1e6 if pb else float("nan")
    return dict(mode=mode, fwd=fwd, soft=soft, nrd=nrd, eps=eps, target=target, seed=seed, net=net, theta=str(theta), bw=bw,
                beta=float(base[byz].sum()), fail_byz=float(noqc[bl].mean()) if bl.any() else float("nan"),
                honest_soft_per_1000=1000.0 * hon_soft / max(1, int(hl.sum())), honest_hard=hon_hard,
                honest_slot_flag=slot_flag, byz_excluded=byz_conv / int(byz.sum()),
                colluder_lead_late=float(np.mean(st.byz[st.leaders[VIEWS // 2:end]])),
                commit_late=pf["commit"], bps_late=pf["bps"], view_ms_late=pf["view_ms"], mb_per_view=mb)


def relative(rows, keys):
    ref0 = {tuple(o[k] for k in keys): o for o in rows if o["mode"] == "none" and o["fwd"] == "off"}
    ref1 = {tuple(o[k] for k in keys) + (o["fwd"],): o for o in rows if o["mode"] == "none"}
    for o in rows:
        r0, r1 = ref0.get(tuple(o[k] for k in keys)), ref1.get(tuple(o[k] for k in keys) + (o["fwd"],))
        o["bps_rel"] = o["bps_late"] / r0["bps_late"] if r0 else float("nan")
        o["bps_rel_same"] = o["bps_late"] / r1["bps_late"] if r1 else float("nan")
        o["bytes_rel"] = o["mb_per_view"] / r0["mb_per_view"] if r0 else float("nan")


def write(name, rows):
    with open(os.path.join(OUT, name), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def run():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    J = lambda m, f, so, nrd, e, tg, s: (m, f, so, nrd, e, tg, s, "base", "rel", 1000.0)  # noqa: E731
    jobs = [J(m, f, so, True, e, 0.2, s) for m in MODES for f in FWDS for so in SOFTS for e in EPS for s in range(SEEDS)]
    jobs += [J(m, f, so, False, e, 0.2, s) for m in ("none", "withhold", "frame_withhold") for f in FWDS for so in SOFTS
             for e in EPS for s in range(SEEDS)]
    jobs += [J(m, f, so, True, e, 0.27, s) for m in ("none", "targeted", "withhold", "frame_withhold") for f in FWDS
             for so in SOFTS for e in EPS for s in range(SEEDS)]
    with Pool(PROCS) as pool:
        rows = pool.map(job, jobs, chunksize=1)
    relative(rows, ("soft", "nrd", "eps", "target", "seed"))
    write("dirTtru_fwd.csv", rows)
    L = [f"# 提案转发与出块时长分数：更强的领导者攻击（每格 {SEEDS} 个人群，{VIEWS} 视图；P2；AT x=2/3、ρ̄=0.1；"
         f"软证据为出块时长分数（相对门限 {SLOT_REL}× 近 200 视图中位数，ρ̄_s={SLOT_RHO}）或关闭；上行串行发送，1 Gbps）\n",
         "每格：吞吐（相对无对手、不转发） / 吞吐（相对无对手、同一转发） / 字节数（相对无对手、不转发） / 同伙视图失败率 / "
         "同伙被排除比例 / 诚实软、硬误定罪（每千个诚实领导视图、总次数）\n"]
    P = L.append
    for tg, nrd, modes in ((0.2, True, MODES), (0.2, False, ("none", "withhold", "frame_withhold")),
                           (0.27, True, ("none", "targeted", "withhold", "frame_withhold"))):
        beta = np.mean([o["beta"] for o in rows if o["target"] == tg])
        for so in SOFTS:
            P(f"\n## 同伙份额约 {beta:.2f}，NR 位 = {'无可用提案（头 + 块）' if nrd else '无提案头'}，软证据{'关闭' if so == 'off' else '开启'}\n")
            P("| 对手 | 转发 | " + " | ".join(f"ε={e}" for e in EPS) + " |")
            P("|---|---|" + "---|" * len(EPS))
            for m in modes:
                for f in FWDS:
                    cells = []
                    for e in EPS:
                        g = [o for o in rows if (o["mode"], o["fwd"], o["soft"], o["nrd"], o["eps"], o["target"]) ==
                             (m, f, so, nrd, e, tg)]
                        mm = lambda c: float(np.nanmean([o[c] for o in g]))  # noqa: E731
                        cells.append(f"{mm('bps_rel'):.2f} / {mm('bps_rel_same'):.2f} / {mm('bytes_rel'):.1f}× / "
                                     f"{mm('fail_byz'):.2f} / {mm('byz_excluded'):.2f} / "
                                     f"{mm('honest_soft_per_1000'):.2f}、{sum(o['honest_hard'] for o in g)}")
                    P(f"| {m} | {f} | " + " | ".join(cells) + " |")
    P(f"\nwall {time.time() - t0:.0f}s")
    with open(os.path.join(OUT, "dirTtru_fwd.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


def run_net():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    jobs = [(m, "hdr", "slot", True, e, 0.2, s, net, th, 1000.0) for m in ("none", "frame_withhold", "slow")
            for net in NETS for th in ("200", "rel") for e in (0.0, 0.1) for s in range(SEEDS)]
    jobs += [(m, f, "slot", True, 0.0, 0.2, s, "base", "rel", 100.0) for m in ("none", "targeted", "withhold")
             for f in FWDS for s in range(SEEDS)]
    with Pool(PROCS) as pool:
        rows = pool.map(job, jobs, chunksize=1)
    relative(rows, ("soft", "nrd", "eps", "target", "seed", "net", "theta", "bw"))
    write("dirTtru_fwd_net.csv", rows)
    L = [f"# 出块时长门限在不同网络下的误判，以及 100 Mbps 下的转发代价（每格 {SEEDS} 个人群；转发提案头；NR = 头 + 块）\n",
         "网络：base = 3 区域；wide = 8 区域、每单位距离 120 ms；wide_jit = 再加 20 ms 抖动。\n",
         "## 诚实领导视图被记坏事实的比例 / 每千个诚实领导视图的软误定罪 / 同伙被排除比例\n",
         "| 对手 | 网络 | 门限 | ε=0 | ε=0.1 |", "|---|---|---|---|---|"]
    for m in ("none", "frame_withhold", "slow"):
        for net in NETS:
            for th in ("200", "rel"):
                cells = []
                for e in (0.0, 0.1):
                    g = [o for o in rows if (o["mode"], o["net"], o["theta"], o["eps"], o["bw"]) == (m, net, th, e, 1000.0)]
                    mm = lambda c: float(np.nanmean([o[c] for o in g]))  # noqa: E731
                    cells.append(f"{mm('honest_slot_flag'):.3f} / {mm('honest_soft_per_1000'):.2f} / {mm('byz_excluded'):.2f}")
                L.append(f"| {m} | {net} | {'200 ms' if th == '200' else f'{SLOT_REL}× 中位数'} | " + " | ".join(cells) + " |")
    L += ["\n## 100 Mbps 下的吞吐（相对无对手、不转发）与字节数\n", "| 对手 | 不转发 | 转发提案头 | 转发整个提案 |", "|---|---|---|---|"]
    for m in ("none", "targeted", "withhold"):
        cells = []
        for f in FWDS:
            g = [o for o in rows if (o["mode"], o["fwd"], o["bw"]) == (m, f, 100.0)]
            cells.append(f"{np.mean([o['bps_rel'] for o in g]):.2f}（{np.mean([o['bytes_rel'] for o in g]):.1f}×）")
        L.append(f"| {m} | " + " | ".join(cells) + " |")
    L.append(f"\nwall {time.time() - t0:.0f}s")
    with open(os.path.join(OUT, "dirTtru_fwd_net.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


def run_timed():
    """Timed release (plain and rule-aware) vs forwarding, NR definition and soft evidence."""
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    jobs = [(m, f, so, nrd, e, 0.2, s, "base", "rel", 1000.0) for m in ("none", "timed", "atimed") for f in FWDS
            for so in SOFTS for nrd in (False, True) for e in (0.0, 0.05) for s in range(SEEDS)]
    with Pool(PROCS) as pool:
        rows = pool.map(job, jobs, chunksize=1)
    relative(rows, ("soft", "nrd", "eps", "target", "seed"))
    write("dirTtru_fwd_timed.csv", rows)
    L = [f"# 定时释放（提案只发给最重的少数诚实节点，在它们超时前约 80 ms 送达）对提案转发的影响（每格 {SEEDS} 个人群）\n",
         "每格：吞吐（相对无对手、不转发） / 同伙视图失败率 / 同伙被排除比例 / 诚实软、硬误定罪\n",
         "| 对手 | 转发 | 软证据 | NR 位 | ε=0 | ε=0.05 |", "|---|---|---|---|---|---|"]
    for m in ("timed", "atimed"):
        for f in FWDS:
            for so in SOFTS:
                for nrd in (False, True):
                    cells = []
                    for e in (0.0, 0.05):
                        g = [o for o in rows if (o["mode"], o["fwd"], o["soft"], o["nrd"], o["eps"]) == (m, f, so, nrd, e)]
                        mm = lambda c: float(np.nanmean([o[c] for o in g]))  # noqa: E731
                        cells.append(f"{mm('bps_rel'):.2f} / {mm('fail_byz'):.2f} / {mm('byz_excluded'):.2f} / "
                                     f"{mm('honest_soft_per_1000'):.2f}、{sum(o['honest_hard'] for o in g)}")
                    L.append(f"| {m} | {f} | {'开' if so == 'slot' else '关'} | {'头 + 块' if nrd else '头'} | " + " | ".join(cells) + " |")
    L.append(f"\nwall {time.time() - t0:.0f}s")
    with open(os.path.join(OUT, "dirTtru_fwd_timed.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    f = "/System/Library/Fonts/STHeiti Medium.ttc"
    if os.path.exists(f):
        font_manager.fontManager.addfont(f)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    rows = list(csv.DictReader(open(os.path.join(OUT, "dirTtru_fwd.csv"))))
    tpath = os.path.join(OUT, "dirTtru_fwd_timed.csv")
    if os.path.exists(tpath):
        rows += [o for o in csv.DictReader(open(tpath)) if o["mode"] != "none"]
    for o in rows:
        for k_ in ("eps", "target", "bps_rel", "bps_rel_same"):
            o[k_] = float(o[k_])
        o["nrd"] = o["nrd"] == "True"

    def mean(key_, **cond):
        g = [o[key_] for o in rows if all(o[k] == v for k, v in cond.items())]
        return float(np.nanmean(g)) if g else float("nan")

    col = {"off": "#555555", "hdr": "#2a78d6", "full": "#eb6834"}
    lab = {"off": "不转发", "hdr": "转发提案头 + 取块", "full": "转发整个提案"}
    modes = ("targeted", "adaptive", "late_partial", "timed", "atimed", "withhold", "slow", "slow_p75", "frame_withhold")
    names = ("定向部分\n发送", "了解软 CUSUM\n的部分发送\n（不知道转发）", "迟到的\n部分发送", "定时释放", "了解规则的\n定时释放",
             "数据扣留", "慢领导者", "概率性\n慢领导者", "扣票 +\n迟到")
    fig, ax = plt.subplots(1, 1, figsize=(13, 4.6))
    xs = np.arange(len(modes))
    for i, f in enumerate(FWDS):
        cond = [dict(mode=m, fwd=f, soft="slot", nrd=True, eps=0.05 if m == "frame_withhold" else 0.0, target=0.2)
                for m in modes]
        x = xs + (i - 1) * 0.27
        ax.bar(x, [mean("bps_rel", **c) for c in cond], 0.25, color=col[f], label=lab[f])
        if f != "off":      # same-forwarding baseline (review v0.8 code E1)
            ax.scatter(x, [mean("bps_rel_same", **c) for c in cond], marker="_", s=120, color="black", zorder=3,
                       label="相对无对手、同一转发" if f == "hdr" else None)
    ax.set_xticks(xs, names, fontsize=8)
    ax.set_ylim(0, 1.25)
    ax.axhline(1, color="#999", lw=0.8)
    ax.set_ylabel("吞吐（柱：相对无对手、不转发）")
    ax.set_title("领导者攻击下的吞吐（同伙份额约 0.24；软证据开启，NR = 无可用提案；扣票 + 迟到取 ε=0.05，其余 ε=0；"
                 "上行串行发送 1 Gbps）", fontsize=9)
    ax.legend(fontsize=8, frameon=False, loc="upper center", ncol=4)
    ax.grid(alpha=0.25, lw=0.5, axis="y")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_fwd.png"), dpi=160, bbox_inches="tight")


if __name__ == "__main__":
    {"plot": plot, "net": run_net, "timed": run_timed}.get(sys.argv[1] if len(sys.argv) > 1 else "run", run)()

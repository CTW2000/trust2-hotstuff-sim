"""Proposal forwarding against partial send (信任2.0_协议级验证 §3.8). Abstract only.

Same population, colluders and weights as dirTtru (n = 31; colluders = cheapest set with base share target
0.2 -> ~0.24 or 0.27 -> ~0.28, capped at 0.30). P2. Leader rule: CUSUM over AT (x = 2/3, rho_bar = 0.1)
with or without the recommended soft evidence (weighted slot-duration score, theta = 200 ms, rho_s = 0.7).
Proposal forwarding (RunConfig.prop_forward, common.proposal_timing):
  None  off (as before)
  hdr   honest replicas forward the signed header on first receipt; replicas without the block fetch it
        from any honest holder, and replicas that fetched it serve it too (cascade)
  full  honest replicas forward the whole proposal on first receipt
Byzantine replicas never forward. Bandwidth: proposal bytes per view (leader sends, forwards, fetches;
block 250 kB, header 4 kB) from st.prop_bytes. The network model has no uplink contention, so the extra
bytes are counted but do not slow messages down.

Modes:
  none            no adversary
  silent          colluding leaders send nothing (AT must still catch them)
  targeted        partial send to the k heaviest honest replicas (evades AT at 2/3); colluders do not vote
  targeted1       partial send to the single heaviest honest replica
  adaptive        rule-aware partial send (keeps its copy of the soft CUSUM below h)
  slow1800        colluding leaders delay their proposal by 1800 ms (forwarding cannot help)
  frame_withhold  colluders withhold votes in honest views and claim NR=1, on top of late messages
Throughput: committed blocks per second in the second half, relative to the run with no adversary and no
forwarding at the same eps, target and soft setting. Bytes relative to that run as well.
Environment: SIM_PROCS (default 8), SIM_SEEDS (default 8).
Run from the repository root:  python -m sim2.experiments.dirTtruFwd [run|plot]
Out: results/dirTtru_fwd.csv, dirTtru_fwd.md; results/fig_fwd.png (plot, needs matplotlib).
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
SOFT_Q, SLOT_THETA, SLOT_RHO = 0.9, 200.0, 0.7
H = float(np.log(1e4))
VIEWS = 2000
FWDS = (None, "hdr", "full")
MODES = ("none", "silent", "targeted", "targeted1", "adaptive", "slow1800", "frame_withhold")
EPS = (0.0, 0.05, 0.1)
SOFTS = ("off", "slot")


def job(args):
    mode, fwd, soft, eps, target, seed = args
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, target, max_share=0.30)
    kw = {} if soft == "off" else dict(soft_evidence="slot", soft_rho=SLOT_RHO, soft_q=SOFT_Q)
    rule = S.CusumExclusion(q=0.5, evidence="at", rho_bar=0.1, D=500, cap=0.5, Wq=500, cap_weights=base, **kw)
    vw = ttru.TtruWeights(base, epoch=100, rule=rule)
    k = evade_k(base, byz, 2 / 3)
    adaptive = A.AdaptivePartialSend(k, float(np.log(SOFT_Q / SLOT_RHO)), float(np.log((1 - SOFT_Q) / (1 - SLOT_RHO))), H)
    adv = {"none": None, "silent": A.SilentLeader(1.0), "targeted": A.PartialSend(k, targeted=True),
           "targeted1": A.PartialSend(1, targeted=True), "adaptive": adaptive, "slow1800": A.SlowLeader(1800.0),
           "frame_withhold": A.Compose([A.LieNR(), A.WithholdVotesOnHonest()])}[mode]
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol="P2", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    adversary=adv, vote_weights=vw, at_share=2 / 3, prop_forward=fwd,
                    slot_theta_ms=SLOT_THETA if soft == "slot" else None)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps)), st, 1,
                          VIEWS)
    end = VIEWS - 10
    lead = st.leaders[1:end]
    hl, bl = st.honest[lead], st.byz[lead]
    noqc = ~st.qc_exists[1:end]
    hon_soft = sum(1 for e_, node, u in st.rule_log if e_ == "exclude_soft" and st.honest[node])
    hon_hard = sum(1 for e_, node, u in st.rule_log if e_ == "exclude" and st.honest[node])
    byz_conv = len({node for e_, node, u in st.rule_log if e_ in ("exclude", "exclude_soft") and st.byz[node]})
    pf = perf(st, VIEWS // 2, end)
    pb = st.__dict__.get("prop_bytes", {})
    mb = float(np.mean([pb[w] for w in range(VIEWS // 2, end) if w in pb])) / 1e6 if pb else float("nan")
    return dict(mode=mode, fwd=fwd or "off", soft=soft, eps=eps, target=target, seed=seed, beta=float(base[byz].sum()),
                n_byz=int(byz.sum()), fail_byz=float(noqc[bl].mean()) if bl.any() else float("nan"),
                fail_honest=float(noqc[hl].mean()), honest_soft_per_1000=1000.0 * hon_soft / max(1, int(hl.sum())),
                honest_hard=hon_hard, byz_excluded=byz_conv / int(byz.sum()),
                colluder_lead_late=float(np.mean(st.byz[st.leaders[VIEWS // 2:end]])),
                commit_late=pf["commit"], bps_late=pf["bps"], view_ms_late=pf["view_ms"], mb_per_view=mb)


def run():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    jobs = [(m, f, so, e, 0.2, s) for m in MODES for f in FWDS for so in SOFTS for e in EPS for s in range(SEEDS)]
    jobs += [(m, f, so, e, 0.27, s) for m in ("none", "targeted", "frame_withhold") for f in FWDS for so in SOFTS for e in EPS
             for s in range(SEEDS)]
    with Pool(PROCS) as pool:
        rows = pool.map(job, jobs, chunksize=1)
    ref = {(o["soft"], o["eps"], o["target"], o["seed"]): o for o in rows if o["mode"] == "none" and o["fwd"] == "off"}
    for o in rows:
        r = ref.get((o["soft"], o["eps"], o["target"], o["seed"]))
        o["bps_rel"] = o["bps_late"] / r["bps_late"] if r else float("nan")
        o["bytes_rel"] = o["mb_per_view"] / r["mb_per_view"] if r else float("nan")
    with open(os.path.join(OUT, "dirTtru_fwd.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    L = [f"# 提案转发对部分发送的作用（每格 {SEEDS} 个人群，{VIEWS} 视图；P2；AT x=2/3、ρ̄=0.1；软证据：关闭或出块时长 "
         f"θ={int(SLOT_THETA)} ms、ρ̄_s={SLOT_RHO}）\n",
         "转发：off = 不转发；hdr = 诚实节点转发签名的提案头，缺块者向任一持有块的诚实节点取块（取到的也能再供给）；"
         "full = 诚实节点转发整个提案。拜占庭节点不转发。\n",
         "吞吐与字节数均相对同 ε、同软证据设置、无对手且不转发的运行；字节数只计提案相关（块 250 kB、头 4 kB），"
         "网络模型不含上行带宽竞争。\n"]
    P = L.append
    for tg in (0.2, 0.27):
        modes = MODES if tg == 0.2 else ("none", "targeted", "frame_withhold")
        beta = np.mean([o["beta"] for o in rows if o["target"] == tg])
        for so in SOFTS:
            P(f"\n## 同伙基础份额约 {beta:.2f}，软证据{'关闭' if so == 'off' else '为出块时长分数'}：吞吐 / 提交比例 / 字节数（相对基线）"
              " / 同伙视图失败率 / 诚实软、硬误定罪（每千个诚实领导视图、总次数）\n")
            P("| 对手 | 转发 | " + " | ".join(f"ε={e}" for e in EPS) + " |")
            P("|---|---|" + "---|" * len(EPS))
            for m in modes:
                for f in ("off", "hdr", "full"):
                    cells = []
                    for e in EPS:
                        g = [o for o in rows if (o["mode"], o["fwd"], o["soft"], o["eps"], o["target"]) == (m, f, so, e, tg)]
                        mm = lambda c: float(np.nanmean([o[c] for o in g]))  # noqa: E731
                        cells.append(f"{mm('bps_rel'):.2f} / {mm('commit_late'):.3f} / {mm('bytes_rel'):.1f}× / "
                                     f"{mm('fail_byz'):.2f} / {mm('honest_soft_per_1000'):.2f}、{sum(o['honest_hard'] for o in g)}")
                    P(f"| {m} | {f} | " + " | ".join(cells) + " |")
    P("\n## 沉默领导者仍被 AT 排除（软证据关闭，ε=0）：同伙被排除比例\n")
    for f in ("off", "hdr", "full"):
        g = [o for o in rows if (o["mode"], o["fwd"], o["soft"], o["eps"], o["target"]) == ("silent", f, "off", 0.0, 0.2)]
        P(f"- 转发 {f}：{np.mean([o['byz_excluded'] for o in g]):.2f}")
    P(f"\nwall {time.time() - t0:.0f}s")
    with open(os.path.join(OUT, "dirTtru_fwd.md"), "w") as fh:
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
    for o in rows:
        for k_ in ("eps", "target", "bps_rel", "bytes_rel"):
            o[k_] = float(o[k_])

    def mean(key_, **cond):
        g = [o[key_] for o in rows if all(o[k] == v for k, v in cond.items())]
        return float(np.nanmean(g)) if g else float("nan")

    col = {"off": "#555555", "hdr": "#2a78d6", "full": "#eb6834"}
    lab = {"off": "不转发", "hdr": "转发提案头 + 取块", "full": "转发整个提案"}
    modes = ("none", "targeted", "adaptive", "slow1800", "frame_withhold")
    names = ("无对手", "定向部分发送", "了解规则的\n部分发送", "慢领导者", "扣票 + 迟到")
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.3))
    xs = np.arange(len(modes))
    for i, f in enumerate(("off", "hdr", "full")):
        y = [mean("bps_rel", mode=m, fwd=f, soft="slot", eps=0.05 if m == "frame_withhold" else 0.0, target=0.2) for m in modes]
        ax[0].bar(xs + (i - 1) * 0.27, y, 0.25, color=col[f], label=lab[f])
    ax[0].set_xticks(xs, names, fontsize=8)
    ax[0].set_ylim(0, 1.15)
    ax[0].axhline(1, color="#999", lw=0.8)
    ax[0].set_ylabel("吞吐（相对无对手、不转发）")
    ax[0].set_title("吞吐（软证据为出块时长分数；扣票 + 迟到取 ε=0.05，其余 ε=0）", fontsize=9)
    ax[0].legend(fontsize=8, frameon=False, loc="upper right")
    ax[0].grid(alpha=0.25, lw=0.5, axis="y")
    for f in ("off", "hdr", "full"):
        y = [mean("bytes_rel", mode="none", fwd=f, soft="slot", eps=e, target=0.2) for e in EPS]
        ax[1].plot(EPS, y, color=col[f], lw=2, marker="o", ms=4, label=lab[f])
    ax[1].set_yscale("log")
    ax[1].set_xlabel("消息迟到率 ε")
    ax[1].set_ylabel("每视图提案字节数（相对不转发，对数轴）")
    ax[1].set_title("带宽代价（无对手）", fontsize=9)
    ax[1].legend(fontsize=8, frameon=False)
    ax[1].grid(alpha=0.25, lw=0.5)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_fwd.png"), dpi=160, bbox_inches="tight")


if __name__ == "__main__":
    plot() if (len(sys.argv) > 1 and sys.argv[1] == "plot") else run()

"""P2 "no QC" as soft evidence (信任2.0_协议级验证 §3.2), v0.6 after review 信任2.0_v05_审查_{代码,实验与文档}.

Same population, colluders and weights as dirTtru (n = 31). Colluders: the cheapest set reaching a base
share target (0.2 -> beta ~0.24, or 0.27 -> beta ~0.28, capped at 0.30). Leader rule: CUSUM over AT (x = 2/3,
rho_bar = 0.03, q = 0.5) plus a second CUSUM over "noqc" (no QC of the view exists; P2 broadcasts votes)
with soft_q = 0.9 and soft_rho in {0.1, 0.3, 0.5, 0.7} or off. Soft convictions only bar the replica from
leading (weight cap 0.5, D = 500); T_tru reputation moves on hard (AT) convictions only (fixed queue,
review code #1-#3: honest hard convictions are now reported and must stay 0 under soft evidence).
Throughput is measured as committed blocks per second (ttru_perf.perf), relative to the run without any
adversary at the same eps and seed ("none").

Modes:
  none            no adversary (baseline; honest views fail only through late messages)
  frame_withhold  colluders withhold votes in honest leaders' views and claim NR=1 (worst-case framing)
  targeted        colluding leaders send only to the k heaviest honest replicas (k evades AT at 2/3)
  targeted_half   the same in half of their views
  adaptive        rule-aware: attacks only while its copy of the soft CUSUM stays below h
  slow            colluding leaders delay their proposal by 1800 ms (< timeout 2 s): QC forms, no evidence
  combo           adaptive partial send plus the slow leader in the remaining views
Environment: SIM_PROCS (default 8), SIM_SEEDS (default 16; attack modes use half).
Run from the repository root:  python -m sim2.experiments.dirTtruSoft [run|plot]
Out: results/dirTtru_soft.csv, dirTtru_soft.md; results/fig_soft.png (plot, needs matplotlib).
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
SEEDS = int(os.environ.get("SIM_SEEDS", "16"))
SOFT_Q = 0.9
H = float(np.log(1e4))
VIEWS = 2000
RHOS = (None, 0.1, 0.3, 0.5, 0.7)
EPS_FRAME = (0.0, 0.05, 0.1, 0.2)
EPS_ATTACK = (0.0, 0.1)
ATTACKS = ("targeted", "targeted_half", "adaptive", "slow", "combo")


def p_star(rho, q=SOFT_Q):
    a, b = np.log(q / rho), np.log((1 - rho) / (1 - q))
    return float(b / (a + b))


def job(args):
    mode, rho, eps, target, seed = args
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, target, max_share=0.30)
    kw = {} if rho is None else dict(soft_evidence="noqc", soft_rho=rho, soft_q=SOFT_Q)
    rule = S.CusumExclusion(q=0.5, evidence="at", rho_bar=0.03, D=500, cap=0.5, Wq=500, cap_weights=base, **kw)
    vw = ttru.TtruWeights(base, epoch=100, rule=rule)
    k = evade_k(base, byz, 2 / 3)
    sr = 0.5 if rho is None else rho
    adaptive = A.AdaptivePartialSend(k, float(np.log(SOFT_Q / sr)), float(np.log((1 - SOFT_Q) / (1 - sr))), H)
    adv = {"none": None, "frame_withhold": A.Compose([A.LieNR(), A.WithholdVotesOnHonest()]),
           "targeted": A.PartialSend(k, targeted=True), "targeted_half": A.PartialSend(k, targeted=True, p=0.5),
           "adaptive": adaptive, "slow": A.SlowLeader(1800.0),
           "combo": A.Compose([adaptive, A.SlowLeader(1800.0)])}[mode]
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol="P2", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    adversary=adv, vote_weights=vw, at_share=2 / 3)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps)), st, 1,
                          VIEWS)
    end = VIEWS - 10
    lead = st.leaders[1:end]
    hl, bl = st.honest[lead], st.byz[lead]
    noqc = ~st.qc_exists[1:end]
    excl = np.zeros(N, bool)
    hon_w = np.zeros(end)
    last, cur = 1, 0.0
    hon_soft = hon_hard = 0
    byz_first = {}
    for ev, node, u in st.rule_log:
        if ev not in ("exclude", "exclude_soft", "release"):
            continue
        u = min(max(u, 1), end)
        hon_w[last:u] = cur
        last = u
        if ev == "release":
            excl[node] = False
        else:
            excl[node] = True
            if st.honest[node]:
                hon_soft += ev == "exclude_soft"
                hon_hard += ev == "exclude"
            elif node not in byz_first:
                byz_first[node] = sum(1 for y in range(1, u + 1) if st.leaders[y] == node)
        cur = float(base[excl & st.honest].sum())
    hon_w[last:end] = cur
    w_end = vw.table(st, (VIEWS - 11) // 100)
    pf = perf(st, VIEWS // 2, end)
    return dict(mode=mode, rho=-1.0 if rho is None else rho, eps=eps, target=target, seed=seed,
                beta=float(base[byz].sum()), honest_led=int(hl.sum()), noqc_honest=float(noqc[hl].mean()),
                noqc_byz=float(noqc[bl].mean()) if bl.any() else float("nan"),
                honest_soft_per_1000=1000.0 * hon_soft / max(1, int(hl.sum())), honest_hard=hon_hard,
                honest_excluded_w=float(hon_w[1:end].mean()), byz_convicted=len(byz_first), n_byz=int(byz.sum()),
                views_to_conviction=float(np.mean(list(byz_first.values()))) if byz_first else float("nan"),
                colluder_lead_late=float(np.mean(st.byz[st.leaders[VIEWS // 2:end]])),
                colluder_vote_share_end=float(w_end[st.byz].sum()),
                qc_rate_late=float(np.mean(st.qc_exists[VIEWS // 2:end])), commit_late=pf["commit"], bps_late=pf["bps"],
                view_ms_late=pf["view_ms"])


def label(rho):
    return "关闭" if rho < 0 else f"{rho}"


def rel_bps(rows, o):
    """bps of a run relative to the no-adversary run with the same rho, eps, target and seed."""
    b = [x["bps_late"] for x in rows if x["mode"] == "none" and (x["rho"], x["eps"], x["target"], x["seed"]) ==
         (o["rho"], o["eps"], o["target"], o["seed"])]
    return o["bps_late"] / b[0] if b else float("nan")


def run():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    jobs = [(m, r, e, 0.2, s) for m in ("none", "frame_withhold") for r in RHOS for e in EPS_FRAME for s in range(SEEDS)]
    jobs += [(m, r, e, 0.27, s) for m in ("none", "frame_withhold") for r in (None, 0.5, 0.7) for e in EPS_FRAME
             for s in range(SEEDS)]
    jobs += [(m, r, e, 0.2, s) for m in ATTACKS for r in (None, 0.3, 0.5, 0.7) for e in EPS_ATTACK
             for s in range(SEEDS // 2)]
    with Pool(PROCS) as pool:
        rows = pool.map(job, jobs, chunksize=1)
    for o in rows:
        o["bps_rel"] = rel_bps(rows, o)
    with open(os.path.join(OUT, "dirTtru_soft.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    rk = lambda r: -1.0 if r is None else r  # noqa: E731
    L = [f"# P2 \"无 QC\" 软证据 v0.6（陷害格每格 {SEEDS} 个人群，攻击格 {SEEDS // 2} 个；{VIEWS} 视图；软 CUSUM q={SOFT_Q}，"
         "h=ln 1e4；AT x=2/3、ρ̄=0.03）\n",
         "软 CUSUM 漂移转正的失败率 p*(ρ̄_s)：" + "，".join(f"{r}: {p_star(r):.2f}" for r in RHOS if r) + "\n",
         "吞吐 = 后半段每秒提交的块数，相对同 ε、同人群、无对手的运行。\n"]
    P = L.append
    for target, rset in ((0.2, RHOS), (0.27, (None, 0.5, 0.7))):
        for m, title in (("none", "无对手（只有迟到）"), ("frame_withhold", "陷害：同伙在诚实视图中扣票并谎报 NR=1，叠加迟到")):
            G0 = [o for o in rows if o["target"] == target and o["mode"] == m]
            beta = np.mean([o["beta"] for o in G0])
            P(f"\n## {title}（同伙基础份额约 {beta:.2f}）：诚实视图无 QC 比例 / 每千个诚实领导视图的软误定罪 / "
              "诚实硬定罪（总数，人群数） / 平均被排除的诚实权重 / 吞吐（相对无对手）\n")
            P("| 软证据 ρ̄_s | " + " | ".join(f"ε={e}" for e in EPS_FRAME) + " |")
            P("|---|" + "---|" * len(EPS_FRAME))
            for r in rset:
                cells = []
                for e in EPS_FRAME:
                    g = [o for o in G0 if (o["rho"], o["eps"]) == (rk(r), e)]
                    mm = lambda c: float(np.mean([o[c] for o in g]))  # noqa: E731
                    hh = sum(o["honest_hard"] for o in g)
                    cells.append(f"{mm('noqc_honest'):.3f} / {mm('honest_soft_per_1000'):.2f} / {hh}（{sum(o['honest_hard'] > 0 for o in g)}）"
                                 f" / {mm('honest_excluded_w'):.3f} / {mm('bps_rel'):.2f}")
                P(f"| {label(rk(r))} | " + " | ".join(cells) + " |")
    P("\n## 领导者攻击（同伙基础份额约 0.24）：同伙被排除比例 / 排除前领导次数 / 后半段同伙领导份额 / 同伙视图无 QC 比例 / "
      "吞吐（相对无对手） / QC 率\n")
    P("| 攻击 | ρ̄_s | " + " | ".join(f"ε={e}" for e in EPS_ATTACK) + " |")
    P("|---|---|" + "---|" * len(EPS_ATTACK))
    for m in ATTACKS:
        for r in (None, 0.3, 0.5, 0.7):
            cells = []
            for e in EPS_ATTACK:
                g = [o for o in rows if (o["mode"], o["rho"], o["eps"], o["target"]) == (m, rk(r), e, 0.2)]
                mm = lambda c: float(np.nanmean([o[c] for o in g]))  # noqa: E731
                vtc = mm("views_to_conviction") if any(o["byz_convicted"] for o in g) else float("nan")
                cells.append(f"{np.mean([o['byz_convicted'] / o['n_byz'] for o in g]):.2f} / {vtc:.1f} / "
                             f"{mm('colluder_lead_late'):.3f} / {mm('noqc_byz'):.2f} / {mm('bps_rel'):.2f} / {mm('qc_rate_late'):.3f}")
            P(f"| {m} | {label(rk(r))} | " + " | ".join(cells) + " |")
    P(f"\nwall {time.time() - t0:.0f}s")
    with open(os.path.join(OUT, "dirTtru_soft.md"), "w") as fh:
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
    rows = list(csv.DictReader(open(os.path.join(OUT, "dirTtru_soft.csv"))))
    for o in rows:
        for k_ in ("rho", "eps", "target", "noqc_honest", "honest_soft_per_1000", "bps_rel", "honest_hard"):
            o[k_] = float(o[k_])
    col = {0.1: "#2a78d6", 0.3: "#eb6834", 0.5: "#1baf7a", 0.7: "#eda100", -1.0: "#555555"}

    def mean(key, **cond):
        g = [o[key] for o in rows if all(o[k] == v for k, v in cond.items())]
        return float(np.nanmean(g)) if g else float("nan")

    fig, ax = plt.subplots(1, 3, figsize=(14, 4.3))
    eps = list(EPS_FRAME)
    for t, ls in ((0.2, "-"), (0.27, "--")):
        ax[0].plot(eps, [mean("noqc_honest", mode="frame_withhold", rho=-1.0, eps=e, target=t) for e in eps], color="#555",
                   ls=ls, lw=2, marker="o", ms=4, label=f"扣票 + 迟到，同伙份额约 {0.24 if t == 0.2 else 0.28}")
    for r in (0.1, 0.3, 0.5, 0.7):
        ax[0].axhline(p_star(r), color=col[r], lw=1, ls=":", label=rf"p* ($\bar\rho_s$={r}) = {p_star(r):.2f}")
    ax[0].set_xlabel("消息迟到率 ε")
    ax[0].set_ylabel("诚实领导视图无 QC 的比例")
    ax[0].set_title("诚实领导者的视图失败率", fontsize=9)
    ax[0].legend(fontsize=7, frameon=False)
    ax[0].grid(alpha=0.25, lw=0.5)
    for r in (0.1, 0.3, 0.5, 0.7):
        ax[1].plot(eps, [mean("honest_soft_per_1000", mode="frame_withhold", rho=r, eps=e, target=0.2) for e in eps],
                   color=col[r], lw=2, marker="o", ms=4, label=rf"$\bar\rho_s$ = {r}（份额约 0.24）")
        if r in (0.5, 0.7):
            ax[1].plot(eps, [mean("honest_soft_per_1000", mode="frame_withhold", rho=r, eps=e, target=0.27) for e in eps],
                       color=col[r], lw=1.4, ls="--", marker="o", ms=3, label=rf"$\bar\rho_s$ = {r}（份额约 0.28）")
    ax[1].set_xlabel("消息迟到率 ε")
    ax[1].set_ylabel("每千个诚实领导视图的软误定罪")
    ax[1].set_title("软证据的误定罪（同伙扣票 + 迟到）", fontsize=9)
    ax[1].legend(fontsize=7, frameon=False, loc="upper left")
    ax[1].grid(alpha=0.25, lw=0.5)
    names = ["关闭", "0.3", "0.5", "0.7"]
    xs = np.arange(4)
    for i, (m, c, lab) in enumerate((("targeted", "#2a78d6", "定向部分发送（每次）"), ("adaptive", "#eb6834", "了解规则的部分发送"),
                                     ("slow", "#1baf7a", "慢领导者（1.8 s）"), ("combo", "#eda100", "了解规则 + 慢领导者"))):
        y = [mean("bps_rel", mode=m, rho=r, eps=0.0, target=0.2) for r in (-1.0, 0.3, 0.5, 0.7)]
        ax[2].bar(xs + (i - 1.5) * 0.2, y, 0.18, color=c, label=lab)
    ax[2].set_xticks(xs, names)
    ax[2].set_ylim(0, 1.0)
    ax[2].set_xlabel(r"软证据 $\bar\rho_s$")
    ax[2].set_ylabel("吞吐（相对无对手，ε=0）")
    ax[2].set_title("领导者攻击下的吞吐（每秒提交块数）", fontsize=9)
    ax[2].legend(fontsize=7, frameon=True, framealpha=0.9, edgecolor="none", loc="upper left")
    ax[2].grid(alpha=0.25, lw=0.5, axis="y")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_soft.png"), dpi=160, bbox_inches="tight")


if __name__ == "__main__":
    plot() if (len(sys.argv) > 1 and sys.argv[1] == "plot") else run()

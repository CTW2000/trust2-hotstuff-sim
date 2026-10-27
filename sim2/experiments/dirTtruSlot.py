"""Weighted slot-duration score as soft evidence against slow leaders and partial send (信任2.0_协议级验证 §3.7).

Same population, colluders and weights as dirTtru (n = 31; colluders = cheapest set with base share target
0.2 -> ~0.24 or 0.27 -> ~0.28, capped at 0.30). P2. Leader rule: CUSUM over AT (x = 2/3, rho_bar = 0.1,
q = 0.5) plus a soft CUSUM (soft_q = 0.9) over one soft evidence:
  off   no soft evidence
  noqc  no QC of the view exists (rho_s = 0.7; the v0.6 option)
  slot  weighted slot-duration score above theta (schedule.weighted_slot_score; colluders lie in their
        reports and a colluding assembler picks the honest reports that suit it), theta in {200, 400, 800} ms,
        rho_s in {0.5, 0.7}
Soft convictions only bar the replica from leading (weight cap 0.5, D = 500); reputation moves on AT only.
Throughput: committed blocks per second in the second half, relative to the run with no adversary and no
soft evidence at the same eps, target and seed.

Modes:
  none            no adversary (honest views fail or slow down only through late messages)
  frame_withhold  colluders withhold votes in honest leaders' views, claim NR=1, and report +inf slots
  slow1800        colluding leaders delay their proposal by 1800 ms (timeout 2 s)
  slow_evade      colluding leaders delay by theta - 150 ms, keeping the score just under theta
                  (for off / noqc: 250 ms, the same as against theta = 400)
  targeted        partial send to the k heaviest honest replicas (evades AT at 2/3) in every view
  adaptive        rule-aware partial send (copy of the soft CUSUM over failed views)
  combo           adaptive partial send plus slow_evade in the other views
Environment: SIM_PROCS (default 8), SIM_SEEDS (default 16; attack modes use half).
Run from the repository root:  python -m sim2.experiments.dirTtruSlot [run|plot]
Out: results/dirTtru_slot.csv, dirTtru_slot.md; results/fig_slot.png (plot, needs matplotlib).
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
THETAS = (200.0, 400.0, 800.0)
SLOT_RHOS = (0.5, 0.7)
EPS_FRAME = (0.0, 0.05, 0.1, 0.2)
EPS_ATTACK = (0.0, 0.1)
ATTACKS = ("slow1800", "slow_evade", "targeted", "adaptive", "combo")
SOFT_CFGS = [("off", None, None), ("noqc", None, 0.7)] + [("slot", t, r) for t in THETAS for r in SLOT_RHOS]


def p_star(rho, q=SOFT_Q):
    a, b = np.log(q / rho), np.log((1 - rho) / (1 - q))
    return float(b / (a + b))


def job(args):
    mode, ev, theta, rho, eps, target, seed = args
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, target, max_share=0.30)
    kw = {} if ev == "off" else dict(soft_evidence=ev, soft_rho=rho, soft_q=SOFT_Q)
    rule = S.CusumExclusion(q=0.5, evidence="at", rho_bar=0.1, D=500, cap=0.5, Wq=500, cap_weights=base, **kw)
    vw = ttru.TtruWeights(base, epoch=100, rule=rule)
    k = evade_k(base, byz, 2 / 3)
    sr = 0.7 if rho is None else rho
    adaptive = A.AdaptivePartialSend(k, float(np.log(SOFT_Q / sr)), float(np.log((1 - SOFT_Q) / (1 - sr))), H)
    xi_evade = (theta if theta is not None else 400.0) - 150.0
    adv = {"none": None, "frame_withhold": A.Compose([A.LieNR(), A.WithholdVotesOnHonest()]),
           "slow1800": A.SlowLeader(1800.0), "slow_evade": A.SlowLeader(xi_evade),
           "targeted": A.PartialSend(k, targeted=True), "adaptive": adaptive,
           "combo": A.Compose([adaptive, A.SlowLeader(xi_evade)])}[mode]
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol="P2", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    adversary=adv, vote_weights=vw, at_share=2 / 3, slot_theta_ms=theta)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps)), st, 1,
                          VIEWS)
    end = VIEWS - 10
    lead = st.leaders[1:end]
    hl, bl = st.honest[lead], st.byz[lead]
    soft_fact = np.array([S.bad_fact(st, u, u + cfg.lag, ev) for u in range(1, end)]) if ev != "off" else np.zeros(end - 1, bool)
    hon_soft = hon_hard = 0
    byz_first = {}
    excl = np.zeros(N, bool)
    hon_w = np.zeros(end)
    last, cur = 1, 0.0
    for e_, node, u in st.rule_log:
        if e_ not in ("exclude", "exclude_soft", "release"):
            continue
        u = min(max(u, 1), end)
        hon_w[last:u] = cur
        last = u
        if e_ == "release":
            excl[node] = False
        else:
            excl[node] = True
            if st.honest[node]:
                hon_soft += e_ == "exclude_soft"
                hon_hard += e_ == "exclude"
            elif node not in byz_first:
                byz_first[node] = sum(1 for y in range(1, u + 1) if st.leaders[y] == node)
        cur = float(base[excl & st.honest].sum())
    hon_w[last:end] = cur
    pf = perf(st, VIEWS // 2, end)
    return dict(mode=mode, ev=ev, theta=-1.0 if theta is None else theta, rho=-1.0 if rho is None else rho, eps=eps,
                target=target, seed=seed, beta=float(base[byz].sum()), n_byz=int(byz.sum()), honest_led=int(hl.sum()),
                soft_fact_honest=float(soft_fact[hl].mean()), soft_fact_byz=float(soft_fact[bl].mean()) if bl.any() else float("nan"),
                honest_soft_per_1000=1000.0 * hon_soft / max(1, int(hl.sum())), honest_hard=hon_hard,
                honest_excluded_w=float(hon_w[1:end].mean()), byz_convicted=len(byz_first),
                views_to_conviction=float(np.mean(list(byz_first.values()))) if byz_first else float("nan"),
                colluder_lead_late=float(np.mean(st.byz[st.leaders[VIEWS // 2:end]])),
                commit_late=pf["commit"], bps_late=pf["bps"], view_ms_late=pf["view_ms"])


def key(o):
    return (o["ev"], o["theta"], o["rho"])


def lab(ev, theta, rho):
    if ev == "off":
        return "关闭"
    if ev == "noqc":
        return f"无 QC，ρ̄_s={rho}"
    return f"时长 θ={int(theta)} ms，ρ̄_s={rho}"


def run():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    frame_cfgs = [("off", None, None)] + [("slot", t, r) for t in THETAS for r in SLOT_RHOS]
    jobs = [(m, ev, t, r, e, tg, s) for tg in (0.2, 0.27) for m in ("none", "frame_withhold") for ev, t, r in frame_cfgs
            for e in EPS_FRAME for s in range(SEEDS)]
    jobs += [(m, ev, t, r, e, 0.2, s) for m in ATTACKS for ev, t, r in SOFT_CFGS for e in EPS_ATTACK for s in range(SEEDS // 2)]
    with Pool(PROCS) as pool:
        rows = pool.map(job, jobs, chunksize=1)
    base_bps = {(o["eps"], o["target"], o["seed"]): o["bps_late"] for o in rows if o["mode"] == "none" and o["ev"] == "off"}
    for o in rows:
        b = base_bps.get((o["eps"], o["target"], o["seed"]))
        o["bps_rel"] = o["bps_late"] / b if b else float("nan")
    with open(os.path.join(OUT, "dirTtru_slot.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    L = [f"# 加权出块时长分数作为软证据（陷害格每格 {SEEDS} 个人群，攻击格 {SEEDS // 2} 个；{VIEWS} 视图；AT x=2/3、ρ̄=0.1；"
         f"软 CUSUM q={SOFT_Q}）\n",
         "软 CUSUM 漂移转正的坏事实率 p*(ρ̄_s)：" + "，".join(f"{r}: {p_star(r):.2f}" for r in (0.5, 0.7)) + "\n",
         "吞吐 = 后半段每秒提交块数，相对同 ε、同人群、无对手且不加软证据的运行。\n"]
    P = L.append
    frame_keys = [("off", -1.0, -1.0)] + [("slot", t, r) for t in THETAS for r in SLOT_RHOS]
    for tg in (0.2, 0.27):
        for m, title in (("none", "无对手（只有迟到）"), ("frame_withhold", "陷害：同伙扣票、谎报 NR=1、在时长报告中谎报 +∞，叠加迟到")):
            G0 = [o for o in rows if o["target"] == tg and o["mode"] == m]
            P(f"\n## {title}（同伙基础份额约 {np.mean([o['beta'] for o in G0]):.2f}）：诚实视图被记坏事实的比例 / "
              "每千个诚实领导视图的软误定罪 / 诚实硬定罪 / 平均被排除的诚实权重 / 吞吐\n")
            P("| 软证据 | " + " | ".join(f"ε={e}" for e in EPS_FRAME) + " |")
            P("|---|" + "---|" * len(EPS_FRAME))
            for kk in frame_keys:
                cells = []
                for e in EPS_FRAME:
                    g = [o for o in G0 if key(o) == kk and o["eps"] == e]
                    mm = lambda c: float(np.mean([o[c] for o in g]))  # noqa: E731
                    cells.append(f"{mm('soft_fact_honest'):.3f} / {mm('honest_soft_per_1000'):.2f} / "
                                 f"{sum(o['honest_hard'] for o in g)} / {mm('honest_excluded_w'):.3f} / {mm('bps_rel'):.2f}")
                P(f"| {lab(kk[0], kk[1], kk[2])} | " + " | ".join(cells) + " |")
    P("\n## 领导者攻击（同伙基础份额约 0.24）：同伙被排除比例 / 排除前领导次数 / 同伙视图被记坏事实的比例 / 吞吐\n")
    P("| 攻击 | 软证据 | " + " | ".join(f"ε={e}" for e in EPS_ATTACK) + " |")
    P("|---|---|" + "---|" * len(EPS_ATTACK))
    for m in ATTACKS:
        for ev, t, r in SOFT_CFGS:
            kk = (ev, -1.0 if t is None else t, -1.0 if r is None else r)
            cells = []
            for e in EPS_ATTACK:
                g = [o for o in rows if o["mode"] == m and key(o) == kk and o["eps"] == e]
                mm = lambda c: float(np.nanmean([o[c] for o in g]))  # noqa: E731
                vtc = mm("views_to_conviction") if any(o["byz_convicted"] for o in g) else float("nan")
                cells.append(f"{np.mean([o['byz_convicted'] / o['n_byz'] for o in g]):.2f} / {vtc:.1f} / "
                             f"{mm('soft_fact_byz'):.2f} / {mm('bps_rel'):.2f}")
            P(f"| {m} | {lab(ev, t, r)} | " + " | ".join(cells) + " |")
    P(f"\nwall {time.time() - t0:.0f}s")
    with open(os.path.join(OUT, "dirTtru_slot.md"), "w") as fh:
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
    rows = list(csv.DictReader(open(os.path.join(OUT, "dirTtru_slot.csv"))))
    for o in rows:
        for k_ in ("theta", "rho", "eps", "target", "honest_soft_per_1000", "bps_rel"):
            o[k_] = float(o[k_])

    def mean(key_, **cond):
        g = [o[key_] for o in rows if all(o[k] == v for k, v in cond.items())]
        return float(np.nanmean(g)) if g else float("nan")

    col = {200.0: "#2a78d6", 400.0: "#eb6834", 800.0: "#1baf7a"}
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.3))
    eps = list(EPS_FRAME)
    for t in THETAS:
        for tg, ls in ((0.2, "-"), (0.27, "--")):
            ax[0].plot(eps, [mean("honest_soft_per_1000", mode="frame_withhold", ev="slot", theta=t, rho=0.7, eps=e, target=tg)
                             for e in eps], color=col[t], ls=ls, lw=2 if ls == "-" else 1.3, marker="o", ms=4,
                       label=f"θ={int(t)} ms，同伙份额约 {0.24 if tg == 0.2 else 0.28}")
    ax[0].set_xlabel("消息迟到率 ε")
    ax[0].set_ylabel("每千个诚实领导视图的软误定罪")
    ax[0].set_title(r"陷害下的软误定罪（$\bar\rho_s$=0.7）", fontsize=9)
    ax[0].legend(fontsize=7, frameon=False, loc="upper left")
    ax[0].grid(alpha=0.25, lw=0.5)
    cfgs = [("off", -1.0, -1.0, "关闭"), ("noqc", -1.0, 0.7, "无 QC")] + [("slot", t, 0.7, f"θ={int(t)}") for t in THETAS]
    xs = np.arange(len(cfgs))
    for i, (m, c, name) in enumerate((("slow1800", "#2a78d6", "慢领导者 1.8 s"), ("slow_evade", "#eb6834", "刚好低于门限的慢领导者"),
                                      ("adaptive", "#1baf7a", "了解规则的部分发送"), ("combo", "#eda100", "组合"))):
        y = [mean("bps_rel", mode=m, ev=ev, theta=t, rho=r, eps=0.0) for ev, t, r, _ in cfgs]
        ax[1].bar(xs + (i - 1.5) * 0.2, y, 0.18, color=c, label=name)
    ax[1].set_xticks(xs, [c[3] for c in cfgs])
    ax[1].set_ylim(0, 1.0)
    ax[1].set_xlabel(r"软证据（$\bar\rho_s$=0.7）")
    ax[1].set_ylabel("吞吐（相对无对手，ε=0）")
    ax[1].set_title("领导者攻击下的吞吐（每秒提交块数）", fontsize=9)
    ax[1].legend(fontsize=7, frameon=True, framealpha=0.9, edgecolor="none", loc="upper left")
    ax[1].grid(alpha=0.25, lw=0.5, axis="y")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_slot.png"), dpi=160, bbox_inches="tight")


if __name__ == "__main__":
    plot() if (len(sys.argv) > 1 and sys.argv[1] == "plot") else run()

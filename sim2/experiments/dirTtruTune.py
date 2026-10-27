"""Joint tuning of the weighted AT threshold x and the CUSUM pre-change rate rho_bar (信任2.0_协议级验证 §3.1).

Same population, colluders and weights as dirTtru (n = 31, colluders = the cheapest ~0.24 of base weight,
T_tru weights with reputation, weight-based exclusion cap 0.5); CUSUM over AT evidence with
q = 0.5, gamma = 1e4, D = 500. Network model S with every message independently late with probability
eps (late_extra 5 s, so a late proposal makes its receiver report NR=1).

Mode "frame":    colluders claim NR=1 in honest leaders' views (LieNR) on top of the late messages; we
                 measure the AT accusation rate of honest-led views and the false convictions of honest
                 replicas (per 1000 honest-led views) and the honest weight excluded (time average).
Mode "silent":   colluding leaders send nothing.
Mode "targeted": colluding leaders send only to the k heaviest honest replicas, k the smallest that evades
                 AT at x = 2/3 (fixed attacker strength across x); we measure detection and the views a
                 colluder leads before conviction.
Mode "targeted_x": the adversary picks k for THIS x (the smallest k that evades x); run with
                 `run_x` (rho 0.03, eps 0 and 0.1) to check that an optimizing leader evades any x.
Analytic reference: CUSUM drift is positive when the accusation rate p exceeds
p*(rho_bar) = ln((1-rho)/(1-q)) / (ln(q/rho) + ln((1-rho)/(1-q))).

Environment: SIM_PROCS (default 8), SIM_SEEDS (default 8).
Run from the repository root:  python -m sim2.experiments.dirTtruTune [run|plot]
Out: results/dirTtru_tune.csv, dirTtru_tune.md (run); results/fig_at_tune.png (plot, needs matplotlib).
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
from sim2.net import NetConfig, Network

PROCS = int(os.environ.get("SIM_PROCS", "8"))
SEEDS = int(os.environ.get("SIM_SEEDS", "8"))
XS = (0.5, 0.55, 0.6, 2 / 3)
RHOS = (0.01, 0.03, 0.1)
EPS_FRAME = (0.0, 0.05, 0.1, 0.15, 0.2, 0.3)
EPS_DETECT = (0.0, 0.1, 0.2)
Q_POST = 0.5
VIEWS = 3000


def p_star(rho, q=Q_POST):
    a, b = np.log(q / rho), np.log((1 - rho) / (1 - q))
    return float(b / (a + b))


def job(args):
    mode, x, rho, eps, seed = args[:5]
    target = args[5] if len(args) > 5 else 0.2
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, target, max_share=0.30)
    rule = S.CusumExclusion(q=Q_POST, evidence="at", rho_bar=rho, D=500, cap=0.5, Wq=500, cap_weights=base)
    vw = ttru.TtruWeights(base, epoch=100, rule=rule)
    if mode == "frame":
        adv = A.LieNR()
    elif mode == "silent":
        adv = A.SilentLeader(1.0)
    elif mode == "targeted":
        adv = A.PartialSend(evade_k(base, byz, 2 / 3), targeted=True)
    else:                                          # "targeted_x": recipients chosen to evade this x
        adv = A.PartialSend(evade_k(base, byz, x), targeted=True)
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol="P2", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    adversary=adv, vote_weights=vw, at_share=x)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps)), st, 1,
                          VIEWS)
    end = VIEWS - 10
    acc = np.array([S.bad_fact(st, u, u + cfg.lag, "at") for u in range(1, end)])
    lead = st.leaders[1:end]
    hl, bl = st.honest[lead], st.byz[lead]
    # exclusions: honest false convictions and time-averaged excluded honest weight
    excl = np.zeros(N, bool)
    hon_w = np.zeros(end)
    last, cur = 1, 0.0
    hon_conv, byz_first = 0, {}
    for ev, node, u in st.rule_log:
        if ev not in ("exclude", "release"):
            continue
        u = min(max(u, 1), end)
        hon_w[last:u] = cur
        last = u
        if ev == "exclude":
            excl[node] = True
            if st.honest[node]:
                hon_conv += 1
            elif node not in byz_first:
                byz_first[node] = sum(1 for y in range(1, u + 1) if st.leaders[y] == node)
        else:
            excl[node] = False
        cur = float(base[excl & st.honest].sum())
    hon_w[last:end] = cur
    return dict(mode=mode, x=x, rho=rho, eps=eps, seed=seed, beta=float(base[byz].sum()),
                k_evade_x=evade_k(base, byz, x), honest_led=int(hl.sum()),
                acc_honest=float(acc[hl].mean()), acc_byz=float(acc[bl].mean()) if bl.any() else float("nan"),
                honest_convictions=hon_conv, false_conv_per_1000=1000.0 * hon_conv / max(1, int(hl.sum())),
                honest_excluded_w=float(hon_w[1:end].mean()), byz_convicted=len(byz_first), n_byz=int(byz.sum()),
                views_to_conviction=float(np.mean(list(byz_first.values()))) if byz_first else float("nan"),
                colluder_lead_late=float(np.mean(st.byz[st.leaders[VIEWS // 2:end]])),
                qc_rate=float(np.mean(st.qc_exists[100:end])))


def run():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    jobs = [("frame", x, r, e, s) for x in XS for r in RHOS for e in EPS_FRAME for s in range(SEEDS)]
    jobs += [(m, x, r, e, s) for m in ("silent", "targeted") for x in XS for r in RHOS for e in EPS_DETECT
             for s in range(SEEDS)]
    with Pool(PROCS) as pool:
        rows = pool.map(job, jobs, chunksize=1)
    with open(os.path.join(OUT, "dirTtru_tune.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    lines = [f"# AT 门槛 x 与 CUSUM ρ̄ 联合扫描（每格 {SEEDS} 个人群，{VIEWS} 视图；q={Q_POST}，h=ln 1e4）\n"]
    P = lines.append
    P("CUSUM 漂移转正的指控率 p*(ρ̄)：" + "，".join(f"ρ̄={r}: {p_star(r):.3f}" for r in RHOS) + "\n")
    k = {x: np.mean([r["k_evade_x"] for r in rows if r["mode"] == "frame" and r["x"] == x and r["eps"] == 0
                     and r["rho"] == RHOS[0]]) for x in XS}
    P("GST 后规避 AT 所需的最重诚实接收者数（人群平均）：" + "，".join(f"x={x:.3f}: {k[x]:.1f}" for x in XS) + "\n")
    P("\n## 陷害（同伙谎报 NR=1）+ 迟到：诚实领导视图被指控率 / 每千个诚实领导视图的误定罪 / 平均被排除的诚实权重\n")
    P("| x | ρ̄ | " + " | ".join(f"ε={e}" for e in EPS_FRAME) + " |")
    P("|---|---|" + "---|" * len(EPS_FRAME))
    for x in XS:
        for r in RHOS:
            cells = []
            for e in EPS_FRAME:
                g = [o for o in rows if (o["mode"], o["x"], o["rho"], o["eps"]) == ("frame", x, r, e)]
                cells.append(f"{np.mean([o['acc_honest'] for o in g]):.4f} / {np.mean([o['false_conv_per_1000'] for o in g]):.2f}"
                             f" / {np.mean([o['honest_excluded_w'] for o in g]):.3f}")
            P(f"| {x:.3f} | {r} | " + " | ".join(cells) + " |")
    for m, label in (("silent", "沉默领导者"), ("targeted", "定向部分发送（按 2/3 门槛可规避的接收者数）")):
        P(f"\n## {label}：同伙被指控率 / 被定罪同伙比例 / 定罪前领导次数 / 后半段同伙领导份额\n")
        P("| x | ρ̄ | " + " | ".join(f"ε={e}" for e in EPS_DETECT) + " |")
        P("|---|---|" + "---|" * len(EPS_DETECT))
        for x in XS:
            for r in RHOS:
                cells = []
                for e in EPS_DETECT:
                    g = [o for o in rows if (o["mode"], o["x"], o["rho"], o["eps"]) == (m, x, r, e)]
                    cells.append(f"{np.nanmean([o['acc_byz'] for o in g]):.2f} / "
                                 f"{np.mean([o['byz_convicted'] / o['n_byz'] for o in g]):.2f} / "
                                 f"{np.nanmean([o['views_to_conviction'] for o in g]) if any(o['byz_convicted'] for o in g) else float('nan'):.1f} / "
                                 f"{np.mean([o['colluder_lead_late'] for o in g]):.3f}")
                P(f"| {x:.3f} | {r} | " + " | ".join(cells) + " |")
    P(f"\nwall {time.time() - t0:.0f}s")
    with open(os.path.join(OUT, "dirTtru_tune.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def run_beta():
    """Sample-size and colluder-share check of the recommended x = 2/3 (review exp #10): 24 populations per
    cell, colluder base share ~0.24 or ~0.29, framing plus late messages."""
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    seeds = 3 * SEEDS
    xs, eps_l = (0.5, 0.6, 2 / 3), (0.1, 0.2, 0.3)
    jobs = [("frame", x, r, e, s, t) for t in (0.2, 0.27) for x in xs for r in RHOS for e in eps_l for s in range(seeds)]
    with Pool(PROCS) as pool:
        rows = pool.map(job, jobs, chunksize=1)
    for o, j in zip(rows, jobs):
        o["target"] = j[5]
    with open(os.path.join(OUT, "dirTtru_tune_beta.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    L = [f"# AT 门槛 x 与 CUSUM ρ̄：样本量与同伙份额（每格 {seeds} 个人群，{VIEWS} 视图；陷害 + 迟到）\n",
         "每格：诚实硬误定罪总数 / 出现误定罪的人群数 / 诚实领导视图被指控率\n"]
    for t in (0.2, 0.27):
        beta = np.mean([o["beta"] for o in rows if o["target"] == t])
        L += [f"\n## 同伙基础份额约 {beta:.2f}\n", "| x | ρ̄ | " + " | ".join(f"ε={e}" for e in eps_l) + " |",
              "|---|---|" + "---|" * len(eps_l)]
        for x in xs:
            for r in RHOS:
                cells = []
                for e in eps_l:
                    g = [o for o in rows if (o["target"], o["x"], o["rho"], o["eps"]) == (t, x, r, e)]
                    cells.append(f"{sum(o['honest_convictions'] for o in g)} / {sum(o['honest_convictions'] > 0 for o in g)} / "
                                 f"{np.mean([o['acc_honest'] for o in g]):.4f}")
                L.append(f"| {x:.3f} | {r} | " + " | ".join(cells) + " |")
    L.append(f"\nwall {time.time() - t0:.0f}s")
    with open(os.path.join(OUT, "dirTtru_tune_beta.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


def run_x():
    jobs = [("targeted_x", x, 0.03, e, s) for x in XS for e in (0.0, 0.1) for s in range(SEEDS)]
    with Pool(PROCS) as pool:
        rows = pool.map(job, jobs, chunksize=1)
    with open(os.path.join(OUT, "dirTtru_tune_x.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    lines = ["| x | ε | 接收者数 k | 接收者份额 ≥ 1−β−x | 同伙被指控率 | 被定罪同伙比例 | 后半段同伙领导份额 | QC 率 |",
             "|---|---|---|---|---|---|---|---|"]
    for x in XS:
        for e in (0.0, 0.1):
            g = [o for o in rows if o["x"] == x and o["eps"] == e]
            m = lambda c: float(np.nanmean([o[c] for o in g]))
            lines.append(f"| {x:.3f} | {e} | {m('k_evade_x'):.1f} | {1 - m('beta') - x:.3f} | {m('acc_byz'):.3f} | "
                         f"{np.mean([o['byz_convicted'] / o['n_byz'] for o in g]):.2f} | {m('colluder_lead_late'):.3f} | "
                         f"{m('qc_rate'):.3f} |")
    with open(os.path.join(OUT, "dirTtru_tune_x.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


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
    rows = list(csv.DictReader(open(os.path.join(OUT, "dirTtru_tune.csv"))))
    for o in rows:
        for k_ in ("x", "rho", "eps", "acc_honest", "false_conv_per_1000", "acc_byz", "views_to_conviction",
                   "byz_convicted", "n_byz", "colluder_lead_late"):
            o[k_] = float(o[k_])
    xs = sorted({o["x"] for o in rows})
    rhos = sorted({o["rho"] for o in rows})
    col = dict(zip(xs, ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")))
    lab = {x: f"x = {x:.2f}" if abs(x - 2 / 3) > 1e-9 else "x = 2/3" for x in xs}

    def mean(mode, x, r, e, key):
        g = [o[key] for o in rows if o["mode"] == mode and o["x"] == x and o["rho"] == r and o["eps"] == e]
        return float(np.nanmean(g)) if g else float("nan")

    fig, ax = plt.subplots(1, 1 + len(rhos), figsize=(4.2 * (1 + len(rhos)), 4.2))
    eps = sorted({o["eps"] for o in rows if o["mode"] == "frame"})
    a0 = ax[0]
    for x in xs:
        y = [mean("frame", x, rhos[0], e, "acc_honest") for e in eps]
        a0.plot(eps, np.maximum(y, 1e-5), color=col[x], lw=2, marker="o", ms=4, label=lab[x])
    for r, ls in zip(rhos, (":", "--", "-.")):
        a0.axhline(p_star(r), color="#555", lw=1, ls=ls, label=rf"p* ($\bar\rho$={r}) = {p_star(r):.2f}")
    a0.set_yscale("log")
    a0.set_ylim(1e-5, 1)
    a0.set_xlabel("消息迟到率 ε")
    a0.set_ylabel("诚实领导视图被 AT 指控的比例（对数轴；0 画在底边）")
    a0.set_title("陷害 + 迟到：AT 误指控率\n灰线为 CUSUM 漂移转正的指控率 p*", fontsize=9)
    a0.legend(fontsize=7, frameon=False, loc="lower right", ncol=2)
    a0.grid(alpha=0.25, lw=0.5)
    for a, r in zip(ax[1:], rhos):
        for x in xs:
            y = [mean("frame", x, r, e, "false_conv_per_1000") for e in eps]
            a.plot(eps, y, color=col[x], lw=2, marker="o", ms=4, label=lab[x])
        a.set_xlabel("消息迟到率 ε")
        a.set_ylabel("每千个诚实领导视图的误定罪次数")
        a.set_title(rf"$\bar\rho$ = {r}：每千个诚实领导视图的误定罪", fontsize=9)
        a.grid(alpha=0.25, lw=0.5)
        a.legend(fontsize=8, frameon=False, loc="upper left")
    ymax = max(a.get_ylim()[1] for a in ax[1:])
    for a in ax[1:]:
        a.set_ylim(-0.02 * ymax, ymax)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_at_tune.png"), dpi=160, bbox_inches="tight")


if __name__ == "__main__":
    {"plot": plot, "run_x": run_x, "run_beta": run_beta}.get(sys.argv[1] if len(sys.argv) > 1 else "run", run)()

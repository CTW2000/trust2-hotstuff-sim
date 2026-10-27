"""Where does T_tru cost more to corrupt than pure stake? (信任2.0, v0.2 after review 信任2.0_区域图与加权_审查)

Abstract population model only. A node's cost is what it loses when proven guilty of a SAFETY attack
(G1 evidence: equivocation): V_i = stake_i + pi*K for licensed entities (pi = probability that the
license penalty is enforced). The minimum cost of controlling theta = 1/3 of the voting weight by
corrupting existing nodes is an exact 0/1 knapsack (ttru_sim.bribe_exact, a lower bound within 1%).
Liveness attacks (silence) leave no G1 evidence and are NOT priced here.

Weightings (all with the same cost V):
  stake        w ~ stake
  value_prop   w ~ V, no cap: maximises the fractional minimum cost (lemma in 信任2.0_协议级验证 §2:
               for any weights the cheapest theta of weight costs at most theta * sum V)
  ttru         CapNorm(V) per class: uncertified class at most u_max, per-entity cap
  one_node     1:1
With a common pi, ttru depends on K and pi only through pi*K, so the scan runs over pi*K and the
(K, pi) region is the area above the hyperbola pi = (pi*K)* / K.

Per population we keep the ratios C_ttru / C_stake and C_ttru / C_value_prop, whether pure stake has a
"whale" (one entity >= 1/3 of the stake), and Nakamoto coefficients (entities needed for 1/3 of the
weight). The break-even (pi*K)* is where the MEDIAN per-population ratio crosses 1 (bootstrap 95% CI).
Configurations: n31 (10 licensed, 12 uncertified, 9 small; cap 0.10) and n100 (20, 50, 30; cap 0.05),
u_max 0.25, Pareto stakes with tail alpha 1.16 and class bases 3 : 1 : 0.2; sensitivity in alpha,
class bases and u_max. Heterogeneous enforcement: two jurisdictions (half the licensed with pi = 1,
half with pi_lo), weights from the nominal K, from the average pi, or from each pi_i.

Run:  python ttru/ttru_region.py      (a few minutes on 8 processes)
Out:  results/region.csv, region_breakeven.csv, region_hetero.csv, region_tables.md, fig_region.png
"""
import csv
import os
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from ttru_sim import bribe_exact, cap_normalize  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "results")
THETA = 1 / 3
XS = np.round(np.arange(0.0, 0.2001, 0.0025), 4)            # pi*K grid
MAIN = {"n31": dict(n=(10, 12, 9), cap=0.10), "n100": dict(n=(20, 50, 30), cap=0.05)}
U_MAX, ALPHA, BASE = 0.25, 1.16, (3.0, 1.0, 0.2)
SEEDS, SEEDS_SENS, BOOT = 500, 300, 1000
PROCS = int(os.environ.get("SIM_PROCS", "8"))


def population(nL, nU, nA, seed, alpha=ALPHA, base=BASE):
    rng = np.random.default_rng([seed, 1])
    cls = np.array(["L"] * nL + ["U"] * nU + ["A"] * nA)
    b = np.where(cls == "L", base[0], np.where(cls == "U", base[1], base[2]))
    s = b * (1.0 + rng.pareto(alpha, cls.size))
    return cls, s / s.sum()


def ttru_base(cls, V, cap, u_max):
    unc = cls != "L"
    U = min(V[unc].sum() / V.sum(), u_max)
    w = np.zeros(len(V))
    w[~unc] = cap_normalize(V[~unc], cap, 1.0 - U)
    w[unc] = cap_normalize(V[unc], cap, U)
    return w


def nakamoto(w, theta=THETA):
    return int(np.searchsorted(np.cumsum(np.sort(w)[::-1]), theta - 1e-12) + 1)


def pop_job(args):
    """All pi*K points of one population: ratios, whale flag, Nakamoto coefficients."""
    (nL, nU, nA), cap, u_max, alpha, base, seed = args
    cls, s = population(nL, nU, nA, seed, alpha, base)
    lic = cls == "L"
    out = []
    for x in XS:
        V = s + np.where(lic, x, 0.0)
        wt = ttru_base(cls, V, cap, u_max)
        cs, cv, ct = (bribe_exact(w, V, THETA) for w in (s, V / V.sum(), wt))
        co = bribe_exact(np.full(len(s), 1 / len(s)), V, THETA)
        out.append(dict(x=float(x), ct_cs=ct / cs, ct_cv=ct / cv, ct_co=ct / co, cs=cs, ct=ct,
                        nak_s=nakamoto(s), nak_v=nakamoto(V / V.sum()), nak_t=nakamoto(wt),
                        max_s=float(s.max()), max_t=float(wt.max())))
    return dict(seed=seed, whale=bool(s.max() >= THETA), s_u=float(s[~lic].sum()), rows=out)


def run_config(pop_n, cap, u_max=U_MAX, alpha=ALPHA, base=BASE, seeds=SEEDS, pool=None):
    jobs = [(pop_n, cap, u_max, alpha, base, sd) for sd in range(seeds)]
    return pool.map(pop_job, jobs, chunksize=4)


def matrix(res, key):
    return np.array([[r[key] for r in p["rows"]] for p in res])


def crossing(curve):
    """First pi*K where the curve exceeds 1 (linear interpolation); nan if never."""
    above = np.flatnonzero(curve > 1.0)
    if not above.size:
        return float("nan")
    j = int(above[0])
    if j == 0:
        return float(XS[0])
    x0, x1, y0, y1 = XS[j - 1], XS[j], curve[j - 1], curve[j]
    return float(x0 + (1.0 - y0) * (x1 - x0) / (y1 - y0))


def breakeven(res, seed=0):
    R = matrix(res, "ct_cs")
    point = crossing(np.median(R, axis=0))
    rng = np.random.default_rng(seed)
    boot = [crossing(np.median(R[rng.integers(0, len(R), len(R))], axis=0)) for _ in range(BOOT)]
    lo, hi = np.nanpercentile(boot, [2.5, 97.5])
    mean_ratio = crossing(matrix(res, "ct").mean(0) / matrix(res, "cs").mean(0))
    nw = np.array([not p["whale"] for p in res])
    nonwhale = crossing(np.median(R[nw], axis=0)) if nw.any() else float("nan")
    return point, float(lo), float(hi), mean_ratio, nonwhale


def hetero_job(args):
    (nL, nU, nA), cap, K, pi_lo, seed = args
    cls, s = population(nL, nU, nA, seed)
    lic = cls == "L"
    pis = np.where(lic, np.where(np.arange(len(s)) % 2 == 0, 1.0, pi_lo), 0.0)
    V = s + pis * K
    cs = bribe_exact(s, V, THETA)
    out = {}
    for name, ph in (("nominal", np.where(lic, 1.0, 0.0)), ("average", np.where(lic, (1 + pi_lo) / 2, 0.0)),
                     ("per_entity", pis)):
        out[name] = bribe_exact(ttru_base(cls, s + ph * K, cap, U_MAX), V, THETA) / cs
    return out


def pct(a):
    return f"{np.median(a):.2f} [{np.percentile(a, 10):.2f}, {np.percentile(a, 90):.2f}]"


def main():
    os.makedirs(OUT, exist_ok=True)
    lines = []
    P = lines.append
    with Pool(PROCS) as pool:
        main_res = {name: run_config(c["n"], c["cap"], pool=pool) for name, c in MAIN.items()}
        rows = []
        for name, res in main_res.items():
            whale = np.array([p["whale"] for p in res])
            R, Rv, Ro = matrix(res, "ct_cs"), matrix(res, "ct_cv"), matrix(res, "ct_co")
            Ct, Cs = matrix(res, "ct"), matrix(res, "cs")
            for j, x in enumerate(XS):
                rows.append(dict(population=name, piK=float(x), median=float(np.median(R[:, j])),
                                 p10=float(np.percentile(R[:, j], 10)), p90=float(np.percentile(R[:, j], 90)),
                                 win=float(np.mean(R[:, j] > 1)), win_nonwhale=float(np.mean(R[~whale, j] > 1)),
                                 median_nonwhale=float(np.median(R[~whale, j])),
                                 median_whale=float(np.median(R[whale, j])) if whale.any() else float("nan"),
                                 vs_valueprop_median=float(np.median(Rv[:, j])), vs_valueprop_max=float(Rv[:, j].max()),
                                 vs_one_node_median=float(np.median(Ro[:, j])),
                                 mean_ratio=float(Ct[:, j].mean() / Cs[:, j].mean())))
        with open(os.path.join(OUT, "region.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

        P(f"# 区域扫描结果（每格 {SEEDS} 个人群；θ=1/3；成本 = 质押 + πK）\n")
        for name, res in main_res.items():
            whale = np.array([p["whale"] for p in res])
            P(f"\n## {name}：鲸鱼人群（纯质押下单体 ≥ 1/3）占 {whale.mean():.0%}\n")
            P("| πK | C_T/C_S 中位数 [10%, 90%] | T_tru 胜出比例 | 非鲸鱼人群胜出 | 鲸鱼人群中位数 | "
              "C_T/C_按价值成比例 中位数（最大） | C_T/C_1:1 中位数 | 均值之比 |")
            P("|---|---|---|---|---|---|---|---|")
            R, Rv, Ro = matrix(res, "ct_cs"), matrix(res, "ct_cv"), matrix(res, "ct_co")
            Ct, Cs = matrix(res, "ct"), matrix(res, "cs")
            for x in (0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.075, 0.1, 0.15, 0.2):
                j = int(np.argmin(np.abs(XS - x)))
                mw = f"{np.median(R[whale, j]):.2f}" if whale.any() else "—"
                P(f"| {x} | {pct(R[:, j])} | {np.mean(R[:, j] > 1):.0%} | {np.mean(R[~whale, j] > 1):.0%} | {mw} | "
                  f"{np.median(Rv[:, j]):.2f}（{Rv[:, j].max():.3f}） | {np.median(Ro[:, j]):.1f} | "
                  f"{Ct[:, j].mean() / Cs[:, j].mean():.2f} |")
            j = int(np.argmin(np.abs(XS - 0.05)))
            ns, nv, nt = (matrix(res, k)[:, j] for k in ("nak_s", "nak_v", "nak_t"))
            ms, mt = matrix(res, "max_s")[:, j], matrix(res, "max_t")[:, j]
            P(f"\n集中度（πK=0.05）：凑齐 1/3 权重所需实体数的中位数（只需 1 个实体的人群比例）："
              f"纯质押 {np.median(ns):.0f}（{np.mean(ns == 1):.0%}），按价值成比例 {np.median(nv):.0f}（{np.mean(nv == 1):.0%}），"
              f"T_tru {np.median(nt):.0f}（{np.mean(nt == 1):.0%}）。最大单体份额中位数：纯质押 {np.median(ms):.3f}"
              f"（最大 {ms.max():.3f}），T_tru {np.median(mt):.3f}（最大 {mt.max():.3f}）。\n")

        configs = [(name, c["n"], c["cap"], U_MAX, ALPHA, BASE, SEEDS) for name, c in MAIN.items()]
        for name, c in MAIN.items():
            for a in (1.5, 2.5):
                configs.append((name, c["n"], c["cap"], U_MAX, a, BASE, SEEDS_SENS))
            configs.append((name, c["n"], c["cap"], U_MAX, ALPHA, (2.0, 1.0, 0.2), SEEDS_SENS))
            configs.append((name, c["n"], c["cap"], 0.15, ALPHA, BASE, SEEDS_SENS))
        brows = []
        for name, n_, cap, um, a, b, sd in configs:
            res = main_res[name] if (um, a, b, sd) == (U_MAX, ALPHA, BASE, SEEDS) else \
                run_config(n_, cap, um, a, b, sd, pool)
            pt, lo, hi, mr, nw = breakeven(res)
            s_u = float(np.mean([p["s_u"] for p in res]))
            brows.append(dict(population=name, n_L=n_[0], cap=cap, u_max=um, alpha=a, base=":".join(map(str, b)),
                              seeds=sd, whale=float(np.mean([p["whale"] for p in res])), S_U=s_u,
                              piK_star=pt, ci_lo=lo, ci_hi=hi, piK_star_mean_ratio=mr, piK_star_nonwhale=nw,
                              pred_thin_tail=max(0.0, s_u - um) / n_[0]))
        with open(os.path.join(OUT, "region_breakeven.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(brows[0].keys()))
            w.writeheader()
            w.writerows(brows)
        P("\n## 持平点 (πK)*：C_T/C_S 的中位数越过 1 的位置\n")
        P("| 人群 | α | 类别基数 L:U:A | u_max | 鲸鱼人群 | 未认证质押份额 S_U | (πK)* [95% CI] | 非鲸鱼人群 (πK)* | "
          "均值之比的 (πK)* | 薄尾预测 (S_U−u_max)/n_L | n_L·(πK)* |")
        P("|---|---|---|---|---|---|---|---|---|---|---|")
        for r in brows:
            P(f"| {r['population']} | {r['alpha']} | {r['base']} | {r['u_max']} | {r['whale']:.0%} | {r['S_U']:.2f} | "
              f"{r['piK_star']:.3f} [{r['ci_lo']:.3f}, {r['ci_hi']:.3f}] | {r['piK_star_nonwhale']:.3f} | "
              f"{r['piK_star_mean_ratio']:.3f} | {r['pred_thin_tail']:.3f} | {r['n_L'] * r['piK_star']:.2f} |")

        hrows = []
        P("\n## 执行概率因法域而异：一半持牌机构 π=1，另一半 π=π_lo；C_T/C_S 中位数（胜出比例）\n")
        P("| 人群 | K | π_lo | 按名义 K 分配 | 按平均 π 分配 | 按各自 π_i 分配 |")
        P("|---|---|---|---|---|---|")
        for name, c in MAIN.items():
            for K in (0.05, 0.1, 0.2):
                for pi_lo in (0.0, 0.5):
                    out = pool.map(hetero_job, [(c["n"], c["cap"], K, pi_lo, sd) for sd in range(SEEDS_SENS)],
                                   chunksize=4)
                    cells = []
                    for k in ("nominal", "average", "per_entity"):
                        a_ = np.array([o[k] for o in out])
                        cells.append(f"{np.median(a_):.2f}（{np.mean(a_ > 1):.0%}）")
                        hrows.append(dict(population=name, K=K, pi_lo=pi_lo, weighting=k,
                                          median=float(np.median(a_)), win=float(np.mean(a_ > 1))))
                    P(f"| {name} | {K} | {pi_lo} | " + " | ".join(cells) + " |")
        with open(os.path.join(OUT, "region_hetero.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(hrows[0].keys()))
            w.writeheader()
            w.writerows(hrows)
    with open(os.path.join(OUT, "region_tables.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    figure(main_res, brows)
    return main_res, brows


def figure(main_res, brows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    f = "/System/Library/Fonts/STHeiti Medium.ttc"
    if os.path.exists(f):
        font_manager.fontManager.addfont(f)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    col = {"n31": "#2a78d6", "n100": "#eb6834"}
    lab = {"n31": "n=31（10 家持牌，上限 10%）", "n100": "n=100（20 家持牌，上限 5%）"}
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.5, 4.8))
    Ks = np.geomspace(0.005, 0.5, 400)
    for name in MAIN:
        r = next(b for b in brows if b["population"] == name and b["alpha"] == ALPHA and b["u_max"] == U_MAX
                 and b["base"] == ":".join(map(str, BASE)))
        a1.fill_between(Ks, np.minimum(r["ci_lo"] / Ks, 1.05), np.minimum(r["ci_hi"] / Ks, 1.05),
                        color=col[name], alpha=0.18, lw=0)
        a1.plot(Ks, np.where(r["piK_star"] / Ks <= 1.05, r["piK_star"] / Ks, np.nan), color=col[name], lw=2,
                label=f"{lab[name]}：πK* = {r['piK_star']:.3f}")
    a1.set_xscale("log")
    a1.set_xticks([0.01, 0.02, 0.05, 0.1, 0.2, 0.5], ["0.01", "0.02", "0.05", "0.1", "0.2", "0.5"])
    a1.set_ylim(0, 1.02)
    a1.set_xlim(0.005, 0.5)
    a1.set_xlabel("单张牌照价值 K（全网质押 = 1，对数轴）")
    a1.set_ylabel("执行概率 π")
    a1.set_title("曲线右上方：过半人群中 T_tru 的最低收买成本高于纯质押\n（曲线 π = πK*/K，阴影为 95% 置信带）", fontsize=10)
    a1.legend(fontsize=8, loc="upper right", frameon=False)
    a1.grid(alpha=0.25, lw=0.5)
    for name, res in main_res.items():
        R = matrix(res, "ct_cs")
        whale = np.array([p["whale"] for p in res])
        a2.fill_between(XS, np.percentile(R, 10, 0), np.percentile(R, 90, 0), color=col[name], alpha=0.15, lw=0)
        a2.plot(XS, np.median(R, 0), color=col[name], lw=2, label=f"{name} 相对纯质押：中位数（阴影 10%–90%）")
        a2.plot(XS, np.median(R[~whale], 0), color=col[name], lw=1.2, ls="--", label=f"{name} 相对纯质押：非鲸鱼人群中位数")
        a2.plot(XS, np.median(matrix(res, "ct_cv"), 0), color=col[name], lw=1.2, ls=":",
                label=f"{name} 相对按价值成比例（上限的代价）")
    a2.axhline(1, color="#555", lw=0.8)
    a2.set_yscale("log")
    a2.set_yticks([0.25, 0.5, 1, 2, 4], ["0.25", "0.5", "1", "2", "4"])
    a2.minorticks_off()
    a2.set_xlabel("每家持牌机构的可执行牌照价值 πK（全网质押 = 1）")
    a2.set_ylabel("最低收买成本之比 C_T / C_对照（对数轴）")
    a2.set_title("T_tru 的最低收买成本，逐个人群与对照比较", fontsize=10)
    a2.legend(fontsize=7, loc="lower right", frameon=True, framealpha=0.9, edgecolor="none")
    a2.grid(alpha=0.25, lw=0.5)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_region.png"), dpi=160, bbox_inches="tight")


if __name__ == "__main__":
    main()

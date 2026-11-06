"""Sensitivity of the recommended protocol to cap, u_max, B_rep and r_min (2026-11-05; the paper listed these four as
defaults without a sensitivity analysis). One parameter at a time around the defaults (cap 0.10, u_max 0.25,
B_rep 0.10, r_min 0.7); everything else is dirTtruV12 (formula A, gamma = ttru.GAMMA), n = 31 (10 licensed,
12 uncertified, 9 small). Run it under the adopted scheme (SIM_SCHEME=h1p).

Parts:
  static  500 populations per value of cap, u_max and B_rep, for n = 31 (cap 0.10) and for n = 100 (20 licensed,
          50 uncertified, 30 small; cap 0.05, the paper's default), base weights only: the uncertified share, the largest
          entity share, the fewest entities above 1/3, the least stake (share of all stake) whose base share exceeds
          the tolerable beta0 = (1 - B_rep)/3, and the fewest licensed entities in any coalition above (1 - B_rep)/3
          and above (1 - B_rep - L_max)/3, against the paper's floor((theta - u_max)/cap) + 1.
  silent  colluding silent leaders (target base share 0.2 / 0.25, no late messages): conviction, the colluders'
          voting share at the end against their base share, commit rate.
  chaos   GST at view 3000 of 5000 with the framing adversary (region outages, adversarial scheduling): honest cut
          against B_rep, colluder share against the bound beta0/(1 - B_rep), commit rate after GST + D.
  budget  framable evidence (failed proposer, P1 collector framing) against AT: whether the colluder share still
          reaches the bound exactly, and AT still cuts no honest weight.
  frame   colluders claim NR = 1 and withhold votes in honest views at 30% late messages (target 0.2 / 0.25):
          honest convictions and cut.
Environment: SIM_PROCS (default 8), SIM_SEEDS (default 50; chaos uses half); set SIM_SCHEME=h1p.
Run from the repository root:  python -m sim2.experiments.dirTtruSens [static|silent|chaos|budget|frame|all|report]
Out: results/dirTtru_sens_<part><suffix>.csv and results/dirTtru_sens<suffix>.md.
"""
import csv
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

from sim2 import ttru
from sim2.experiments import dirTtruV12 as V
from sim2.experiments.dirTtruReview import poisson_upper

DEFAULT = dict(cap=0.10, u_max=0.25, b_rep=0.10, r_min=0.7)
GRID = (("cap", (0.08, 0.10, 0.15, 0.20)),          # 10 licensed: cap >= (1 - u_max)/10 = 0.075
        ("u_max", (0.10, 0.15, 0.20, 0.25, 0.29)),  # u_max < (1 - B_rep)/3 = 0.30
        ("b_rep", (0.05, 0.10, 0.15, 0.20)),        # u_max = 0.25 < (1 - B_rep)/3 up to B_rep = 0.25
        ("r_min", (0.5, 0.6, 0.7, 0.8, 0.9)))
NAMES = dict(cap="cap", u_max="u_max", b_rep="B_rep", r_min="r_min")
STATIC_SEEDS = 500
# Static populations: (licensed, uncertified, small), default cap, cap values (n_L * cap >= 1 - u_max).
POPS = {"n31": ((10, 12, 9), 0.10, (0.08, 0.10, 0.15, 0.20)), "n100": ((20, 50, 30), 0.05, (0.04, 0.05, 0.075, 0.10))}


def grid(pop=None):
    """GRID with the cap values of a static population (the dynamic part runs n = 31)."""
    return tuple((k, POPS[pop][2] if (pop and k == "cap") else v) for k, v in GRID)


def default(pop=None):
    d = dict(DEFAULT)
    if pop:
        d["cap"] = POPS[pop][1]
    return d


def cells(pop=None):
    """(key, value) per run cell: the defaults once, then every other value of each parameter (r_min does not change
    base weights, so the static part, pop given, leaves it out)."""
    out = [("default", 0.0)]
    for key, vals in grid(pop):
        if pop and key == "r_min":
            continue
        out += [(key, v) for v in vals if v != default(pop)[key]]
    return out


def set_params(key, val, pop=None):
    """Set the module constants of dirTtruV12 for one cell (a worker runs one job at a time)."""
    p = default(pop)
    if key != "default":
        p[key] = val
    V.CAP, V.UMAX, V.B_REP, V.R_MIN = p["cap"], p["u_max"], p["b_rep"], p["r_min"]
    return p


def tag(row, key, val, p):
    row.update(param=key, value=val, **{f"p_{k}": v for k, v in p.items()})
    return row


def min_licensed(base, lic, theta):
    """Fewest licensed entities in a coalition of base share > theta (all uncertified entities may join it)."""
    need = theta - float(base[~lic].sum())
    if need < 0:
        return 0
    cs = np.cumsum(np.sort(base[lic])[::-1])
    return int(np.argmax(cs > need + 1e-12)) + 1 if cs[-1] > need + 1e-12 else -1


def formula_licensed(theta, u_max, cap):
    """The paper's floor: floor((theta - u_max)/cap) + 1 licensed entities when theta > u_max."""
    return int(np.floor((theta - u_max) / cap + 1e-12)) + 1 if theta > u_max else 0


def static_job(args):
    pop, key, val, seed = args
    p = set_params(key, val, pop)
    cls, s = ttru.population(*POPS[pop][0], seed)
    base = ttru.base_weights(cls, s, 0.0, 0.0, p["cap"], p["u_max"])
    lic = cls == "L"
    theta, theta2 = (1 - p["b_rep"]) / 3, (1 - p["b_rep"] - V.L_MAX) / 3
    top = np.cumsum(np.sort(base)[::-1])
    return tag(dict(part="static", pop=pop, seed=seed, beta_tol=theta, unc_share=float(base[~lic].sum()),
                    max_share=float(base.max()), lic_max_share=float(base[lic].max()),
                    nakamoto=int(np.argmax(top > 1 / 3)) + 1,
                    stake_to_tol=V.min_deposit(base, s / s.sum(), theta),
                    lic_min=min_licensed(base, lic, theta), lic_formula=formula_licensed(theta, p["u_max"], p["cap"]),
                    lic_min_lmax=min_licensed(base, lic, theta2),
                    lic_formula_lmax=formula_licensed(theta2, p["u_max"], p["cap"])), key, val, p)


def job(args):
    part, key, val, rest = args
    p = set_params(key, val)
    fn = {"silent": V.silent_job, "chaos": V.chaos_job, "budget": V.budget_job, "frame": V.frame_job}[part]
    return tag(fn(rest), key, val, p)


def jobs_of(part):
    seeds, half = V.SEEDS, max(1, V.SEEDS // 2)
    if part == "static":
        return [(pop, k, v, s) for pop in POPS for k, v in cells(pop) for s in range(STATIC_SEEDS)]
    rest = dict(silent=[(tg, 0.0, False, s) for tg in (0.2, 0.25) for s in range(seeds)],
                chaos=[(nm, False, s) for nm in ("outage", "adv") for s in range(half)],
                budget=[(ev, s) for ev in ("failed", "at") for s in range(seeds)],
                frame=[(tg, 0.3, "base", s) for tg in (0.2, 0.25) for s in range(seeds)])[part]
    return [(part, k, v, r) for k, v in cells() for r in rest]


def name(part):
    return os.path.join(V.OUT, f"dirTtru_sens_{part}{ttru.suffix()}.csv")


def run(part):
    t0 = time.time()
    with Pool(V.PROCS) as pool:
        rows = pool.map(static_job if part == "static" else job, jobs_of(part), chunksize=8 if part == "static" else 1)
    with open(name(part), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r}))
        w.writeheader()
        w.writerows(rows)
    print(f"{part}: {len(rows)} runs, {time.time() - t0:.0f}s", flush=True)


def load(part):
    if not os.path.exists(name(part)):
        return []
    rows = list(csv.DictReader(open(name(part))))
    for r in rows:
        for k, v in r.items():
            try:
                r[k] = float(v)
            except ValueError:
                pass
    return rows


def groups(rows, pop=None):
    """(key, value, rows) for every value of every parameter, the default rows standing in for the default value."""
    out = []
    for key, vals in grid(pop):
        if pop and key == "r_min":
            continue
        for v in vals:
            grp = [r for r in rows if (pop is None or r["pop"] == pop) and (r["param"], r["value"]) ==
                   ((key, v) if v != default(pop)[key] else ("default", 0.0))]
            if grp:
                out.append((key, v, grp))
    return out


def q(xs, f=np.median, d=3):
    return f"{f(xs):.{d}f}"


def report():
    L = ["# cap、u_max、B_rep、r_min 的敏感性\n",
         "每次只改一个参数，其余取默认值（cap 0.10、u_max 0.25、B_rep 0.10、r_min 0.7）；其余同 dirTtruV12（公式 A、"
         "γ = 10²、按本文交接规则），n = 31（10 家持牌、12 家未认证、9 个小节点）。加粗行为默认值。\n"]
    st = load("static")
    for pop in POPS if st else ():
        nl, nu, na = POPS[pop][0]
        L += [f"## 基础权重：n = {nl + nu + na}（{nl} 家持牌、{nu} 家未认证、{na} 个小节点；cap 默认 {POPS[pop][1]:g}；静态，每个取值 500 个人群）\n",
              "可容忍 β0 = (1 − B_rep)/3。“至少要多少质押”：基础份额超过可容忍 β0 的最便宜实体集合占全部质押的比例（中位数，"
              "括号为 5%–95% 分位）；不封顶、按质押计票时这个比例就等于可容忍 β0。“罪犯中至少几家持牌”：基础份额超过阈值的任何集合"
              "至少含几家持牌实体，公式 ⌊(θ − u_max)/cap⌋ + 1 / 500 个人群中的最少值；θ 取 (1 − B_rep)/3，计入 L_max 时取 "
              "(1 − B_rep − L_max)/3。\n",
              "| 参数 | 取值 | 可容忍 β0 | 未认证类份额 | 单实体最大份额 | 超过 1/3 至少几个实体 | 至少要多少质押 | "
              "罪犯中至少几家持牌：公式 / 实测 | 计入 L_max 时 |", "|---|---|---|---|---|---|---|---|---|"]
        for key, v, g in groups(st, pop):
            b = "**" if v == default(pop)[key] else ""
            stake = [r["stake_to_tol"] for r in g]
            L.append(f"| {b}{NAMES[key]}{b} | {b}{v:g}{b} | {g[0]['beta_tol']:.3f} | {q([r['unc_share'] for r in g])} | "
                     f"{q([r['max_share'] for r in g], np.max)} | {q([r['nakamoto'] for r in g], d=0)} | "
                     f"{np.median(stake):.3f}（{np.quantile(stake, 0.05):.3f}–{np.quantile(stake, 0.95):.3f}） | "
                     f"{int(g[0]['lic_formula'])} / {int(min(r['lic_min'] for r in g))} | "
                     f"{int(g[0]['lic_formula_lmax'])} / {int(min(r['lic_min_lmax'] for r in g))} |")
    sl, ch, bu, fr = load("silent"), load("chaos"), load("budget"), load("frame")
    if sl or ch or bu or fr:
        L += ["\n## 协议级（每格：沉默与陷害 2 × 50 个人群，混乱期 2 × 25，预算 2 × 50）\n",
              "沉默：同伙为沉默领导者，基础份额约 0.2 / 0.25，无迟到，2000 个视图；“末尾份额 / 基础份额”为最后三张表里同伙投票份额与其"
              "基础份额之比（中位数）。混乱期：GST 在视图 3000（共 5000），对抗调度与区域故障两种网络合并；“越界最大”= 同伙份额最大 − "
              "β0/(1 − B_rep)，≤ 0 表示没有越界。预算：可陷害证据（提案失败）下同伙份额最大与界之差（均值 / 最大），AT 下诚实被降权最大。"
              "陷害：30% 迟到，同伙谎报 NR 并扣票。\n",
              "| 参数 | 取值 | 沉默：同伙被定罪比例 | 沉默：末尾份额 / 基础份额 | 沉默：提交比例 | 混乱期：诚实降权最大 / B_rep | "
              "混乱期：越界最大 | 混乱期：GST 后提交比例 | 预算：可陷害证据 份额 − 界（均值 / 最大） | 预算：AT 诚实降权最大 | "
              "陷害 30%：诚实定罪 / 千视图（95% 上界） | 陷害 30%：诚实降权最大 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for key, vals in GRID:
            for v in vals:
                sel = lambda rows: [r for r in rows if (r["param"], r["value"]) ==
                                    ((key, v) if v != DEFAULT[key] else ("default", 0.0))]
                s_, c_, b_, f_ = sel(sl), sel(ch), sel(bu), sel(fr)
                if not (s_ or c_ or b_ or f_):
                    continue
                b = "**" if v == DEFAULT[key] else ""
                cells_ = [f"{b}{NAMES[key]}{b}", f"{b}{v:g}{b}"]
                cells_ += [q([r["byz_convicted"] for r in s_], np.mean), q([r["colluder_share_end"] / r["beta"] for r in s_]),
                           q([r["commit"] for r in s_], np.mean)] if s_ else ["—"] * 3
                if c_:
                    br = c_[0]["p_b_rep"]
                    cells_ += [f"{max(r['honest_cut_max'] for r in c_):.3f} / {br:.2f}",
                               f"{max(r['colluder_share_max'] - r['bound'] for r in c_):+.4f}",
                               q([r["commit_post"] for r in c_], np.mean)]
                else:
                    cells_ += ["—"] * 3
                fa = [r for r in b_ if r["evidence"] == "failed"]
                at = [r for r in b_ if r["evidence"] == "at"]
                cells_ += [f"{np.mean([r['colluder_share_max'] - r['bound'] for r in fa]):+.4f} / "
                           f"{max(r['colluder_share_max'] - r['bound'] for r in fa):+.4f}" if fa else "—",
                           f"{max(r['honest_cut_max'] for r in at):.3f}" if at else "—"]
                if f_:
                    tc, tv = sum(r["honest_conv"] for r in f_), sum(r["honest_led"] for r in f_)
                    cells_ += [f"{1000 * tc / tv:.3f}（≤ {1000 * poisson_upper(int(tc)) / tv:.3f}）",
                               f"{max(r['honest_cut_max'] for r in f_):.4f}"]
                else:
                    cells_ += ["—"] * 2
                L.append("| " + " | ".join(cells_) + " |")
    with open(os.path.join(V.OUT, f"dirTtru_sens{ttru.suffix()}.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which == "report":
        report()
    else:
        for part in (("static", "silent", "chaos", "budget", "frame") if which == "all" else (which,)):
            run(part)
        report()

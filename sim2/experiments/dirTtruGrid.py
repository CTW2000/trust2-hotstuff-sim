"""Two-dimensional sweep of the weight parameters (prototype DESIGN.md §15.21; the mock review's A8): where a culprit
coalition must contain licensed entities, and what the cap costs in stake. dirTtruSens moved one parameter at a time
around the simulator's n = 31 defaults (cap 0.10); this script sweeps pairs and adds the paper's n = 100 default
(cap 0.05) to the dynamic runs as well.

Parts:
  static  base weights only, 200 populations per cell, for n = 31 (10 licensed, 12 uncertified, 9 small) and n = 100
          (20 / 50 / 30): cap x u_max at B_rep = 0.10, and B_rep x u_max at the default cap. Per cell: the fewest
          licensed entities in any coalition above theta = (1 - B_rep)/3 and above theta' = (1 - B_rep - L_max)/3 (the
          worst of the populations) against the paper's floor((theta - u_max)/cap_eff) + 1, where cap_eff =
          max(cap, (1 - u_max)/n_L) is the cap CapNorm can meet; and the least stake whose base share exceeds theta.
  n100    the dynamic claims at the paper's default (n = 100, cap 0.05, u_max 0.25, B_rep 0.10, r_min 0.7): silent
          colluding leaders (target 0.2 / 0.25) and framing at 30% late messages, 10 seeds each.
Environment: SIM_PROCS (default 8); set SIM_SCHEME=h1p. Run from the repository root:
    SIM_SCHEME=h1p python -m sim2.experiments.dirTtruGrid [static|n100|all|report]
Out: results/dirTtru_grid_<part><suffix>.csv and results/dirTtru_grid<suffix>.md."""
import csv
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

from sim2 import ttru
from sim2.experiments import dirTtruSens as T
from sim2.experiments import dirTtruV12 as V

POPS = {"n31": ((10, 12, 9), 0.10), "n100": ((20, 50, 30), 0.05)}
CAPS = {"n31": (0.075, 0.10, 0.15, 0.20), "n100": (0.03, 0.04, 0.05, 0.075, 0.10, 0.15)}
U_MAX = (0.05, 0.10, 0.15, 0.20, 0.25, 0.27, 0.29)
B_REP = (0.0, 0.05, 0.10, 0.15, 0.20)
STATIC_SEEDS = 200
N100_SEEDS = 10


def static_cells():
    out = []
    for pop, (_, cap0) in POPS.items():
        out += [(pop, "cap_umax", cap, u, 0.10) for cap in CAPS[pop] for u in U_MAX]
        out += [(pop, "brep_umax", cap0, u, b) for b in B_REP for u in U_MAX if u < (1 - b) / 3]
    return out


def static_job(args):
    pop, plane, cap, u_max, b_rep, seed = args
    (nl, nu, na), _ = POPS[pop]
    cls, s = ttru.population(nl, nu, na, seed)
    base = ttru.base_weights(cls, s, 0.0, 0.0, cap, u_max)
    lic = cls == "L"
    unc = float(base[~lic].sum())
    cap_eff = max(cap, (1 - unc) / nl)
    theta, theta2 = (1 - b_rep) / 3, (1 - b_rep - V.L_MAX) / 3
    return dict(part="static", pop=pop, plane=plane, cap=cap, u_max=u_max, b_rep=b_rep, seed=seed, unc_share=unc,
                cap_eff=cap_eff, lic_max_share=float(base[lic].max()),
                lic_min=T.min_licensed(base, lic, theta), lic_formula=T.formula_licensed(theta, u_max, cap_eff),
                lic_min_lmax=T.min_licensed(base, lic, theta2),
                lic_formula_lmax=T.formula_licensed(theta2, u_max, cap_eff),
                stake_to_tol=V.min_deposit(base, s / s.sum(), theta))


def n100_job(args):
    part, rest = args
    V.N, V.NL, V.NU, V.NA = 100, 20, 50, 30
    V.CAP, V.UMAX, V.B_REP, V.R_MIN = 0.05, 0.25, 0.10, 0.7
    row = (V.silent_job if part == "silent" else V.frame_job)(rest)
    row.update(pop="n100", cap=0.05)
    return row


def jobs_of(part):
    if part == "static":
        return [c + (s,) for c in static_cells() for s in range(STATIC_SEEDS)]
    return ([("silent", (tg, 0.0, False, s)) for tg in (0.2, 0.25) for s in range(N100_SEEDS)] +
            [("frame", (tg, 0.3, "base", s)) for tg in (0.2, 0.25) for s in range(N100_SEEDS)])


def name(part):
    return os.path.join(V.OUT, f"dirTtru_grid_{part}{ttru.suffix()}.csv")


def run(part):
    t0 = time.time()
    with Pool(V.PROCS) as pool:
        rows = pool.map(static_job if part == "static" else n100_job, jobs_of(part),
                        chunksize=16 if part == "static" else 1)
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


def cell(rows, pop, plane, cap, u_max, b_rep):
    return [r for r in rows if r["pop"] == pop and r["plane"] == plane and abs(r["cap"] - cap) < 1e-9 and
            abs(r["u_max"] - u_max) < 1e-9 and abs(r["b_rep"] - b_rep) < 1e-9]


def show(g):
    """worst licensed count above theta (formula) / worst above theta' / median stake to theta; '-' when the
    uncertified class alone can exceed theta (u_max >= theta)."""
    if not g:
        return ""
    lm, lf = min(r["lic_min"] for r in g), g[0]["lic_formula"]
    l2, f2 = min(r["lic_min_lmax"] for r in g), g[0]["lic_formula_lmax"]
    eff = max(r["cap_eff"] for r in g)
    mark = "*" if eff > g[0]["cap"] + 1e-9 else ""
    stake = np.median([r["stake_to_tol"] for r in g])
    a = f"{lm:.0f} ({lf:.0f})" if lm >= 0 else "-"
    b = f"{l2:.0f} ({f2:.0f})" if l2 >= 0 else "-"
    return f"{a} / {b} / {stake:.3f}{mark}"


def report():
    rows = load("static")
    L = ["# 权重参数的二维扫描\n",
         "每格：任一份额超过 θ = (1 − B_rep)/3 的联盟至少含几家持牌实体（200 个人群中的最坏值，括号内为公式 "
         "⌊(θ − u_max)/cap_eff⌋ + 1）/ 计入 L_max 时 θ' = (1 − B_rep − L_max)/3 的同一数 / 使基础份额超过 θ 所需的"
         "最少质押占比（中位数）。cap_eff = max(cap, (1 − u_max)/n_L)：持牌家数太少时 CapNorm 只能放宽 cap，带 * 的格子"
         "即放宽过。0 表示未认证类单独即可越线（u_max ≥ θ）。按质押直接计票时最后一项为 θ 本身。\n"]
    for pop, ((nl, nu, na), cap0) in POPS.items():
        L += [f"## n = {nl + nu + na}（{nl} 家持牌、{nu} 家未认证、{na} 个小节点）\n",
              "### cap × u_max（B_rep = 0.10）\n", "| cap \\ u_max | " + " | ".join(f"{u:g}" for u in U_MAX) + " |",
              "|---|" + "---|" * len(U_MAX)]
        for cap in CAPS[pop]:
            L.append(f"| {cap:g} | " + " | ".join(show(cell(rows, pop, "cap_umax", cap, u, 0.10)) for u in U_MAX) + " |")
        L += ["", f"### B_rep × u_max（cap = {cap0:g}）\n",
              "| B_rep \\ u_max | " + " | ".join(f"{u:g}" for u in U_MAX) + " |", "|---|" + "---|" * len(U_MAX)]
        for b in B_REP:
            L.append(f"| {b:g} | " + " | ".join(show(cell(rows, pop, "brep_umax", cap0, u, b)) for u in U_MAX) + " |")
        L.append("")
    if rows:
        bad = [r for r in rows if r["lic_min"] >= 0 and r["lic_min"] < r["lic_formula"]]
        bad2 = [r for r in rows if r["lic_min_lmax"] >= 0 and r["lic_min_lmax"] < r["lic_formula_lmax"]]
        tight = sum(1 for c in static_cells() if (g := cell(rows, *c)) and min(r["lic_min"] for r in g) == g[0]["lic_formula"])
        L += ["## 公式是否成立\n",
              f"- 人群中持牌家数少于公式的：θ 下 {len(bad)} 个、θ' 下 {len(bad2)} 个（共 {len(rows)} 个人群）。",
              f"- 最坏值恰好等于公式（紧）的格子：{tight} / {len(static_cells())}。\n"]
    dyn = load("n100")
    if dyn:
        L += ["## 论文默认参数下的动态结果（n = 100、cap 0.05、u_max 0.25、B_rep 0.10、r_min 0.7）\n",
              "| 场景 | 目标份额 | 运行数 | 合谋者基础份额（中位数） | 末段份额 / 上界 β/(1 − B_rep)（最大比值） | "
              "诚实定罪 | 诚实削减最大值 | 合谋者全部被定罪的比例 |", "|---|---|---|---|---|---|---|---|"]
        for part in ("silent", "frame"):
            for tg in (0.2, 0.25):
                g = [r for r in dyn if r["part"] == part and abs(r["target"] - tg) < 1e-9]
                if not g:
                    continue
                ratio = max(r["colluder_share_max"] / r["bound"] for r in g)
                conv = sum(r.get("honest_conv", 0) or 0 for r in g)
                byz = np.mean([r["byz_convicted"] == 1 for r in g]) if part == "silent" else float("nan")
                L.append(f"| {'沉默领导者' if part == 'silent' else '陷害（30% 迟到）'} | {tg:g} | {len(g)} | "
                         f"{np.median([r['beta'] for r in g]):.3f} | {ratio:.3f} | {conv:.0f} | "
                         f"{max(r['honest_cut_max'] for r in g):.4f} | {'' if np.isnan(byz) else f'{byz:.2f}'} |")
        L.append("")
    path = os.path.join(V.OUT, f"dirTtru_grid{ttru.suffix()}.md")
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")
    print(path)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what == "report":
        report()
    else:
        for part in (("static", "n100") if what == "all" else (what,)):
            run(part)
        report()

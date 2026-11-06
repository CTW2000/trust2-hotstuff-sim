"""Threshold sweep of the G2 CUSUM (2026-11-04, after the prototype comparison of leader rules, prototype/DESIGN.md
§15.12): how much faster silent leaders are convicted at a lower threshold h = ln(gamma), and what it costs the
honest replicas. With q = 0.5 and rho_bar = 0.1 a run of bad facts convicts after 6, 5, 3, 2 and 1 leads for the
gammas below (10^4 was the recommended protocol; 10^2 since 2026-11-05, ttru.GAMMA). The sweep sets h itself. Everything else is dirTtruV12 under the adopted scheme:
  silent   colluding leaders send nothing (target 0.2 / 0.25, eps 0 / 0.1, doubling off);
  frame    colluders claim NR = 1 and withhold votes in honest views, late messages eps 0.1 / 0.2 / 0.3, base
           network only (the wide network gives the same results);
  chaos    GST at view 3000 of 5000 with the framing adversary (iid, outage, adv), doubling off.
Environment: SIM_PROCS (default 8), SIM_SEEDS (default 50; chaos uses half); set SIM_SCHEME=h1p.
Run from the repository root:  python -m sim2.experiments.dirTtruGamma [silent|frame|chaos|all|report]
Out: results/dirTtru_gamma_<part><suffix>.csv and results/dirTtru_gamma<suffix>.md.
"""
import csv
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

from sim2 import ttru
from sim2.experiments import dirTtruV12 as V
from sim2.experiments.dirTtruReview import fmt, poisson_upper, wilson_upper

GAMMAS = (1e4, 1e3, 1e2, 20.0, 4.0)
UP = float(np.log(0.5 / 0.1))
_build = V.build


def leads(gamma):
    """Leads with a bad fact each that convict from a zero CUSUM."""
    return int(np.ceil(np.log(gamma) / UP))


def build_with(gamma):
    def build(*args, **kwargs):
        rule, vw = _build(*args, **kwargs)
        rule.h = float(np.log(gamma))
        return rule, vw
    return build


def job(args):
    part, gamma, rest = args
    V.build = build_with(gamma)          # the V12 jobs look up build at call time; one job per worker at a time
    row = {"silent": V.silent_job, "frame": V.frame_job, "chaos": V.chaos_job}[part](rest)
    row["gamma"] = gamma
    return row


def jobs_of(part):
    seeds, half = V.SEEDS, max(1, V.SEEDS // 2)
    if part == "silent":
        return [(part, g, (tg, e, False, s)) for g in GAMMAS for tg in (0.2, 0.25) for e in (0.0, 0.1) for s in range(seeds)]
    if part == "frame":
        return [(part, g, (tg, e, "base", s)) for g in GAMMAS for tg in (0.2, 0.25) for e in (0.1, 0.2, 0.3)
                for s in range(seeds)]
    return [(part, g, (nm, False, s)) for g in GAMMAS for nm in ("iid", "outage", "adv") for s in range(half)]


def name(part):
    return os.path.join(V.OUT, f"dirTtru_gamma_{part}{ttru.suffix()}.csv")


def run(part):
    t0 = time.time()
    with Pool(V.PROCS) as pool:
        rows = pool.map(job, jobs_of(part), chunksize=1)
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


def report():
    L = ["# G2 CUSUM 阈值扫描\n",
         "h = ln γ，q = 0.5、ρ̄ = 0.1 时连续坏事实在下列次数的领导后定罪；γ = 10⁴ 是推荐协议。其余同 dirTtruV12（公式 A、"
         "按本文交接规则），n = 31。区间为对人群的自助法 95% 区间。\n"]
    sl = load("silent")
    if sl:
        L += ["## 沉默领导者\n",
              "| γ | 连续坏事实几次定罪 | ε | 同伙被定罪比例 | 定罪前的领导次数 | 后半段同伙当领导者的比例 | 提交比例 | 诚实定罪 |",
              "|---|---|---|---|---|---|---|---|"]
        for g in GAMMAS:
            for e in (0.0, 0.1):
                grp = [r for r in sl if (r["gamma"], r["eps"]) == (g, e)]
                if grp:
                    L.append(f"| {g:g} | {leads(g)} | {e} | {fmt([r['byz_convicted'] for r in grp])} | "
                             f"{fmt([r['leads_to_conviction'] for r in grp], 1)} | {fmt([r['byz_lead_late'] for r in grp])} | "
                             f"{fmt([r['commit'] for r in grp])} | {int(sum(r['honest_conv'] for r in grp))} |")
    fr = load("frame")
    if fr:
        L += ["\n## 陷害加迟到（base 网络）\n",
              "| γ | ε | 诚实定罪 / 千个诚实领导视图（Poisson 95% 上界） | 出现诚实定罪的人群（上界） | 诚实被降权重最大 | "
              "同伙份额最大 / 单表界（最大超界） |", "|---|---|---|---|---|---|"]
        for g in GAMMAS:
            for e in (0.1, 0.2, 0.3):
                grp = [r for r in fr if (r["gamma"], r["eps"]) == (g, e)]
                if not grp:
                    continue
                k = sum(r["honest_conv"] > 0 for r in grp)
                tc, tv = sum(r["honest_conv"] for r in grp), sum(r["honest_led"] for r in grp)
                over = max(r["colluder_share_max"] - r["bound"] for r in grp)
                L.append(f"| {g:g} | {e} | {1000 * tc / tv:.3f}（≤ {1000 * poisson_upper(int(tc)) / tv:.3f}） | "
                         f"{k}/{len(grp)}（{wilson_upper(k, len(grp)):.3f}） | {fmt([r['honest_cut_max'] for r in grp])} | "
                         f"{V.m(grp, 'colluder_share_max')} / {V.m(grp, 'bound')}（{over:+.4f}） |")
    ch = load("chaos")
    if ch:
        L += ["\n## GST 之前的混乱期（GST = 视图 3000，共 5000 视图，同伙陷害）\n",
              "| γ | 混乱期网络 | 诚实定罪：GST 前 / 后 | 诚实被降权重最大 | 同伙份额最大 / 单表界（最大超界） | GST+D 后提交比例 |",
              "|---|---|---|---|---|---|"]
        for g in GAMMAS:
            for nm in ("iid", "outage", "adv"):
                grp = [r for r in ch if (r["gamma"], r["net"]) == (g, nm)]
                if grp:
                    over = max(r["colluder_share_max"] - r["bound"] for r in grp)
                    L.append(f"| {g:g} | {nm} | {int(sum(r['honest_conv_pre'] for r in grp))} / "
                             f"{int(sum(r['honest_conv_post'] for r in grp))} | {fmt([r['honest_cut_max'] for r in grp])} | "
                             f"{V.m(grp, 'colluder_share_max')} / {V.m(grp, 'bound')}（{over:+.4f}） | "
                             f"{fmt([r['commit_post'] for r in grp])} |")
    with open(os.path.join(V.OUT, f"dirTtru_gamma{ttru.suffix()}.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which == "report":
        report()
    else:
        for part in (("silent", "frame", "chaos") if which == "all" else (which,)):
            run(part)
        report()

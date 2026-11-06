"""Ablation of reputation in the voting power (prototype DESIGN.md §15.18; the mock review's A3): what lowering r
adds to excluding a convicted leader from leading. The cells of dirTtruSens with B_rep = 0 (convictions still exclude,
nothing is cut from the voting power) on the same seeds as its default cell (B_rep = 0.10), so the two compare run by
run: silent leaders, the pre-GST chaos with framing, framing at 30% late, and the framable-evidence budget runs.
Each run is done twice in this script, with the protocol and with B_rep = 0. Run from the repository root:
    SIM_SCHEME=h1p python -m sim2.experiments.dirTtruAblation [silent|chaos|frame|budget|all|report]
Out: results/dirTtru_ablation_<part><suffix>.csv and results/dirTtru_ablation<suffix>.md."""
import csv
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

from sim2 import ttru
from sim2.experiments import dirTtruSens as T
from sim2.experiments import dirTtruV12 as V

PARTS = ("silent", "chaos", "frame", "budget")


def jobs_of(part):
    """Each run of the default cell of dirTtruSens twice: as is, and with B_rep = 0."""
    base = [j for j in T.jobs_of(part) if (j[1], j[2]) == ("default", 0.0)]
    return base + [(part, "b_rep", 0.0, j[3]) for j in base]


def name(part):
    return os.path.join(V.OUT, f"dirTtru_ablation_{part}{ttru.suffix()}.csv")


def run(part):
    t0 = time.time()
    with Pool(V.PROCS) as pool:
        rows = pool.map(T.job, jobs_of(part), chunksize=1)
    with open(name(part), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r}))
        w.writeheader()
        w.writerows(rows)
    print(f"{part}: {len(rows)} runs, {time.time() - t0:.0f}s", flush=True)


def load(path, keep=lambda r: True):
    if not os.path.exists(path):
        return []
    rows = []
    for r in csv.DictReader(open(path)):
        for k, v in r.items():
            try:
                r[k] = float(v)
            except ValueError:
                pass
        if keep(r):
            rows.append(r)
    return rows


def report():
    L = ["# 信誉进入投票权的消融\n",
         "现行规则（B_rep = 0.10）对只排除领导资格（B_rep = 0，定罪仍排除领导资格，信誉不降）；其余同 dirTtruV12（γ = 10²、"
         "按本文交接规则），n = 31，同一批种子逐次对照。“同伙份额 / 基础份额”为同伙投票份额与其基础份额之比，期末取最后三张表，"
         "全程取所有表的均值（按表份额发放参与收益时，它就是同伙收益相对不降权时的比例）。\n",
         "| 场景 | 规则 | 运行数 | 同伙被定罪比例 | 同伙份额 / 基础份额：期末（全程） | 提交比例 | 诚实被降权最大 | 同伙份额最大 − 1/3 |",
         "|---|---|---|---|---|---|---|---|"]
    for part in PARTS:
        rows_all = load(name(part))
        base = [r for r in rows_all if r["param"] == "default"]
        abl = [r for r in rows_all if r["param"] == "b_rep"]
        for label, rows in (("现行规则", base), ("只排除领导资格", abl)):
            if not rows:
                continue
            conv = np.mean([r["byz_convicted"] for r in rows]) if "byz_convicted" in rows[0] else float("nan")
            end = np.median([r["colluder_share_end"] / r["beta"] for r in rows])
            mean = np.median([r.get("colluder_share_mean", float("nan")) / r["beta"] for r in rows])
            commit = np.mean([r["commit"] for r in rows]) if "commit" in rows[0] else (
                np.mean([r["commit_post"] for r in rows]) if "commit_post" in rows[0] else float("nan"))
            cut = max(r["honest_cut_max"] for r in rows)
            over = max(r["colluder_share_max"] for r in rows) - 1 / 3
            L.append(f"| {part} | {label} | {len(rows)} | {conv:.3f} | {end:.3f}（{mean:.3f}） | {commit:.3f} | "
                     f"{cut:.3f} | {over:+.3f} |")
    with open(os.path.join(V.OUT, f"dirTtru_ablation{ttru.suffix()}.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which == "report":
        report()
    else:
        for part in (PARTS if which == "all" else (which,)):
            run(part)
        report()

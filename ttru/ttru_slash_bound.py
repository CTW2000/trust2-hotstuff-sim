"""Value slashed by a safety violation (理论_可问责安全与纪元交接 推论 2, review T-08). Abstract only.

Theorem 1 gives a slashing set C with share > 1/3 on the EPOCH table; with reputation cuts D <= B_rep
(not redistributed) its base weight is only guaranteed b(C) > (1 - B_rep)/3, and without the epoch
hand-over (theorem 6, monotone / recovering cuts) b(C) > (1 - 2 B_rep)/3 or (1 - 4 B_rep)/3. The
guaranteed slashed value is therefore C_knap(b, theta) = min{V(S): b(S) > theta} for those theta, not the
theta = 1/3 cost of 信任2.0_协议级验证 §2. Same populations as ttru_region (T_tru base weights b =
CapNorm(stake + pi K), V = stake + pi K), 300 populations, B_rep = 0.10.
Out: results/slash_bound.md
Run:  python ttru/ttru_slash_bound.py
"""
import os
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from ttru_region import MAIN, OUT, U_MAX, population, ttru_base  # noqa: E402
from ttru_sim import bribe_exact  # noqa: E402

SEEDS = 300
B = 0.10
THETAS = {"1/3（§2 的口径）": 1 / 3, "(1−B)/3（交接，定理 1）": (1 - B) / 3,
          "(1−2B)/3（不交接、降权不恢复）": (1 - 2 * B) / 3, "(1−4B)/3（不交接、降权可恢复）": (1 - 4 * B) / 3}


def job(args):
    (nL, nU, nA), cap, piK, seed = args
    cls, s = population(nL, nU, nA, seed)
    V = s + np.where(cls == "L", piK, 0.0)
    b = ttru_base(cls, V, cap, U_MAX)
    out = {k: bribe_exact(b, V, th + 1e-9) for k, th in THETAS.items()}
    out["stake_1/3"] = bribe_exact(s, V, 1 / 3)
    return out


def main():
    L = [f"# 一次安全违背至少罚没的价值（{SEEDS} 个人群，B_rep = {B}；全网质押 = 1；中位数）\n",
         "| 人群 | πK | " + " | ".join(THETAS) + " | 与 §2 口径之比（交接） | 纯质押 θ=1/3 |",
         "|---|---|" + "---|" * len(THETAS) + "---|---|"]
    with Pool(int(os.environ.get("SIM_PROCS", "8"))) as pool:
        for name, c in MAIN.items():
            for piK in (0.0, 0.02, 0.05, 0.1):
                out = pool.map(job, [(c["n"], c["cap"], piK, sd) for sd in range(SEEDS)], chunksize=4)
                med = {k: float(np.median([o[k] for o in out])) for k in list(THETAS) + ["stake_1/3"]}
                ratio = float(np.median([o["(1−B)/3（交接，定理 1）"] / o["1/3（§2 的口径）"] for o in out]))
                L.append(f"| {name} | {piK} | " + " | ".join(f"{med[k]:.3f}" for k in THETAS) +
                         f" | {ratio:.2f} | {med['stake_1/3']:.3f} |")
    with open(os.path.join(OUT, "slash_bound.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()

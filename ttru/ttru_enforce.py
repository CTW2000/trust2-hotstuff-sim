"""Unenforceable licenses and the agency problem (信任2.0_协议级验证 §2.4-§2.5). Abstract only.

Same populations as ttru_region (n31, n100; alpha 1.16; u_max 0.25), theta = 1/3, exact knapsack costs.

Part A, reclassification. A fraction of the licensed entities sits in a jurisdiction where the license
penalty is enforced with probability pi_lo (the rest: pi = 1). Weightings:
  nominal     every licensed entity weighted with stake + K
  per_entity  stake + pi_i K, all licensed entities stay in the licensed class
  reclass     licensed entities with pi_i < PI_MIN are moved to the uncertified class (weight from stake,
              class total at most u_max); the others weighted with stake + pi_i K. With fewer licensed
              entities n_L' * cap may fall below 1 - u_max (infeasible), so the licensed cap is raised to
              the smallest feasible value (1 - U) / n_L' (reported: the concentration cost of demotion)
Part B, agency. The replica of a fraction a of the licensed entities is run by an operator who can be
bribed for less than the institution's loss: the bribe for that replica is lam_s * stake + lam_k * pi K.
Weights do not know who is affected (they use stake + pi K), so this lowers the cost side only.
Out: results/enforce.md
Run:  python ttru/ttru_enforce.py
"""
import os
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from ttru_region import MAIN, OUT, THETA, U_MAX, population, ttru_base  # noqa: E402
from ttru_sim import bribe_exact  # noqa: E402

SEEDS = 300
PI_MIN = 0.5


def reclass_weights(cls, s, K, pis, cap):
    """Returns (weights, licensed cap used)."""
    from ttru_sim import cap_normalize
    cls2 = cls.copy()
    lic = cls == "L"
    cls2[lic & (pis < PI_MIN)] = "U"
    V = s + np.where(cls2 == "L", pis * K, 0.0)
    unc = cls2 != "L"
    U = min(V[unc].sum() / V.sum(), U_MAX)
    capL = max(cap, (1.0 - U) / (~unc).sum())
    w = np.zeros(len(V))
    w[~unc] = cap_normalize(V[~unc], capL, 1.0 - U)
    w[unc] = cap_normalize(V[unc], cap, U)
    return w, capL


def job_a(args):
    (nL, nU, nA), cap, K, frac, pi_lo, seed = args
    cls, s = population(nL, nU, nA, seed)
    lic = np.flatnonzero(cls == "L")
    pis = np.zeros(len(s))
    pis[lic] = 1.0
    pis[lic[: int(round(frac * len(lic)))]] = pi_lo
    V = s + pis * K
    cs = bribe_exact(s, V, THETA)
    out = {"nominal": bribe_exact(ttru_base(cls, s + np.where(cls == "L", K, 0.0), cap, U_MAX), V, THETA) / cs,
           "per_entity": bribe_exact(ttru_base(cls, s + pis * K, cap, U_MAX), V, THETA) / cs}
    w, capL = reclass_weights(cls, s, K, pis, cap)
    out["reclass"] = bribe_exact(w, V, THETA) / cs
    out["nak_reclass"] = int(np.searchsorted(np.cumsum(np.sort(w)[::-1]), THETA - 1e-12) + 1)
    out["cap_reclass"] = capL
    return out


def job_b(args):
    (nL, nU, nA), cap, piK, a, lam_s, lam_k, seed = args[:7]
    everyone = len(args) > 7 and args[7]
    cls, s = population(nL, nU, nA, seed)
    pool_idx = np.arange(len(s)) if everyone else np.flatnonzero(cls == "L")
    agent = np.zeros(len(s), bool)
    agent[pool_idx[: int(round(a * len(pool_idx)))]] = True
    V = s + np.where(cls == "L", piK, 0.0)
    cost = np.where(agent, lam_s * s + lam_k * (V - s), V)          # license term only for licensed entities
    cs = bribe_exact(s, cost, THETA)
    ct = bribe_exact(ttru_base(cls, V, cap, U_MAX), cost, THETA)
    return ct / cs


def fmt(a):
    a = np.asarray(a, float)
    a = a[~np.isnan(a)]
    return "—" if not a.size else f"{np.median(a):.2f}（{np.mean(a > 1):.0%}）"


def main():
    L = ["# 处罚不可执行与代理问题（C_T / C_纯质押 的中位数，括号内为 T_tru 成本更高的人群比例；"
         f"{SEEDS} 个人群）\n",
         f"## A. 处罚不可执行的持牌机构改按未认证处理（π_i < {PI_MIN} 即降级）\n",
         "注：降级后把持牌单体上限提高到刚好可行，即 (1−U)/n_L'，这意味着剩余持牌机构全部被封顶，等权分得 1−U。\n",
         "| 人群 | K | 不可执行比例 | π_lo | 按名义 K | 按各自 π_iK | 降级为未认证 | 降级后的持牌单体上限 | 降级后凑齐 1/3 所需实体数（中位数） |",
         "|---|---|---|---|---|---|---|---|---|"]
    with Pool(int(os.environ.get("SIM_PROCS", "8"))) as pool:
        for name, c in MAIN.items():
            for K in (0.05, 0.1, 0.2):
                for frac in (0.3, 0.5):
                    for pi_lo in (0.0, 0.25):
                        out = pool.map(job_a, [(c["n"], c["cap"], K, frac, pi_lo, sd) for sd in range(SEEDS)], chunksize=4)
                        L.append(f"| {name} | {K} | {frac:.0%} | {pi_lo} | {fmt([o['nominal'] for o in out])} | "
                                 f"{fmt([o['per_entity'] for o in out])} | {fmt([o['reclass'] for o in out])} | "
                                 f"{np.median([o['cap_reclass'] for o in out]):.3f}（原 {c['cap']}） | "
                                 f"{np.median([o['nak_reclass'] for o in out]):.0f} |")
        L += ["\n## B. 代理问题：一部分持牌机构的节点由可被收买的运维方操作\n",
              "收买该节点的代价 = λ_s·质押 + λ_K·πK（λ=1 即无代理问题）；权重不知道哪些节点受影响。\n",
              "| 人群 | πK | 受影响比例 a | λ_s | λ_K | C_T / C_纯质押 |", "|---|---|---|---|---|---|"]
        for name, c in MAIN.items():
            for piK in (0.05, 0.1):
                for a, lam_s, lam_k in ((0.0, 1, 1), (0.3, 1, 0.25), (0.3, 1, 0.0), (1.0, 1, 0.25), (1.0, 1, 0.0),
                                        (0.3, 0.25, 0.25), (1.0, 0.25, 0.25)):
                    out = pool.map(job_b, [(c["n"], c["cap"], piK, a, lam_s, lam_k, sd) for sd in range(SEEDS)], chunksize=4)
                    L.append(f"| {name} | {piK} | {a:.0%} | {lam_s} | {lam_k} | {fmt(out)} |")
        L += ["\n对称设定：代理折扣施加于所有实体（持牌与未认证都由可被收买的运维方操作）。\n",
              "| 人群 | πK | 受影响比例 a（全体） | λ_s | λ_K | C_T / C_纯质押 |", "|---|---|---|---|---|---|"]
        for name, c in MAIN.items():
            for piK in (0.05, 0.1):
                for a, lam_s, lam_k in ((0.3, 0.25, 0.25), (1.0, 0.25, 0.25), (1.0, 0.5, 0.5)):
                    out = pool.map(job_b, [(c["n"], c["cap"], piK, a, lam_s, lam_k, sd, True) for sd in range(SEEDS)],
                                   chunksize=4)
                    L.append(f"| {name} | {piK} | {a:.0%} | {lam_s} | {lam_k} | {fmt(out)} |")
    with open(os.path.join(OUT, "enforce.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()

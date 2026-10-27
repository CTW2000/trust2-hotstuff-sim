"""Cross-epoch quorum intersection: exhaustive check of the two conditions in 信任2.0_协议级验证 §5.

Model: base weights b (sum 1), Byzantine set Z with share beta0. Between two epochs the reputation cut
removes c <= B_rep of weight from honest replicas (r_i >= r_min, removed weight not redistributed) and the
second table is (b - cut) / (1 - c). A cross-epoch violation is a QC of table 1 and a TC of table 2
(each a share strictly above 2/3) whose signers meet only in Z. For small n we enumerate every split of
the honest replicas into H1 (QC only), H2 (TC only) and H3 (neither); the cut that helps the adversary
most falls on H1 and H3 (it never helps to cut H2), so c = min(B_rep, (1 - r_min) * b(H1 u H3)).
Checks:
  (a) one table after the cut (hand-over rule): both quorums of the same post-cut table, the cut falling on
      honest replicas outside both quorums (the worst place); no violation whenever beta0 < (1 - B_rep)/3;
  (b) two tables without hand-over: no violation whenever beta0 < (1 - 2 B_rep) / 3 (sufficient), and
      violations do occur for beta0 between (1 - 2 B_rep)/3 and (1 - B_rep)/3 (the v0.4 condition).
Run:  python ttru/epoch_check.py
"""
import itertools
import os

import numpy as np

OUT = os.path.join(os.path.dirname(__file__), "results")
Q = 2 / 3
EPS = 1e-12


def violation(b, byz, B, r_min, one_table=False):
    beta = b[byz].sum()
    hon = np.flatnonzero(~byz)
    for assign in itertools.product((0, 1, 2), repeat=len(hon)):
        a = np.array(assign)
        h1, h2, h3 = b[hon[a == 0]].sum(), b[hon[a == 1]].sum(), b[hon[a == 2]].sum()
        if h1 + beta <= Q + EPS:
            continue
        if one_table:
            c = min(B, (1 - r_min) * h3)
            if (h1 + beta) / (1 - c) > Q + EPS and (h2 + beta) / (1 - c) > Q + EPS:
                return True
            continue
        c = min(B, (1 - r_min) * (h1 + h3))
        if (h2 + beta) / (1 - c) > Q + EPS:
            return True
    return False


def instance(rng, n, beta0):
    """Random weights with a Byzantine set of share exactly beta0 (scale the two parts)."""
    nb = rng.integers(1, max(2, n // 3) + 1)
    wb = rng.dirichlet(np.ones(nb)) * beta0
    wh = rng.dirichlet(np.ones(n - nb) * rng.choice([0.5, 1.0, 3.0])) * (1 - beta0)
    b = np.r_[wb, wh]
    byz = np.r_[np.ones(nb, bool), np.zeros(n - nb, bool)]
    return b, byz


def main():
    rng = np.random.default_rng(7)
    lines = ["# 跨纪元法定集合相交：穷举检验（每格随机权重实例；n 为节点数）\n",
             "| n | B_rep | r_min | β0 | 条件 | 实例数 | 单表（交接）违背 | 两表（不交接）违背 |",
             "|---|---|---|---|---|---|---|---|"]
    bad = 0
    for n in (7, 9, 11):
        for B, r_min in ((0.10, 0.7), (0.20, 0.5)):
            lo, hi = (1 - 2 * B) / 3, (1 - B) / 3
            for beta0, tag in ((lo - 0.01, "< (1−2B)/3"), (lo + 0.005, "略高于 (1−2B)/3"), ((lo + hi) / 2, "两条件之间"),
                               (hi - 0.002, "略低于 (1−B)/3")):
                trials = 300 if n <= 9 else 80
                v1 = v2 = 0
                for _ in range(trials):
                    b, byz = instance(rng, n, beta0)
                    v1 += violation(b, byz, B, r_min, one_table=True)
                    v2 += violation(b, byz, B, r_min)
                lines.append(f"| {n} | {B} | {r_min} | {beta0:.4f} | {tag} | {trials} | {v1} | {v2} |")
                if v1 or (beta0 < lo and v2):
                    bad += 1
    # tightness of (1 - 2B)/3 depends on r_min: with little room to cut (r_min = 0.9) the threshold moves up
    for n in (9,):
        for B, r_min in ((0.10, 0.9),):
            lo = (1 - 2 * B) / 3
            for beta0, tag in ((lo + 0.005, "略高于 (1−2B)/3，r_min=0.9"), (0.305, "0.305，r_min=0.9"), (0.32, "0.32，r_min=0.9")):
                v1 = v2 = 0
                for _ in range(300):
                    b, byz = instance(rng, n, beta0)
                    v1 += violation(b, byz, B, r_min, one_table=True)
                    v2 += violation(b, byz, B, r_min)
                lines.append(f"| {n} | {B} | {r_min} | {beta0:.4f} | {tag} | 300 | {v1} | {v2} |")
    lines.append("\n判据：单表（降权后、交接规则下）违背必须为 0；β0 < (1−2B)/3 时两表违背必须为 0。" + ("全部通过。" if not bad else f"失败 {bad} 格。"))
    lines.append("(1−2B)/3 的紧性依赖 r_min：要把预算 B 全部压到提交 QC 的诚实部分上，需要 (1−r_min)·b(H1∪H3) ≥ B；r_min 接近 1 时阈值上移（末三行）。")
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "epoch_check.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    assert not bad


if __name__ == "__main__":
    main()

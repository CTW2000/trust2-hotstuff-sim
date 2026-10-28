"""Cost of the forensic rules (理论_可问责安全与纪元交接 §4 第 6 条, 命题 3(d)): certificate and evidence sizes,
verification work, and how often a block must embed a TC. Abstract models only; nothing contacts a real
system.

Sizes use BLS12-381 in the "minimal public key" setting used by Aptos (signature 96 bytes in G2, public
key 48 bytes in G1) and a minimal encoding: hash 32 bytes, round and epoch 8 bytes each, signer bitmap
ceil(n/8) bytes. Real QCs (for example Aptos VoteData with two BlockInfo records) are larger, so the
relative overhead of an embedded TC is smaller in practice than in this table.
  QC       = epoch + round + block hash + bitmap + aggregate signature
  TC       = epoch + round + highest QC + bitmap + one 8-byte hq round per signer + aggregate signature
             (multi-message aggregate, as Aptos AggregateSignatureWithRounds)
  evidence = the whole culprit set is convicted by two certificates: E1 needs two QCs; E3 needs QC(X+),
             TC(w-1) and the two block headers that bind them (header taken as 128 bytes).
Verification of an aggregate over |S| signers: after grouping the public keys by message, |S|-1 point
additions and one pairing per distinct message plus one; a TC whose signers report d distinct hq rounds
signs d distinct messages (d+1 pairings), plus 2 pairings for the QC it carries. The signer count is
taken as 2n/3+1 (equal weights); with unequal weights it is the size of the smallest quorum used.

How often a block embeds a TC (its justify QC is not of the previous view) is measured with the protocol
simulator (sim2): P2, AT x = 2/3, rho = 0.1, NR on header and block, R3 on, no forwarding, colluder share
about 0.24, 2000 views, 8 populations per cell.

Run from the repository root:  python formal/overhead.py   (writes formal/results/overhead.md)
"""
import math
import os
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sim2 import adversary as A                                  # noqa: E402
from sim2 import engine_event                                    # noqa: E402
from sim2 import schedule as S                                   # noqa: E402
from sim2 import ttru                                            # noqa: E402
from sim2.common import RunConfig, State                         # noqa: E402
from sim2.experiments.dirTtru import N, cheapest_set, evade_k, setup   # noqa: E402
from sim2.net import NetConfig, Network                          # noqa: E402

SIG, HASH, ROUND, EPOCH, HEADER = 96, 32, 8, 8, 128
VIEWS, SEEDS = 2000, 8
OUT = os.path.join(os.path.dirname(__file__), "results")


def qc_bytes(n):
    return EPOCH + ROUND + HASH + math.ceil(n / 8) + SIG


def tc_bytes(n):
    signers = 2 * n // 3 + 1
    return EPOCH + ROUND + qc_bytes(n) + math.ceil(n / 8) + ROUND * signers + SIG


def job(args):
    mode, eps, seed = args
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, 0.2, max_share=0.30)
    rule = S.CusumExclusion(q=0.5, evidence="at", rho_bar=0.1, D=500, cap=0.5, Wq=500, cap_weights=base)
    adv = {"none": None, "silent": A.SilentLeader(1.0), "targeted": A.PartialSend(evade_k(base, byz, 2 / 3), targeted=True),
           "slow": A.SlowLeader(1800.0), "frame_withhold": A.Compose([A.LieNR(), A.WithholdVotesOnHonest()])}[mode]
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol="P2", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    adversary=adv, vote_weights=ttru.TtruWeights(base, epoch=100, rule=rule), at_share=2 / 3,
                    nr_requires_data=True, vote_monotone=True)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps)), st, 1, VIEWS)
    ws = [w for w in range(VIEWS // 2, VIEWS - 10) if st.prop_parent[w] >= 0]
    tc_justified = float(np.mean([st.prop_parent[w] < w - 1 for w in ws])) if ws else float("nan")
    tc_views = float(np.mean(st.tc_exists[VIEWS // 2:VIEWS - 10]))
    return mode, eps, tc_justified, tc_views


def main():
    os.makedirs(OUT, exist_ok=True)
    cells = [("none", 0.0), ("none", 0.05), ("none", 0.1), ("none", 0.2), ("silent", 0.0), ("targeted", 0.0),
             ("slow", 0.0), ("frame_withhold", 0.1)]
    with Pool(int(os.environ.get("SIM_PROCS", "8"))) as pool:
        rows = pool.map(job, [(m, e, s) for m, e in cells for s in range(SEEDS)], chunksize=1)
    names = {"none": "无对手", "silent": "沉默领导者", "targeted": "定向部分发送", "slow": "慢领导者（1.8 s）",
             "frame_withhold": "扣票 + 谎报 NR"}
    L = ["# 取证规则的开销（证书与证据大小、验证量、块内嵌 TC 的频率）\n",
         "## 证书与证据大小（字节；BLS12-381 minpk，最小编码）\n",
         "| n | QC | TC（逐签名者 hq） | E1 证据（整组罪犯） | E3 证据（整组罪犯） | TC 验证的配对数（d 个不同 hq） |",
         "|---|---|---|---|---|---|"]
    for n in (31, 100, 200):
        q, t = qc_bytes(n), tc_bytes(n)
        L.append(f"| {n} | {q} | {t} | {2 * q} | {q + t + 2 * HEADER} | d + 1，另加所附 QC 的 2 次（QC 本身为 2） |")
    L += ["\n说明：字节数是最小编码，Aptos 的实际结构（例如 VoteData 带两份 BlockInfo）更大，所以内嵌 TC 的相对开销在实际中更小；"
          "配对数指按消息分组聚合公钥之后的代价；签名者数按等权的 2n/3+1 计。\n",
          "\n## 需要内嵌 TC 的块所占比例（仿真，n=31，每格 8 个人群，后半段视图）\n",
          "| 场景 | ε | 内嵌 TC 的块比例（均值 [最小–最大]） | 以超时结束的视图比例 | n=100 时每块平均多出的字节 | n=200 时 |",
          "|---|---|---|---|---|---|"]
    for m, e in cells:
        g = [r for r in rows if (r[0], r[1]) == (m, e)]
        f = np.array([r[2] for r in g])
        tv = np.mean([r[3] for r in g])
        L.append(f"| {names[m]} | {e} | {f.mean():.4f} [{f.min():.4f}–{f.max():.4f}] | {tv:.4f} | "
                 f"{f.mean() * tc_bytes(100):.1f} | {f.mean() * tc_bytes(200):.1f} |")
    L.append("\n说明：每块平均多出的字节 = 内嵌 TC 的块比例 × TC 大小。块的负载按仿真设定为 250 kB 时，"
             "即使在每个块都内嵌 TC 的极端情形下，n=200 的 TC 也只占块大小的约 "
             f"{tc_bytes(200) / 250e3 * 100:.2f}%。")
    with open(os.path.join(OUT, "overhead.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()

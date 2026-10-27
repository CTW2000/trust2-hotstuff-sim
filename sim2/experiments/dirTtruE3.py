"""Hard check of accountable-safety evidence E3 on honest replicas (理论_可问责安全与纪元交接 §4 item 12).

Lemma 1 there: under R1-R8 an honest replica never signs a vote of v1 (block justified by QC(j)) and a
timeout of v2 >= v1 with hq view h < j. The simulator allows late votes for views a replica has left
(it violates R3 unless cfg.vote_monotone), so honest E3 should appear without the rule and vanish with
it. Same population, colluders and T_tru weights as dirTtru; leader rule CUSUM over AT (x = 2/3).
Networks: S, eps 0.05 / 0.1 / 0.2 late messages, 300 asynchronous views (p = 0.5, up to 3 s).
Adversaries: none, framing (withhold votes in honest views + NR=1), targeted partial send.
Positive control (review v0.5 exp #5; schedule of 理论 命题 3(b), honest-only, n = 7, counting votes): the
network delays chosen messages around view J so that an honest replica times out in J+2 with hq < J and then
receives the late proposal of J+1 (justified by QC(J)); without R3 it votes for it and e3_violators flags it,
with R3 it does not. This checks that the detector and the R3 switch work, which the random runs cannot.
Environment: SIM_PROCS (default 8), SIM_SEEDS (default 8).
Run from the repository root:  python -m sim2.experiments.dirTtruE3
Out: results/dirTtru_e3.{csv,md}
"""
import csv
import os
import time
from multiprocessing import Pool

import numpy as np

from sim2 import adversary as A
from sim2 import engine_event
from sim2 import schedule as S
from sim2 import ttru
from sim2.common import RunConfig, State
from sim2.experiments.dirTtru import N, OUT, cheapest_set, evade_k, setup
from sim2.experiments.ttru_perf import perf
from sim2.net import NetConfig, Network

PROCS = int(os.environ.get("SIM_PROCS", "8"))
SEEDS = int(os.environ.get("SIM_SEEDS", "8"))
VIEWS = 2000
NETS = {"S": {}, "eps0.05": dict(eps_late=0.05), "eps0.1": dict(eps_late=0.1), "eps0.2": dict(eps_late=0.2),
        "async300": dict(async_views=300, async_p=0.5, async_extra_ms=3000.0)}
ADVS = ("none", "frame", "partial")


POS_N, POS_J, POS_K = 7, 20, 1
POS_BIG, POS_HALF = 12_000.0, 1_000.0


class PositiveNet(Network):
    """Adversarial schedule of the positive control (see module docstring)."""

    def __init__(self, cfg, L1, k):
        super().__init__(cfg)
        self.L1, self.k = L1, k

    def delays(self, view, mtype):
        d = super().delays(view, mtype).copy()
        J, L1, k = POS_J, self.L1, self.k
        others = np.ones(self.cfg.n, bool)
        others[L1] = False
        if view == J and mtype == "vote":
            d[:, others] += POS_BIG                 # only L1 = leader(J+1) forms QC(J)
        if view == J and mtype == "tmo":
            d[:, k] += POS_HALF                     # k gets cert(J) late ...
        if view == J + 1 and mtype == "fwd":
            d[:, k] += POS_HALF                     # ... so TC(J+1) reaches k before its own timer of J+1
        if J + 1 <= view <= J + 3 and mtype in ("prop", "fwd", "tmo"):
            d[L1, :] += POS_BIG                     # L1's proposal of J+1 (carrying QC(J)) is late
        if view == J + 2 and mtype == "prop":
            d[:, :] += POS_BIG                      # everybody times out in J+2 with hq < J
        np.fill_diagonal(d, 0.0)
        return d


def positive(mono, seed=1):
    cfg = RunConfig(n=POS_N, views=80, seed=seed, protocol="P2", track_signed=True, vote_monotone=mono)
    st = State(cfg)
    net = PositiveNet(NetConfig(n=POS_N, seed=seed, regions=3, jitter_max_ms=2.0), int(st.leaders[POS_J + 1]), POS_K)
    engine_event.simulate(cfg, net, st, 1, cfg.views)
    return np.flatnonzero(S.e3_violators(st) & st.honest).tolist()


def job(args):
    proto, net, adv_name, mono, seed = args
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, 0.2)
    rule = S.CusumExclusion(q=0.5, evidence="at", rho_bar=0.03, D=500, cap=0.5, Wq=500, cap_weights=base)
    vw = ttru.TtruWeights(base, epoch=100, rule=rule)
    adv = {"none": None, "frame": A.Compose([A.LieNR(), A.WithholdVotesOnHonest()]),
           "partial": A.PartialSend(evade_k(base, byz, 2 / 3), targeted=True)}[adv_name]
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol=proto, leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    adversary=adv, vote_weights=vw, at_share=2 / 3, track_signed=True, vote_monotone=mono)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, **NETS[net])), st, 1, VIEWS)
    e3 = S.e3_violators(st)
    return dict(protocol=proto, net=net, adversary=adv_name, monotone=mono, seed=seed,
                honest_e3=int((e3 & st.honest).sum()), honest_e3_share=float(base[e3 & st.honest].sum()),
                byz_e3=int((e3 & st.byz).sum()), votes=len(st.sig_votes),
                qc_rate=float(np.mean(st.qc_exists[100:VIEWS - 10])), **perf(st, 100, VIEWS - 10))


def main():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    jobs = [(p, n, a, m, s) for p in ("P2", "P1") for n in NETS for a in ADVS for m in (False, True) for s in range(SEEDS)]
    with Pool(PROCS) as pool:
        rows = pool.map(job, jobs, chunksize=1)
    with open(os.path.join(OUT, "dirTtru_e3.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    L = [f"# 诚实节点产生 E3（highQC 倒退）证据的次数（每格 {SEEDS} 个人群，{VIEWS} 视图）\n",
         "每格：产生 E3 的诚实节点数（人群平均）/ 其最大基础份额；左为允许迟到投票（现状），右为 R3 单调投票。\n",
         "| 协议 | 对手 | " + " | ".join(NETS) + " |", "|---|---|" + "---|" * len(NETS)]
    for p in ("P2", "P1"):
        for a in ADVS:
            cells = []
            for n in NETS:
                c = []
                for m in (False, True):
                    G = [o for o in rows if (o["protocol"], o["net"], o["adversary"], o["monotone"]) == (p, n, a, m)]
                    c.append(f"{np.mean([o['honest_e3'] for o in G]):.1f}/{max(o['honest_e3_share'] for o in G):.2f}")
                cells.append(" → ".join(c))
            L.append(f"| {p} | {a} | " + " | ".join(cells) + " |")
    L += ["\n提交比例 / 每秒提交块数（左：允许迟到投票；右：R3）：\n", "| 协议 | 对手 | " + " | ".join(NETS) + " |", "|---|---|" + "---|" * len(NETS)]
    for p in ("P2", "P1"):
        for a in ADVS:
            cells = []
            for n in NETS:
                c = [[np.mean([o[key] for o in rows if (o["protocol"], o["net"], o["adversary"], o["monotone"]) == (p, n, a, m)])
                      for key in ("commit", "bps")] for m in (False, True)]
                cells.append(f"{c[0][0]:.3f}/{c[0][1]:.2f} → {c[1][0]:.3f}/{c[1][1]:.2f}")
            L.append(f"| {p} | {a} | " + " | ".join(cells) + " |")
    pos = {m: positive(m) for m in (False, True)}
    L.append(f"\n正例（命题 3(b) 的对抗调度，n=7）：产生 E3 的诚实节点，允许迟到投票 {pos[False]}，R3 {pos[True]}")
    L.append(f"\nwall {time.time() - t0:.0f}s")
    with open(os.path.join(OUT, "dirTtru_e3.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()

"""G1 slashing (z = 0) in the weighted closed loop (信任2.0_协议级验证 §4.1). Abstract only.

Same population, colluders and weights as dirTtru (n = 31, colluders = the cheapest ~0.24 of base weight).
Colluders run LieNRVote: in honest leaders' views every colluder claims NR=1; a share `greedy` of them
also votes (keeping its vote presence) and broadcasts the NR=1 timeout right after voting, which an
honest replica holding the vote turns into a transferable proof (NR self-contradiction, G1); the others
withhold their vote (consistent liars, not provable). With track_signed, schedule.liars(st, v) is the
proven-liar set; CusumExclusion(g1=True) bars liars from leading and TtruWeights(g1=True) sets z = 0
(their voting weight is removed for good, not redistributed into the budget).
Networks: S, eps = 0.05 late messages, and 300 asynchronous views before GST (soundness: no honest
replica may ever be proven a liar).
Environment: SIM_PROCS (default 8), SIM_SEEDS (default 8).
Run from the repository root:  python -m sim2.experiments.dirTtruG1
Out: results/dirTtru_g1.{csv,md}
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
from sim2.experiments.dirTtru import N, OUT, cheapest_set, setup
from sim2.net import NetConfig, Network

PROCS = int(os.environ.get("SIM_PROCS", "8"))
SEEDS = int(os.environ.get("SIM_SEEDS", "8"))
VIEWS = 3000
NETS = {"S": {}, "eps0.05": dict(eps_late=0.05), "async300": dict(async_views=300, async_p=0.5, async_extra_ms=3000.0)}


def job(args):
    proto, greedy, net, seed = args
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, 0.2)
    rule = S.CusumExclusion(q=0.5, evidence="at", rho_bar=0.03, D=500, cap=0.5, Wq=500, cap_weights=base, g1=True)
    vw = ttru.TtruWeights(base, epoch=100, rule=rule, g1=True)
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol=proto, leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    adversary=A.LieNRVote(greedy=greedy), vote_weights=vw, at_share=2 / 3, track_signed=True)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, **NETS[net])), st, 1, VIEWS)
    end = VIEWS - 10
    K = S.liars(st, end)
    first = {}
    for u in range(1, end - cfg.lag):
        for k in np.flatnonzero(S.contradictions(st, u)):
            first.setdefault(int(k), u)
    cache = st.__dict__["_ttru_cache"][id(vw)]
    tables = cache["tables"]
    lead = st.leaders[1:end]
    acc = np.array([S.bad_fact(st, u, u + cfg.lag, "at") for u in range(1, end)])
    n_greedy = int(round(greedy * byz.sum()))
    return dict(protocol=proto, greedy=greedy, net=net, seed=seed, beta=float(base[byz].sum()), n_byz=int(byz.sum()),
                n_greedy=n_greedy, liars_caught=int((K & st.byz).sum()), honest_caught=int((K & st.honest).sum()),
                first_proof_view=float(np.mean(list(first.values()))) if first else float("nan"),
                colluder_share_end=float(tables[-1][byz].sum()),
                slashed_share=float(base[K & st.byz].sum()),
                honest_accused=float(acc[st.honest[lead]].mean()),
                colluder_lead_late=float(np.mean(st.byz[st.leaders[VIEWS // 2:end]])),
                qc_rate=float(np.mean(st.qc_exists[100:end])))


def main():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    jobs = [(p, g, n, s) for p in ("P2", "P1") for g in (0.0, 0.5, 1.0) for n in NETS for s in range(SEEDS)]
    with Pool(PROCS) as pool:
        rows = pool.map(job, jobs, chunksize=1)
    with open(os.path.join(OUT, "dirTtru_g1.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    L = [f"# G1 罚没（NR 自相矛盾 → z=0）的加权闭环（每格 {SEEDS} 个人群，{VIEWS} 视图）\n",
         "| 协议 | 贪心说谎者比例 | 网络 | 同伙数 / 其中贪心 | 被证实的说谎者 | 被误证实的诚实节点 | 首次证据所在视图 | "
         "被罚没的份额 | 同伙基础份额 → 期末投票份额 | 诚实领导视图被 AT 指控率 | 后半段同伙领导份额 | QC 率 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for p in ("P2", "P1"):
        for g in (0.0, 0.5, 1.0):
            for n in NETS:
                G = [o for o in rows if (o["protocol"], o["greedy"], o["net"]) == (p, g, n)]
                m = lambda c: float(np.nanmean([o[c] for o in G]))  # noqa: E731
                L.append(f"| {p} | {g} | {n} | {m('n_byz'):.1f} / {m('n_greedy'):.1f} | {m('liars_caught'):.1f} | "
                         f"{sum(o['honest_caught'] for o in G)} | {m('first_proof_view'):.0f} | {m('slashed_share'):.3f} | "
                         f"{m('beta'):.3f} → {m('colluder_share_end'):.3f} | {m('honest_accused'):.4f} | "
                         f"{m('colluder_lead_late'):.3f} | {m('qc_rate'):.3f} |")
    L.append(f"\nwall {time.time() - t0:.0f}s")
    with open(os.path.join(OUT, "dirTtru_g1.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()

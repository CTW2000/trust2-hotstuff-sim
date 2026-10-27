"""Inclusion attestations (G2) under T_tru weighted voting (证据扩展设计 §2.5 E-INC1..3, 信任2.0_协议级验证 §4.2).

Same population, colluders and weights as dirTtru (n = 31, colluders = the cheapest ~0.24 of base weight);
P2. Transaction layer: sim2.txlayer with the weighted due threshold (attesting share > 2/3; control:
> 1/3, the f+1 analogue), attestation guard delta_g = delta_fwd + delta_max.

Part "reliab" (E-INC1): leader rule Uniform (weighted draw); colluders try INC-2 framing in every honest-
led view and submit conflicting pairs; networks S, eps 0.05 / 0.1 / 0.2, 300 asynchronous views. Metric:
share of certified honest-led views flagged "omit".
Part "detect" (E-INC2/3): colluding leaders censor a victim client (25% of transactions) with
probability c; leader rule = CUSUM over "at" or over ("at", "omit") (rho_bar 0.03, q 0.5), T_tru
reputation on its convictions; eps 0 / 0.05 / 0.1. Metrics: colluder censoring views flagged, honest
flagged, convictions, victim inclusion delay (views) vs other transactions, QC rate, colluder vote share.
Environment: SIM_PROCS (default 8), SIM_SEEDS (default 8).
Run from the repository root:  python -m sim2.experiments.dirTtruInc [reliab|detect]
Out: results/dirTtru_inc_reliab.{csv,md}, results/dirTtru_inc_detect.{csv,md}
"""
import csv
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

from sim2 import engine_event
from sim2 import schedule as S
from sim2 import ttru
from sim2.common import RunConfig, State
from sim2.experiments.dirTtru import N, OUT, cheapest_set, setup
from sim2.net import NetConfig, Network
from sim2.txlayer import TxAdversary, TxConfig, TxLayer

PROCS = int(os.environ.get("SIM_PROCS", "8"))
SEEDS = int(os.environ.get("SIM_SEEDS", "8"))
VIEWS = 2000
NETS = {"S": {}, "eps0.05": dict(eps_late=0.05), "eps0.1": dict(eps_late=0.1), "eps0.2": dict(eps_late=0.2),
        "async300": dict(async_views=300, async_p=0.5, async_extra_ms=3000.0), "outage": dict(outage_p=0.02)}


def reliab_job(args):
    thr, net, seed = args
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, 0.2)
    nw = Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, **NETS[net]))
    tl = TxLayer(TxConfig(threshold=thr, adversary=TxAdversary(frame=1.0, conflict=0.3), seed=seed), nw)
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol="P2", leader_rule=S.Uniform(),
                    byzantine=list(np.flatnonzero(byz)), vote_weights=lambda st, v: base, txlayer=tl)
    st = State(cfg)
    engine_event.simulate(cfg, nw, st, 1, VIEWS)
    sx = tl.advance(st, VIEWS - 3)
    hl = [u for u in range(20, VIEWS - 10) if st.honest[st.leaders[u]] and st.qc_exists[u]]
    frames = sum(1 for m in sx["meta"] if m["frame"])
    return dict(threshold=thr, net=net, seed=seed, honest_views=len(hl),
                honest_flagged=float(np.mean([sx["omit"][u] for u in hl])), frame_attempts=frames)


def detect_job(args):
    evidence, c, eps, seed = args
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, 0.2)
    nw = Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps))
    tl = TxLayer(TxConfig(threshold="w", adversary=TxAdversary(censor=c), seed=seed), nw)
    ev = ("at", "omit") if evidence == "at+omit" else "at"
    rule = S.CusumExclusion(q=0.5, evidence=ev, rho_bar=0.03, D=500, cap=0.5, Wq=500, cap_weights=base)
    vw = ttru.TtruWeights(base, epoch=100, rule=rule)
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol="P2", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    vote_weights=vw, txlayer=tl, at_share=2 / 3)
    st = State(cfg)
    engine_event.simulate(cfg, nw, st, 1, VIEWS)
    sx = tl.advance(st, VIEWS - 3)
    end = VIEWS - 10
    cens = [u for u in range(20, end) if st.byz[st.leaders[u]] and st.qc_exists[u] and sx["content"].get(u, (0, 0, 0))[2]]
    hl = [u for u in range(20, end) if st.honest[st.leaders[u]] and st.qc_exists[u]]
    vic, oth = tl.victim_delays(st, 50, end - 50)
    conv = {node for e, node, u in st.rule_log if e == "exclude"}
    w_end = vw.table(st, (VIEWS - 11) // 100)
    return dict(evidence=evidence, censor=c, eps=eps, seed=seed,
                byz_flagged=float(np.mean([sx["omit"][u] for u in cens])) if cens else float("nan"),
                honest_flagged=float(np.mean([sx["omit"][u] for u in hl])),
                byz_convicted=len([k for k in conv if st.byz[k]]) / int(byz.sum()),
                honest_convicted=len([k for k in conv if st.honest[k]]),
                victim_delay=float(np.mean(vic)) if vic else float("nan"),
                victim_p95=float(np.percentile(vic, 95)) if vic else float("nan"),
                other_delay=float(np.mean(oth)) if oth else float("nan"),
                colluder_lead_late=float(np.mean(st.byz[st.leaders[VIEWS // 2:end]])),
                colluder_vote_share_end=float(w_end[st.byz].sum()), qc_rate=float(np.mean(st.qc_exists[100:end])))


def write(name, rows):
    with open(os.path.join(OUT, name), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def run_reliab():
    t0 = time.time()
    jobs = [(thr, n, s) for thr in ("w", "w13") for n in NETS for s in range(SEEDS)]
    with Pool(PROCS) as pool:
        rows = pool.map(reliab_job, jobs, chunksize=1)
    write("dirTtru_inc_reliab.csv", rows)
    L = [f"# 交易包含证言的可靠性（加权；每格 {SEEDS} 个人群，{VIEWS} 视图；同伙每个诚实视图都尝试陷害并制造冲突交易）\n",
         "| 到期门槛 | " + " | ".join(NETS) + " |", "|---|" + "---|" * len(NETS)]
    for thr in ("w", "w13"):
        cells = []
        for n in NETS:
            G = [o for o in rows if (o["threshold"], o["net"]) == (thr, n)]
            cells.append(f"{np.mean([o['honest_flagged'] for o in G]):.4f}")
        L.append(f"| {'份额 > 2/3' if thr == 'w' else '份额 > 1/3（对照）'} | " + " | ".join(cells) + " |")
    L.append("\n（表中为被记 omit 的诚实领导、已认证视图的比例）")
    L.append(f"\nwall {time.time() - t0:.0f}s")
    with open(os.path.join(OUT, "dirTtru_inc_reliab.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


def run_detect():
    t0 = time.time()
    jobs = [(ev, c, e, s) for ev in ("at", "at+omit") for c in (1.0, 0.5, 0.2) for e in (0.0, 0.05, 0.1)
            for s in range(SEEDS)]
    with Pool(PROCS) as pool:
        rows = pool.map(detect_job, jobs, chunksize=1)
    write("dirTtru_inc_detect.csv", rows)
    L = [f"# 审查的检出与约束（加权到期门槛 > 2/3；每格 {SEEDS} 个人群，{VIEWS} 视图）\n",
         "| 领导者规则证据 | 审查概率 | ε | 审查视图被记 omit | 诚实视图被记 omit | 同伙被定罪比例 | 诚实被定罪 | "
         "受害交易上链延迟（均值 / 95%） | 其他交易延迟 | 后半段同伙领导份额 | 期末同伙投票份额 | QC 率 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for ev in ("at", "at+omit"):
        for c in (1.0, 0.5, 0.2):
            for e in (0.0, 0.05, 0.1):
                G = [o for o in rows if (o["evidence"], o["censor"], o["eps"]) == (ev, c, e)]
                m = lambda k: float(np.nanmean([o[k] for o in G]))  # noqa: E731
                L.append(f"| {ev} | {c} | {e} | {m('byz_flagged'):.3f} | {m('honest_flagged'):.4f} | {m('byz_convicted'):.2f} | "
                         f"{m('honest_convicted'):.1f} | {m('victim_delay'):.2f} / {m('victim_p95'):.1f} | {m('other_delay'):.2f} | "
                         f"{m('colluder_lead_late'):.3f} | {m('colluder_vote_share_end'):.3f} | {m('qc_rate'):.3f} |")
    L.append(f"\nwall {time.time() - t0:.0f}s")
    with open(os.path.join(OUT, "dirTtru_inc_detect.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    {"reliab": run_reliab, "detect": run_detect}[sys.argv[1] if len(sys.argv) > 1 else "reliab"]()

"""Closed loop (NR self-contradiction results v0.2 §7, review M5): G1 bars, presence convictions and
the cleaned slot score inside R5/R6. Abstract models only.

Network as M3/E6 (6 regions, heterogeneous latency), n = 31, tau = 2000 ms, 6000 views, warm-up
1000. Colluders always lie in slot-duration reports (+inf for honest leaders, 0 for their own) and
pick reports when they assemble a certificate (slot_score, lie=True).
Rules:
  uniform
  R6                   PerfTilt(L=1/200, K=50) + R5 (AT evidence, CUSUM, cap 0.5, D=500)   (M3)
  R6+G1+clean          + proven liars barred at once, score from the pool without them
  R6+G1+clean+pres     + presence conviction (P2: threshold 0.7, P1: 0.4; window 300 views)
Adversaries (in honest leaders' views unless stated):
  behave       follow the protocol (lying reports only)
  withhold     withhold votes (A2)
  withhold_r   withhold with probability 0.5 per view
  greedy       vote and claim NR=1 (caught by G1)
  partial      M3 "partial": withhold, lie in NR, partially send own proposals (unattributable)
  frame        (P1) leave honest replica 0 out of every QC the colluders form
Measured after the warm-up: mean slot time (first honest entry to the next), colluder leader
share, time-average number of honest / colluding replicas barred from leading, number of honest
replicas ever convicted through presence.
Environment: SIM_PROCS (default 8), SIM_SEEDS (default 2).
Run from the repository root:  python -m sim2.experiments.dirNRC_loop
"""
import csv
import os
import time
from multiprocessing import Pool

import numpy as np

from sim2 import adversary as A
from sim2 import engine_fast
from sim2 import schedule as S
from sim2.common import RunConfig
from sim2.experiments.m3_e6_perf import NET, TAU, adversary as m3_adversary
from sim2.net import NetConfig, Network

OUT = os.path.join(os.path.dirname(__file__), "..", "results")
N, VIEWS, WARM = 31, 6000, 1000
PROCS = int(os.environ.get("SIM_PROCS", "8"))
SEEDS = int(os.environ.get("SIM_SEEDS", "2"))
RULES = ("uniform", "R6", "R6+G1+clean", "R6+G1+clean+pres")
ADVS = {"P2": ("behave", "withhold", "withhold_r", "greedy", "partial"),
        "P1": ("behave", "withhold", "withhold_r", "greedy", "partial", "frame")}


def make_rule(name, proto):
    if name == "uniform":
        return S.Uniform()
    kw = dict(evidence="at", D=500, cap=0.5, Wq=500)
    if "G1" in name:
        kw["g1"] = True
    if "pres" in name:
        kw.update(presence_theta=0.7 if proto == "P2" else 0.4, presence_window=300)
    return S.PerfTilt(L=1 / 200, K=50, W=20, V=2000, clean="clean" in name, exclusion=S.CusumExclusion(**kw))


def make_adv(name, f0):
    if name == "behave":
        return None
    if name == "withhold":
        return A.LieNRVote(greedy=0.0, claim=False)
    if name == "withhold_r":
        return A.LieNRVote(greedy=0.0, claim=False, wp=0.5)
    if name == "greedy":
        return A.LieNRVote(greedy=1.0)
    if name == "partial":
        return m3_adversary("partial", f0)
    return A.PresenceFrame(targets=(0,))


def barred_time(log, roles, lo, hi):
    """Time-average number of honest and colluding replicas barred from leading in views [lo, hi)."""
    start = {}
    tot = {1: 0.0, 2: 0.0}
    ever_presence_honest = set()
    for ev, k, u in sorted(log, key=lambda e: e[2]):
        if ev in ("exclude", "g1") and k not in start:
            start[k] = u
        elif ev == "release" and k in start:
            a, b = max(start.pop(k), lo), min(u, hi)
            if b > a and roles[k] in tot:
                tot[roles[k]] += b - a
        if ev == "presence" and roles[k] == 1:
            ever_presence_honest.add(k)
    for k, a in start.items():
        a, b = max(a, lo), hi
        if b > a and roles[k] in tot:
            tot[roles[k]] += b - a
    span = hi - lo
    return tot[1] / span, tot[2] / span, len(ever_presence_honest)


def job(args):
    proto, f0, eps, adv_name, rule_name, seed = args
    net = Network(NetConfig(n=N, seed=seed, eps_late=eps, **NET))
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol=proto, tau_ms=TAU, leader_rule=make_rule(rule_name, proto),
                    byzantine=list(range(N - f0, N)), adversary=make_adv(adv_name, f0), timeout_votes=(proto == "P1"),
                    track_signed=True)
    t0 = time.time()
    r = engine_fast.run(cfg, net)
    E = r.know[:, r.honest].min(axis=1)
    slot = np.diff(E)[WARM:VIEWS - 10]
    lead = r.leaders[WARM + 1:VIEWS - 9]
    hon_b, byz_b, pres_h = barred_time(r.rule_log, r.roles, WARM, VIEWS)
    return dict(proto=proto, f0=f0, eps=eps, adversary=adv_name, rule=rule_name, seed=seed,
                slot_ms=float(slot.mean()), colluder_share=float(np.mean(r.roles[lead] == 2)),
                honest_barred=hon_b, colluder_barred=byz_b, honest_presence_convicted=pres_h,
                secs=time.time() - t0)


def main():
    t0 = time.time()
    jobs = [(p, f0, e, a, rn, s) for p in ("P2", "P1") for f0 in (6, 10) for e in (0.0, 0.05)
            for a in ADVS[p] for rn in RULES for s in range(SEEDS)]
    with Pool(PROCS) as pool:
        rows = pool.map(job, jobs, chunksize=1)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "dirNRC_loop.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("| 协议 | f0 | ε | 对手 | " + " | ".join(RULES) + " |")
    print("|---|---|---|---|" + "---|" * len(RULES))
    for p in ("P2", "P1"):
        for f0 in (6, 10):
            for e in (0.0, 0.05):
                for a in ADVS[p]:
                    cells = []
                    for rn in RULES:
                        G = [r for r in rows if (r["proto"], r["f0"], r["eps"], r["adversary"], r["rule"]) == (p, f0, e, a, rn)]
                        m = lambda c: np.mean([r[c] for r in G])
                        cells.append(f"{m('slot_ms'):.0f} ms · {m('colluder_share'):.2f} · 诚实 {m('honest_barred'):.2f}"
                                     f"（{max(r['honest_presence_convicted'] for r in G)}）· 同伙 {m('colluder_barred'):.1f}")
                    print(f"| {p} | {f0} | {e} | {a} | " + " | ".join(cells) + " |")
    print("格式：平均槽位 · 同伙领导份额 · 诚实节点平均被禁数（因在场分被定罪过的诚实节点数，各种子取最大）· 同伙平均被禁数")
    print(f"wall {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

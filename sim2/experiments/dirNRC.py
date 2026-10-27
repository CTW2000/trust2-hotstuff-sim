"""NR self-contradiction (G1; 证据扩展_NR矛盾与包含证言_设计.md, part 1). Abstract models only.
v0.2 (after review/NR矛盾_审查.md): presence over views with a proposal and from receipts no single
assembler can drop; slot-score metrics report honest-led and colluder-led scores and their gap.
v0.1 results: results/dirNRC_tight_v01.csv, dirNRC_dilemma_v01.csv.

Part "tight" (E-NRC2, AT): colluders partially send in their own views so that the plain AT misses
them by exactly m = 3 NR signatures (the honest recipients are k = (n - f0) - q + m), and lie in
honest leaders' views (NR=1); a share g of them is greedy (votes and lies, so it is caught).
Post hoc: proven liars |K|; AT detection of the colluders' partial sends and AT accusations of
honest leaders, plain (2f+1 of all) vs tightened (q - |K| of the replicas outside K, K from views
before the fact).
Part "slot" (E-NRC2, slot score): colluders lie in reports (+inf for honest leaders, 0 for their
own views) with a share g greedy (caught); no partial sending. Mean slot score of honest-led and of
colluder-led views: truthful, plain (all reports), pool without K keeping the (f+1)-th smallest,
pool without K with the (f-|K|+1)-th smallest.
Part "dilemma" (E-NRC3, presence): colluder strategies in honest leaders' views: "honest",
"greedy" (vote + NR=1), "consistent" (withhold + NR=1), "withhold" (withhold, truthful NR),
"withhold_r" (withhold with probability 0.5 per view), and "frame" (colluders follow the protocol
but leave honest replica 0 out of every QC they form). Presence = share of views with a proposal in
which presence evidence exists (schedule.presence_seen).
Environment: SIM_PROCS (default 8), SIM_SEEDS (default 2).
Run from the repository root:  python -m sim2.experiments.dirNRC [tight|slot|dilemma]
"""
import csv
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

from sim2 import adversary as A
from sim2 import engine_event
from sim2 import schedule as S
from sim2.common import RunConfig, State
from sim2.net import NetConfig, Network

OUT = os.path.join(os.path.dirname(__file__), "..", "results")
N = 31
F = (N - 1) // 3
Q = (N + F) // 2 + 1
PROCS = int(os.environ.get("SIM_PROCS", "8"))
SEEDS = int(os.environ.get("SIM_SEEDS", "2"))
VIEWS = 3000
PROTOS = (("P2", False), ("P1", True))
LO, HI = 50, VIEWS - 10


def run(proto, tv, f0, eps, seed, adv):
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol=proto, leader_rule=S.Uniform(),
                    byzantine=list(range(N - f0, N)), adversary=adv, timeout_votes=tv, track_signed=True)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps)), st, 1, VIEWS)
    return cfg, st


def caught_cum(st):
    con = st.nr1 & (st.vote_seen | st.qc_pub)
    return con, np.logical_or.accumulate(con, axis=0)


def tight_job(args):
    proto, tv, f0, eps, g, seed = args
    m = 3
    adv = A.Compose([A.PartialSend((N - f0) - Q + m), A.LieNRVote(greedy=g)])
    cfg, st = run(proto, tv, f0, eps, seed, adv)
    con, cum = caught_cum(st)
    det_p, det_t, fa_p, fa_t = [], [], [], []
    for u in range(LO, HI):
        K = cum[u - 1]                                   # proofs from earlier views
        plain = bool(st.nr1[u].sum() >= Q)
        tight = S.accused_tight(st, u, K)
        if st.byz[st.leaders[u]]:
            det_p.append(plain)
            det_t.append(tight)
        else:
            fa_p.append(plain)
            fa_t.append(tight)
    return dict(proto=proto, f0=f0, eps=eps, greedy=g, seed=seed, K_final=int(cum[-1].sum()),
                detect_plain=float(np.mean(det_p)), detect_tight=float(np.mean(det_t)),
                false_acc_plain=float(np.mean(fa_p)), false_acc_tight=float(np.mean(fa_t)),
                nr_double=int((st.nr_count != st.nr1.sum(axis=1)).sum()))


def slot_job(args):
    proto, tv, f0, eps, g, seed = args
    cfg, st = run(proto, tv, f0, eps, seed, A.LieNRVote(greedy=g, claim=True))
    con, cum = caught_cum(st)
    out = {k: ([], []) for k in ("truth", "plain", "keep", "shift")}
    for u in range(LO, HI):
        K = cum[u - 1]
        side = 1 if st.byz[st.leaders[u]] else 0
        out["truth"][side].append(S.slot_score(st, u, lie=False))
        out["plain"][side].append(S.slot_score(st, u))
        out["keep"][side].append(S.slot_score(st, u, excl=K))
        out["shift"][side].append(S.slot_score(st, u, excl=K, shift_index=True))
    row = dict(proto=proto, f0=f0, eps=eps, greedy=g, seed=seed, K_final=int(cum[-1].sum()))
    for k, (h, b) in out.items():
        row[f"honest_{k}"] = float(np.mean(h))
        row[f"colluder_{k}"] = float(np.mean(b)) if b else float("nan")
    return row


STRATS = {
    "honest": None,
    "greedy": lambda: A.LieNRVote(greedy=1.0, claim=True),
    "consistent": lambda: A.LieNRVote(greedy=0.0, claim=True),
    "withhold": lambda: A.LieNRVote(greedy=0.0, claim=False),
    "withhold_r": lambda: A.LieNRVote(greedy=0.0, claim=False, wp=0.5),
    "frame": lambda: A.PresenceFrame(targets=(0,)),
}


def dilemma_job(args):
    proto, tv, f0, eps, strat, seed = args
    mk = STRATS[strat]
    cfg, st = run(proto, tv, f0, eps, seed, None if mk is None else mk())
    con, cum = caught_cum(st)
    rows = [u for u in range(LO, HI) if st.prop_parent[u] >= 0]
    pres = S.presence_seen(st, rows).mean(axis=0)
    hon = np.flatnonzero(st.honest)
    others = hon[hon != 0]
    hl = [u for u in range(LO, HI) if st.honest[st.leaders[u]]]
    failed = [not S.succeeded(st.prop_parent, u, VIEWS) for u in hl]
    acc = [bool(st.nr1[u].sum() >= Q) for u in hl]
    slot = np.diff(st.know[:, st.honest].min(axis=1))[LO:HI]
    return dict(proto=proto, f0=f0, eps=eps, strategy=strat, seed=seed, K_final=int(cum[-1][st.byz].sum()),
                presence_colluders=float(pres[st.byz].mean()), presence_colluders_max=float(pres[st.byz].max()),
                presence_honest_min=float(pres[others].min()), presence_target=float(pres[0]),
                honest_led_failed=float(np.mean(failed)), honest_leader_accused=float(np.mean(acc)),
                mean_slot_ms=float(slot.mean()))


def main():
    part = sys.argv[1] if len(sys.argv) > 1 else "tight"
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    if part == "tight":
        jobs = [(p, tv, f0, e, g, s) for p, tv in PROTOS for f0 in (3, 6, 10) for e in (0.0, 0.05)
                for g in (0.0, 1 / 3, 2 / 3, 1.0) for s in range(SEEDS)]
        with Pool(PROCS) as pool:
            rows = pool.map(tight_job, jobs, chunksize=1)
        print("| 协议 | f0 | ε | 贪心比例 | 期末 |K| | 部分发送检出：原 AT / 收紧 | 诚实领导者被指控：原 / 收紧 | NR 重复计数视图 |")
        print("|---|---|---|---|---|---|---|---|")
        for p, _ in PROTOS:
            for f0 in (3, 6, 10):
                for e in (0.0, 0.05):
                    for g in (0.0, 1 / 3, 2 / 3, 1.0):
                        G = [r for r in rows if (r["proto"], r["f0"], r["eps"], r["greedy"]) == (p, f0, e, g)]
                        m = lambda c: np.mean([r[c] for r in G])
                        print(f"| {p} | {f0} | {e} | {g:.2f} | {m('K_final'):.1f} | {m('detect_plain'):.3f} / "
                              f"{m('detect_tight'):.3f} | {m('false_acc_plain'):.4f} / {m('false_acc_tight'):.4f} | "
                              f"{m('nr_double'):.0f} |")
    elif part == "slot":
        jobs = [(p, tv, f0, e, g, s) for p, tv in PROTOS for f0 in (3, 6, 10) for e in (0.0, 0.05)
                for g in (0.0, 1 / 3, 2 / 3, 1.0) for s in range(SEEDS)]
        with Pool(PROCS) as pool:
            rows = pool.map(slot_job, jobs, chunksize=1)
        print("| 协议 | f0 | ε | 贪心比例 | |K| | 如实：诚实 / 同伙 | 原（全部报告）：诚实 / 同伙 | 清洗 K、保留第 f+1 小 | 清洗 K、改取第 f−k+1 小 |")
        print("|---|---|---|---|---|---|---|---|---|")
        for p, _ in PROTOS:
            for f0 in (3, 6, 10):
                for e in (0.0, 0.05):
                    for g in (0.0, 1 / 3, 2 / 3, 1.0):
                        G = [r for r in rows if (r["proto"], r["f0"], r["eps"], r["greedy"]) == (p, f0, e, g)]
                        m = lambda c: np.mean([r[c] for r in G])
                        cell = lambda k: f"{m('honest_' + k):.1f} / {m('colluder_' + k):.1f}"
                        print(f"| {p} | {f0} | {e} | {g:.2f} | {m('K_final'):.1f} | {cell('truth')} | {cell('plain')} | "
                              f"{cell('keep')} | {cell('shift')} |")
    else:
        eps_list = (0.0, 0.05, 0.10, 0.25)
        jobs = [(p, tv, f0, e, stn, s) for p, tv in PROTOS for f0 in (3, 6, 10) for e in eps_list
                for stn in STRATS for s in range(SEEDS)]
        with Pool(PROCS) as pool:
            rows = pool.map(dilemma_job, jobs, chunksize=1)
        print("| 协议 | f0 | ε | 同伙策略 | 被证明说谎 | 同伙在场分（均值 / 最高） | 诚实在场分最低（不含 0 号） | 0 号诚实节点 | 诚实领导视图失败 | 诚实领导者被 AT 指控 | 平均槽位 ms |")
        print("|---|---|---|---|---|---|---|---|---|---|---|")
        for p, _ in PROTOS:
            for f0 in (3, 6, 10):
                for e in eps_list:
                    for stn in STRATS:
                        G = [r for r in rows if (r["proto"], r["f0"], r["eps"], r["strategy"]) == (p, f0, e, stn)]
                        m = lambda c: np.mean([r[c] for r in G])
                        print(f"| {p} | {f0} | {e} | {stn} | {m('K_final'):.1f}/{f0} | {m('presence_colluders'):.3f} / "
                              f"{max(r['presence_colluders_max'] for r in G):.3f} | "
                              f"{min(r['presence_honest_min'] for r in G):.3f} | {m('presence_target'):.3f} | "
                              f"{m('honest_led_failed'):.3f} | {m('honest_leader_accused'):.4f} | {m('mean_slot_ms'):.1f} |")
    with open(os.path.join(OUT, f"dirNRC_{part}.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wall {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

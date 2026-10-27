"""Direction A v0.4 (方向A_收集者问责.md): compare four evidence schemes against the framings of an
honest collector (A2', late proposal) and of an honest leader (withholding collector), with and
without the collector's TC-wait rule, against fixed, adaptive and focused adversaries.
Abstract models only.

Schemes (P1, vote-carrying timeouts, rec_tau(u) = at least tau vote-carrying timeouts of u):
  old     failed proposer only (the leader of every orphaned block is charged);
  A_q     leader charged iff orphaned and not rec_q; collector charged iff orphaned and rec_q (v0.1);
  A_tau   the same with tau = q + floor(f/2) (identifiability threshold, theorem A4);
  pair    leader charged on every orphaned block, collector also when rec_q (pair evidence A5).
With a collector record, every collector turn is an opportunity of the collector's own estimate.
Wait rule (cfg.tc_wait_ms = delta_fwd + delta_max of the network): an honest leader that entered
its view by a TC without the previous QC waits that long before proposing; replicas vote only
while still in the view.

Part "attr": uniform leaders; adversary "double" (CollectorFraming as collector of an honest leader
+ PartialFrameCollector as leader with an honest collector) or "late" (LateProposalFramer), each
without and with the wait rule. Charge rates per opportunity are computed post hoc for all schemes.
Part "collapse": the M1/E2 threshold rule (ForgetThreshold theta = 0.1, W = 50, K = 1000,
rho_nat = 0.01) under each scheme against the informed AdaptiveFramer (spread, and focused on one
victim at a time), with the wait rule; plus A_tau without the wait rule (the late proposal is then
a free attack). The adversary always runs the attacks that never charge it (free_attacks) and the
others only while its own estimate stays below 0.5 * theta.
Earlier runs (v0.3, no wait rule, no late-proposal attack): results/dirA2_*_v03.csv; the first run
against a fixed double framing and an uninformed adaptive adversary:
results/dirA2_collapse_v1_double_and_naive_adaptive.csv (both destroy themselves).
Run from the repository root:  python -m sim2.experiments.dirA2 [attr|collapse]
Environment: SIM_PROCS = worker processes (default 8), SIM_SEEDS = seeds per cell (default 2).
"""
import csv
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

from sim2 import adversary as A
from sim2 import engine_fast
from sim2 import schedule as S
from sim2.common import RunConfig, State
from sim2.net import NetConfig, Network

OUT = os.path.join(os.path.dirname(__file__), "..", "results")
N = 31
F = (N - 1) // 3
Q = (N + F) // 2 + 1
TAU_HI = Q + F // 2
SCHEMES = ("old", "A_q", "A_tau", "pair")


def charges(r, views):
    """Post-hoc per-replica (charged, opportunities) under each scheme (no forgetting)."""
    out = {s: (np.zeros(N), np.zeros(N)) for s in SCHEMES}
    for u in range(1, views - 10):
        L, C = r.leaders[u], r.leaders[u + 1]
        failed = not S.succeeded(r.prop_parent, u, views)
        rq, rt = r.tmo_votes[u] >= Q, r.tmo_votes[u] >= TAU_HI
        for s in SCHEMES:
            Fc, Oc = out[s]
            Oc[L] += 1
            if s == "old":
                Fc[L] += failed
                continue
            rc = rt if s == "A_tau" else rq
            Fc[L] += failed if s == "pair" else (failed and not rc)
            Oc[C] += 1
            Fc[C] += failed and rc
    return out


def wait_ms(net):
    return net.delta_fwd() + net.delta_max()


def attr_job(args):
    f0, eps, seed, adv_name, wait = args
    views = 3000
    byz = list(range(N - f0, N))
    if adv_name == "double":
        adv = A.Compose([A.CollectorFraming(omit_tmo_votes=True), A.PartialFrameCollector()])
    else:
        adv = A.LateProposalFramer()
    net = Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps))
    cfg = RunConfig(n=N, views=views, seed=seed, protocol="P1", leader_rule=S.Uniform(), byzantine=byz,
                    adversary=adv, timeout_votes=True, tc_wait_ms=wait_ms(net) if wait else None)
    r = engine_fast.run(cfg, net)
    hon, bz = r.honest, r.roles == 2
    rows = []
    for s, (Fc, Oc) in charges(r, views).items():
        rate = np.divide(Fc, Oc, out=np.zeros(N), where=Oc > 0)
        rows.append(dict(f0=f0, eps=eps, seed=seed, adversary=adv_name, wait=wait, scheme=s,
                         honest_rate=float(Fc[hon].sum() / Oc[hon].sum()), honest_max=float(rate[hon].max()),
                         colluder_rate=float(Fc[bz].sum() / Oc[bz].sum()), colluder_min=float(rate[bz].min())))
    return rows


def free_attacks(scheme, f0, wait):
    """Attacks that never charge the attacker under the scheme (model S, theorem A4).
    Without the wait rule the late proposal frames an honest collector for every tau <= n-1, so it
    is free under A_q and A_tau for every f0; with the wait rule it orphans nothing."""
    if scheme == "old":
        return ("withhold",)                     # the honest leader is charged, never the collector
    if scheme == "A_q":
        return ("a2p",)                          # rec_q holds: the honest collector is blamed
    if scheme == "A_tau":
        if f0 > F // 2:
            return ("withhold", "a2p")           # beyond the identifiability bound both are free
        return () if wait else ("late",)
    return ()


def make_rule(scheme):
    kw = dict(theta=0.1, W=50, K=1000.0, prior=0.01)
    if scheme == "old":
        return S.ForgetThreshold(evidence="failed", **kw)
    if scheme == "A_q":
        return S.ForgetThreshold(evidence="failed_A", blame_collector=True, **kw)
    if scheme == "A_tau":
        return S.ForgetThreshold(evidence="failed_A", blame_collector=True, rec_tau=TAU_HI, **kw)
    return S.ForgetThreshold(evidence="failed_A", blame_collector=True, pair=True, **kw)


def collapse_job(args):
    scheme, adv_name, wait, f0, seed = args
    views = 10000
    byz = list(range(N - f0, N))
    rule = make_rule(scheme)
    adv = A.AdaptiveFramer(rule, free=free_attacks(scheme, f0, wait), focus=(adv_name == "focused"))
    net = Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0))
    cfg = RunConfig(n=N, views=views, seed=seed, protocol="P1", leader_rule=rule, rho_nat=0.01, byzantine=byz,
                    adversary=adv, timeout_votes=True, tc_wait_ms=wait_ms(net) if wait else None)
    t0 = time.time()
    r = engine_fast.run(cfg, net)
    share = (r.roles[r.leaders[1:views + 1]] == 2).astype(float)
    half = share[views // 2:]
    # estimates at the end of the run, recomputed from the final facts (low tier: estimate >= theta)
    st = State(cfg)
    st.prop_parent[: views + 1] = r.prop_parent[: views + 1]
    st.tmo_votes[: views + 1] = r.tmo_votes[: views + 1]
    st.leaders[: views + 2] = r.leaders[: views + 2]
    st._lead_known = views + 1
    est = make_rule(scheme).rates(views, st)
    return dict(scheme=scheme, adversary=adv_name, wait=wait, f0=f0, beta0=f0 / N, seed=seed,
                lam_half=float(half.mean()), lam_last5pct=float(half[-len(half) // 10:].mean()),
                honest_low_tier=int((est[r.honest] >= 0.1).sum()), colluder_low_tier=int((est[r.roles == 2] >= 0.1).sum()),
                secs=time.time() - t0)


F0S = (1, 2, 3, 4, 5, 6, 9)
PROCS = int(os.environ.get("SIM_PROCS", "8"))
SEEDS = int(os.environ.get("SIM_SEEDS", "2"))


def main():
    part = sys.argv[1] if len(sys.argv) > 1 else "attr"
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    if part == "attr":
        jobs = [(f0, e, s, a, wt) for a in ("double", "late") for wt in (False, True) for f0 in (1, 3, 5, 6, 10)
                for e in (0.0, 0.05) for s in range(SEEDS)]
        with Pool(PROCS) as pool:
            rows = [x for part_rows in pool.map(attr_job, jobs) for x in part_rows]
        print("| 对手 | 等待规则 | f0 | ε | " + " | ".join(f"{s}：诚实 / 同伙" for s in SCHEMES) + " |")
        print("|---|---|---|---|" + "---|" * len(SCHEMES))
        for a in ("double", "late"):
            for wt in (False, True):
                for f0 in (1, 3, 5, 6, 10):
                    for e in (0.0, 0.05):
                        cells = []
                        for s in SCHEMES:
                            g = [r for r in rows if (r["adversary"], r["wait"], r["f0"], r["eps"], r["scheme"]) == (a, wt, f0, e, s)]
                            cells.append(f"{np.mean([r['honest_rate'] for r in g]):.3f} / "
                                         f"{np.mean([r['colluder_rate'] for r in g]):.3f}")
                        print(f"| {a} | {'有' if wt else '无'} | {f0} | {e} | " + " | ".join(cells) + " |")
    else:
        jobs = [(sc, adv, True, f0, s) for adv in ("adaptive", "focused") for sc in SCHEMES for f0 in F0S
                for s in range(SEEDS)]
        jobs += [("A_tau", adv, False, f0, s) for adv in ("adaptive", "focused") for f0 in F0S for s in range(SEEDS)]
        with Pool(PROCS) as pool:
            rows = pool.map(collapse_job, jobs, chunksize=1)
        cols = [(sc, True) for sc in SCHEMES] + [("A_tau", False)]
        for adv in ("adaptive", "focused"):
            print(f"\n对手：知情{'+集中' if adv == 'focused' else '（分散）'}。同伙领导份额（后半段 / 最后 5%）；"
                  f"括号内为期末低档的诚实 / 同伙节点数")
            print("| β0 | " + " | ".join(f"{sc}{'' if wt else '（无等待）'}" for sc, wt in cols) + " |")
            print("|---|" + "---|" * len(cols))
            for f0 in F0S:
                cells = []
                for sc, wt in cols:
                    g = [r for r in rows if (r["adversary"], r["scheme"], r["wait"], r["f0"]) == (adv, sc, wt, f0)]
                    cells.append(f"{np.mean([r['lam_half'] for r in g]):.3f} / {np.mean([r['lam_last5pct'] for r in g]):.3f}"
                                 f"（{np.mean([r['honest_low_tier'] for r in g]):.1f} / "
                                 f"{np.mean([r['colluder_low_tier'] for r in g]):.1f}）")
                print(f"| {f0 / N:.3f} | " + " | ".join(cells) + " |")
    with open(os.path.join(OUT, f"dirA2_{part}.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wall {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

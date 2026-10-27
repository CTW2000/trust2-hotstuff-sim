"""Regression checks for the v0.5 features (review 信任2.0_v05_审查_代码 #1-#4, #8, #10):
- CusumExclusion soft queue: a hard conviction after a dropped soft entry is logged as hard and lowers
  T_tru reputation; the soft CUSUM is capped while queued and reset on a drop; soft history never raises
  the hard CUSUM; the weight-based cap queue is strict FIFO;
- e3_violators on synthetic positive and negative records, and on the adversarial schedule of 理论 命题 3(b);
- vote_monotone (R3): no vote for a view at or below a view the replica already signed;
- soft evidence ("noqc") runs compute leaders from final facts (verify_leaders == 0);
- weighted slot-duration evidence ("slot"): slow leaders score far above honest views, and slot runs
  compute leaders from final facts;
- weighted due threshold of the transaction layer: no honest leader flagged in model S;
- proposal forwarding ("hdr", "full") neutralizes a targeted partial send.
Run from the repository root:  python -m sim2.tests.test_v05   (or pytest: test_v05)"""
import sys
import time

import numpy as np

from sim2 import adversary as A
from sim2 import engine_event
from sim2 import schedule as S
from sim2 import ttru
from sim2.common import RunConfig, State
from sim2.net import NetConfig, Network
from sim2.txlayer import TxAdversary, TxConfig, TxLayer

N4 = 4


def synth(rule, views=400):
    cfg = RunConfig(n=N4, views=views, leader_rule=rule, lag=10)
    st = State(cfg)
    st.leaders[:] = 3
    st._lead_known = views + 2
    st.qc_exists[:] = True
    return st


def at(st, u, k):
    st.leaders[u] = k
    st.nr_count[u] = st.cfg.quorum


def noqc(st, u, k):
    st.leaders[u] = k
    st.qc_exists[u] = False


def soft_rule(**kw):
    return S.CusumExclusion(q=0.5, rho_bar=0.01, evidence="at", soft_evidence="noqc", soft_rho=0.3, soft_q=0.9, **kw)


def check_queue():
    bad = 0
    # (1) soft entry dropped, later hard conviction queued -> dequeued as hard, reputation drops
    rule = soft_rule(D=200, cap=0.25, Wq=50)
    st = synth(rule)
    for u in (1, 2, 3):
        at(st, u, 0)
    for u in range(10, 19):
        noqc(st, u, 1)
    for u in (180, 181, 182):
        at(st, u, 1)
    tw = ttru.TtruWeights(np.full(N4, 1 / N4), epoch=50, rule=rule)
    for v in range(1, 400, 50):
        tw(st, v)
    ev1 = [e[0] for e in st.rule_log if e[1] == 1 and e[0].startswith("exclude")]
    r1 = min(r[1] for r in st.__dict__["_ttru_cache"][id(tw)]["rs"])
    print(f"soft drop then hard conviction: exclusions {ev1}, min reputation {r1:.2f}")
    bad += ev1 != ["exclude"] or r1 >= 1.0
    # (2) soft re-conviction while queued must not raise the hard CUSUM
    rule = soft_rule(D=1000, cap=0.25, Wq=1000)
    st = synth(rule, 600)
    for u in (1, 2, 3):
        at(st, u, 0)
    for u in range(10, 28):
        noqc(st, u, 1)
    at(st, 40, 1)
    for v in range(1, 60):
        rule._advance(st, v)
    s = rule._state(st)
    print(f"soft history, one AT fact: hard W {s['W'][1]:.2f} (< h {rule.h:.2f}), soft W2 {s['W2'][1]:.2f}, queue {s['queue']}")
    bad += s["W"][1] >= rule.h or s["W2"][1] > rule.h + 1e-9 or [e[2] for e in s["queue"]] != [True]
    # (3) soft CUSUM reset on a drop
    rule = soft_rule(D=400, cap=0.25, Wq=50)
    st = synth(rule)
    for u in (1, 2, 3):
        at(st, u, 0)
    for u in range(10, 40):
        noqc(st, u, 1)
    noqc(st, 100, 1)
    for v in range(1, 120):
        rule._advance(st, v)
    log1 = [e[0] for e in st.rule_log if e[1] == 1]
    print(f"soft CUSUM after a drop: events {log1}")
    bad += log1 != ["queue", "drop"]
    # (4) strict FIFO under the weight cap
    w = np.array([0.30, 0.30, 0.10, 0.30])
    rule = S.CusumExclusion(q=0.5, rho_bar=0.01, D=1000, cap=0.5, Wq=60, evidence="at", cap_weights=w)
    st = synth(rule)
    for u in (1, 2, 3):
        at(st, u, 0)
    for u in (10, 11, 12):
        at(st, u, 1)
    for u in (20, 21, 22):
        at(st, u, 2)
    for v in range(1, 160):
        rule._advance(st, v)
    order = [(e[0], e[1]) for e in st.rule_log if e[0] in ("exclude", "queue")]
    print(f"weight cap FIFO: {order}")
    bad += ("exclude", 2) in order[:3]
    return bad


def check_e3():
    cfg = RunConfig(n=8, views=50)
    cases = [([(3, 10, 8)], [(3, 12, 7)], {3}), ([(3, 10, 8)], [(3, 10, 7)], {3}), ([(3, 10, 8)], [(3, 9, 5)], set()),
             ([(3, 10, 8)], [(3, 12, 8)], set()), ([(3, 10, 8)], [(2, 12, 7)], set()),
             ([(4, 5, 3), (4, 20, 18)], [(4, 10, 4), (4, 25, 17)], {4}), ([(5, 7, 6)], [(5, 9, 4)], {5})]
    bad = 0
    for votes, tmos, expect in cases:
        st = State(cfg)
        st.sig_votes, st.sig_tmos = list(votes), list(tmos)
        bad += set(int(k) for k in np.flatnonzero(S.e3_violators(st))) != expect
    print(f"e3_violators synthetic: {len(cases) - bad}/{len(cases)} correct")
    return bad


def check_monotone():
    n = 31
    late = {}
    for mono in (False, True):
        cfg = RunConfig(n=n, views=300, seed=1, protocol="P2", leader_rule=S.Uniform(), byzantine=[28, 29, 30],
                        track_signed=True, vote_monotone=mono)
        st = State(cfg)
        engine_event.simulate(cfg, Network(NetConfig(n=n, seed=1, regions=3, jitter_max_ms=2.0, eps_late=0.2)), st, 1, 300)
        top, n_late = {}, 0
        for kind, k, v in st.sig_order:           # signing order
            if kind == "vote" and v <= top.get(k, -1):
                n_late += 1
            top[k] = max(top.get(k, -1), v)
        late[mono] = n_late
    print(f"votes signed at or below an already signed view: off {late[False]}, R3 on {late[True]}")
    return late[True] != 0 or late[False] == 0


def check_e3_positive():
    from sim2.experiments.dirTtruE3 import positive
    off, on = positive(False), positive(True)
    print(f"E3 positive control (adversarial schedule): honest E3 without R3 {off}, with R3 {on}")
    return not off or bool(on)


def check_soft_stale():
    from sim2.experiments.dirTtru import N, cheapest_set, evade_k, setup
    cls, s, base, cost = setup(0, 1.0)
    byz = cheapest_set(base, cost, 0.2)
    stale = 0
    for adv in (A.Compose([A.LieNR(), A.WithholdVotesOnHonest()]), A.PartialSend(evade_k(base, byz, 2 / 3), targeted=True)):
        mk = lambda: soft_rule(D=500, cap=0.5, Wq=500, cap_weights=base)  # noqa: E731
        r1 = mk()
        cfg = RunConfig(n=N, views=700, seed=0, protocol="P2", leader_rule=r1, byzantine=list(np.flatnonzero(byz)),
                        adversary=adv, vote_weights=ttru.TtruWeights(base, epoch=100, rule=r1), at_share=2 / 3)
        res = engine_event.run(cfg, Network(NetConfig(n=N, seed=0, regions=3, jitter_max_ms=2.0, eps_late=0.2)))
        r2 = mk()
        cfg2 = RunConfig(n=N, views=700, seed=0, protocol="P2", leader_rule=r2, byzantine=list(np.flatnonzero(byz)),
                         vote_weights=ttru.TtruWeights(base, epoch=100, rule=r2), at_share=2 / 3)
        stale += S.verify_leaders(res, cfg2)
    print(f"soft evidence runs (eps 0.2): leaders from stale facts {stale}")
    return stale != 0


def check_slot():
    """Weighted slot-duration evidence: slow colluding leaders score far above honest views, and a
    weighted run with the "slot" soft evidence computes leaders from final facts."""
    from sim2.experiments.dirTtru import N, cheapest_set, setup
    cls, s, base, cost = setup(0, 1.0)
    byz = cheapest_set(base, cost, 0.2)
    cfg = RunConfig(n=N, views=500, seed=0, protocol="P2", leader_rule=S.Uniform(), byzantine=list(np.flatnonzero(byz)),
                    adversary=A.SlowLeader(1800.0), vote_weights=lambda st, v: base)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=0, regions=3, jitter_max_ms=2.0)), st, 1, 500)
    sc = np.array([S.weighted_slot_score(st, u) for u in range(20, 480)])
    lead = st.leaders[20:480]
    hon_max, byz_min = float(sc[st.honest[lead]].max()), float(sc[st.byz[lead]].min())
    print(f"weighted slot score: honest-led max {hon_max:.0f} ms, slow colluder-led min {byz_min:.0f} ms")
    bad = not (hon_max < 400.0 < byz_min)
    mk = lambda: S.CusumExclusion(q=0.5, rho_bar=0.1, evidence="at", soft_evidence="slot", soft_rho=0.7,  # noqa: E731
                                  soft_q=0.9, D=500, cap=0.5, Wq=500, cap_weights=base)
    r1 = mk()
    adv = A.Compose([A.LieNR(), A.WithholdVotesOnHonest(), A.SlowLeader(1800.0)])
    cfg = RunConfig(n=N, views=700, seed=0, protocol="P2", leader_rule=r1, byzantine=list(np.flatnonzero(byz)),
                    adversary=adv, vote_weights=ttru.TtruWeights(base, epoch=100, rule=r1), at_share=2 / 3,
                    slot_theta_ms=400.0)
    res = engine_event.run(cfg, Network(NetConfig(n=N, seed=0, regions=3, jitter_max_ms=2.0, eps_late=0.1)))
    r2 = mk()
    cfg2 = RunConfig(n=N, views=700, seed=0, protocol="P2", leader_rule=r2, byzantine=list(np.flatnonzero(byz)),
                     vote_weights=ttru.TtruWeights(base, epoch=100, rule=r2), at_share=2 / 3, slot_theta_ms=400.0)
    stale = S.verify_leaders(res, cfg2)
    print(f"slot soft evidence run (framing + slow leader, eps 0.1): leaders from stale facts {stale}")
    return bad or stale != 0


def check_forwarding():
    """Proposal forwarding: off by default (the regression covers it); with "hdr" or "full" a targeted
    partial send no longer fails views (eps = 0)."""
    from sim2.experiments.dirTtru import N, cheapest_set, evade_k, setup
    from sim2.experiments.ttru_perf import perf
    cls, s, base, cost = setup(0, 1.0)
    byz = cheapest_set(base, cost, 0.2)
    out = {}
    for fwd in (None, "hdr", "full"):
        cfg = RunConfig(n=N, views=500, seed=0, protocol="P2", leader_rule=S.Uniform(), byzantine=list(np.flatnonzero(byz)),
                        adversary=A.PartialSend(evade_k(base, byz, 2 / 3), targeted=True), vote_weights=lambda st, v: base,
                        prop_forward=fwd)
        st = State(cfg)
        engine_event.simulate(cfg, Network(NetConfig(n=N, seed=0, regions=3, jitter_max_ms=2.0)), st, 1, 500)
        out[fwd] = perf(st, 100, 490)["commit"]
    print(f"targeted partial send, committed share: no forwarding {out[None]:.3f}, header {out['hdr']:.3f}, full {out['full']:.3f}")
    return out[None] > 0.9 or out["hdr"] < 0.99 or out["full"] < 0.99


def check_tx_weighted():
    from sim2.experiments.dirTtru import N, cheapest_set, setup
    cls, s, base, cost = setup(1, 1.0)
    byz = cheapest_set(base, cost, 0.2)
    nw = Network(NetConfig(n=N, seed=1, regions=3, jitter_max_ms=2.0))
    tl = TxLayer(TxConfig(threshold="w", adversary=TxAdversary(frame=1.0, conflict=0.3), seed=1), nw)
    cfg = RunConfig(n=N, views=500, seed=1, protocol="P2", leader_rule=S.Uniform(), byzantine=list(np.flatnonzero(byz)),
                    vote_weights=lambda st, v: base, txlayer=tl)
    st = State(cfg)
    engine_event.simulate(cfg, nw, st, 1, 500)
    sx = tl.advance(st, 497)
    hl = [u for u in range(20, 490) if st.honest[st.leaders[u]] and st.qc_exists[u]]
    flagged = float(np.mean([sx["omit"][u] for u in hl]))
    print(f"weighted due threshold, model S with framing: honest-led views flagged {flagged:.3f}")
    return flagged != 0.0


def main():
    t0 = time.time()
    bad = check_queue() + check_e3() + check_e3_positive() + check_monotone() + check_soft_stale() + check_slot() + check_forwarding() + check_tx_weighted()
    print(f"({time.time() - t0:.0f}s)")
    if bad:
        print(f"FAILED: {bad}")
        sys.exit(1)
    print("ALL V0.5 CHECKS PASSED")


def test_v05():
    main()


if __name__ == "__main__":
    main()

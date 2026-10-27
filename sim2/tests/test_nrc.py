"""NR self-contradiction (G1) checks: the soundness hard check (theorem NRC-1: no honest replica is
ever caught, in any network model and against every adversary), detection of greedy liars, the
lag of the liar set, and the tightened AT / slot score.
Run from the repository root:  python -m sim2.tests.test_nrc"""
import sys
import time

import numpy as np

from sim2 import adversary as A
from sim2 import engine_event, engine_fast
from sim2 import schedule as S
from sim2.common import RunConfig, State
from sim2.net import NetConfig, Network

NETS = {
    "S": dict(regions=3, jitter_max_ms=2.0),
    "P05": dict(regions=3, jitter_max_ms=2.0, eps_late=0.05),
    "P15": dict(regions=3, jitter_max_ms=2.0, eps_late=0.15, late_extra_ms=400.0),
    "async": dict(regions=3, jitter_max_ms=2.0, async_views=150, async_p=0.5, async_extra_ms=3000.0),
    "outage": dict(regions=3, jitter_max_ms=2.0, outage_p=0.02, outage_len=20, outage_extra_ms=3000.0),
}


def advs():
    return [None, A.LieNR(), A.LieNRVote(greedy=1.0), A.LieNRVote(greedy=0.5), A.LieNRVote(greedy=0.0, claim=False),
            A.WithholdVotesOnHonest(), A.CollectorFraming(), A.PartialSend(2), A.DataWithhold(1), A.SilentLeader(0.5),
            A.Compose([A.PartialSend(2, p=0.5), A.LieNRVote(greedy=0.5)]),
            A.Compose([A.CollectorFraming(), A.PartialFrameCollector()]), A.LateProposalFramer()]


def soundness():
    """Theorem NRC-1 as a hard check."""
    bad, runs, caught_byz = 0, 0, 0
    t0 = time.time()
    for proto, tv in (("P2", False), ("P1", False), ("P1", True)):
        for nname, p in NETS.items():
            for adv in advs():
                for nrd in (False, True):
                    n = 10
                    cfg = RunConfig(n=n, views=250, seed=runs % 3, protocol=proto, leader_rule=S.Uniform(),
                                    byzantine=[7, 8, 9], adversary=adv, timeout_votes=tv, track_signed=True,
                                    nr_requires_data=nrd, tau_ms=250.0 if nname == "P15" else 2000.0)
                    r = engine_fast.run(cfg, Network(NetConfig(n=n, seed=runs % 3, **p)))
                    con = r.nr1 & (r.vote_seen | r.qc_pub)
                    runs += 1
                    if not np.array_equal(r.nr_count, r.nr1.sum(axis=1)):
                        bad += 1                  # one timeout per sender and view (review M3)
                        print(f"[NR COUNT] {proto} tv={tv} {nname} {getattr(adv, 'name', None)}")
                    caught_byz += int(con[:, r.roles == 2].any(axis=0).sum())
                    if con[:, r.honest].any():
                        bad += 1
                        if bad <= 5:
                            u, k = np.argwhere(con[:, r.honest])[0]
                            print(f"[HONEST CAUGHT] {proto} tv={tv} {nname} {getattr(adv, 'name', None)} nrd={nrd}: view {u}")
    print(f"NRC-1 soundness: {runs} runs (P1/P2, with/without timeout votes, 5 networks incl. asynchrony and "
          f"outages, 13 adversaries, NR with/without data): honest replicas caught or NR double-counted in {bad} "
          f"runs; colluders caught {caught_byz} times in total ({time.time() - t0:.0f}s)")
    # other configurations (review M4): collector TC-wait (also longer than tau), parent data, natural
    # failures, no leave rule
    bad2, runs2 = 0, 0
    extras = [dict(tc_wait_ms=100.0), dict(tc_wait_ms=300.0, tau_ms=250.0), dict(tc_wait_ms=3000.0),
              dict(vote_needs_parent=True), dict(rho_nat=0.05), dict(tmo_after_leave=False)]
    for ex in extras:
        for proto, tv in (("P2", True), ("P1", True)):
            for nname in ("S", "P15", "async"):
                for adv in (None, A.LieNRVote(greedy=0.5), A.Compose([A.CollectorFraming(), A.PartialFrameCollector()])):
                    kw = dict(tau_ms=250.0 if nname == "P15" else 2000.0)
                    kw.update(ex)
                    cfg = RunConfig(n=10, views=250, seed=runs2 % 3, protocol=proto, leader_rule=S.Uniform(),
                                    byzantine=[7, 8, 9], adversary=adv, timeout_votes=tv, track_signed=True, **kw)
                    r = engine_fast.run(cfg, Network(NetConfig(n=10, seed=runs2 % 3, **NETS[nname])))
                    runs2 += 1
                    con = r.nr1 & (r.vote_seen | r.qc_pub)
                    if con[:, r.honest].any() or not np.array_equal(r.nr_count, r.nr1.sum(axis=1)):
                        bad2 += 1
                        if bad2 <= 5:
                            print(f"[EXTRA] {ex} {proto} {nname} {getattr(adv, 'name', None)}")
    print(f"NRC-1 soundness, other configurations (TC-wait incl. > tau, parent data, natural failures, no leave "
          f"rule): {runs2} runs, failing {bad2}")
    return bad + bad2 + (caught_byz == 0)


def detection_and_lag():
    bad = 0
    n, f0, views = 31, 6, 400
    cfg = RunConfig(n=n, views=views, seed=1, protocol="P2", leader_rule=S.Uniform(), byzantine=list(range(n - f0, n)),
                    adversary=A.LieNRVote(greedy=0.5), track_signed=True)
    r = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=n, seed=1, regions=3, jitter_max_ms=2.0)), r, 1, views)
    con = r.nr1 & r.vote_seen
    caught = con.any(axis=0)
    greedy = np.zeros(n, bool)
    greedy[np.flatnonzero(r.roles == 2)[:3]] = True
    print(f"greedy liars caught: {np.flatnonzero(caught).tolist()} (greedy: {np.flatnonzero(greedy).tolist()})")
    if not np.array_equal(caught, greedy):
        bad += 1
    # liars(st, v) only uses views u <= v - lag
    st = State(cfg)
    st.nr1[:] = r.nr1
    st.vote_seen[:] = r.vote_seen
    first = int(np.argmax(con.any(axis=1)))
    if S.liars(st, first + cfg.lag - 1).any() or not S.liars(st, first + cfg.lag).any():
        bad += 1
        print("[LAG] liar set read before the lag")
    # tightened AT: |K| proven liars lower the threshold by |K| and only count non-K signatures
    st2 = State(cfg)
    K = np.zeros(n, bool)
    K[[30, 29]] = True
    st2.nr1[5, :q_minus(cfg, 2)] = True          # q-2 honest NR=1
    plain = bool(st2.nr1[5].sum() >= cfg.quorum)
    tight = S.accused_tight(st2, 5, K)
    st2.nr1[5, [30, 29]] = True                  # signatures of K do not count
    tight2 = S.accused_tight(st2, 5, K)
    print(f"accused_tight: plain {plain}, tight {tight}, K signatures ignored {tight2}")
    if plain or not tight or not tight2:
        bad += 1
    # slot score: excl = empty set reproduces the plain score
    diff = max(abs(S.slot_score(r, u) - S.slot_score(r, u, excl=np.zeros(n, bool))) for u in range(20, 300))
    if diff > 0:
        bad += 1
        print(f"[SLOT] excl=empty changes the score by {diff}")
    return bad


def closed_loop():
    """Rule-layer integration: G1 bars proven liars at once; presence convicts vote withholders
    (P2, threshold 0.7) and no honest replica; schedules are computed from final facts."""
    bad = 0
    n, f0, views = 31, 6, 1200
    net = Network(NetConfig(n=n, seed=4, regions=3, jitter_max_ms=2.0))
    for adv, kw, what in ((A.LieNRVote(greedy=1.0), dict(g1=True), "g1"),
                          (A.LieNRVote(greedy=0.0, claim=False), dict(presence_theta=0.7, presence_window=200), "presence")):
        rule = S.PerfTilt(L=1 / 200, K=50, W=20, V=2000, clean=True,
                          exclusion=S.CusumExclusion(evidence="at", D=500, cap=0.5, Wq=500, **kw))
        cfg = RunConfig(n=n, views=views, seed=4, protocol="P2", leader_rule=rule, byzantine=list(range(n - f0, n)),
                        adversary=adv, track_signed=True)
        r = engine_fast.run(cfg, net)
        log = [e for e in r.rule_log if e[0] == what]
        hit = {k for _, k, _ in log}
        late = r.leaders[600:views + 1]
        share = float(np.mean(r.roles[late] == 2))
        stale = S.verify_leaders(r, cfg)
        print(f"closed loop ({what}): convicted {sorted(hit)}, colluder leader share after view 600 {share:.3f}, "
              f"stale leaders {stale}")
        if hit != set(range(n - f0, n)) or share > 0.02 or stale:
            bad += 1
    return bad


def q_minus(cfg, m):
    return cfg.quorum - m


def main():
    failures = soundness() + detection_and_lag() + closed_loop()
    if failures:
        print(f"FAILED: {failures}")
        sys.exit(1)
    print("ALL NRC CHECKS PASSED")


if __name__ == "__main__":
    main()

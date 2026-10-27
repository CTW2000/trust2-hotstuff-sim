"""Direct unit tests of the leader rules on hand-built facts (no protocol engine), because the
engine cross-check cannot catch rule bugs (both engines share the rule code).
Run from the repository root:  python -m sim2.tests.test_rules"""
import math
import sys

import numpy as np

from sim2 import schedule as S
from sim2.common import RunConfig, State


class FactState(State):
    """A State whose leaders and outcome facts are scripted: views led by `bad` replicas are accused."""

    def __init__(self, cfg, script_leaders, bad):
        super().__init__(cfg)
        self.leaders[: len(script_leaders)] = script_leaders
        self._lead_known = len(script_leaders) - 1
        for u, L in enumerate(script_leaders):
            if u >= 1 and L in bad:
                self.nr_count[u] = cfg.quorum


def run_rule(rule, n, leaders, bad, upto):
    cfg = RunConfig(n=n, views=len(leaders) + 20, leader_rule=rule, lag=10)
    st = FactState(cfg, leaders, bad)
    rule._advance(st, upto)
    return st


def main():
    fails = 0
    # 1. CUSUM increments and threshold: q = 0.5, rho_bar = 0.01, gamma = 1e4 -> up 3.912, h = 9.210
    rule = S.CusumExclusion(evidence="at", D=100)
    assert abs(rule.up - math.log(50)) < 1e-12 and abs(rule.h - math.log(1e4)) < 1e-12
    # replica 1 accused in its 1st, 2nd, 3rd led views -> excluded at its 3rd (3 * 3.912 >= 9.21)
    leaders = [-1] + [1, 0, 1, 0, 1, 0] + [0] * 20
    st = run_rule(rule, 4, leaders, {1}, 40)
    ex = [e for e in st.rule_log if e[0] == "exclude"]
    ok = ex == [("exclude", 1, 5)]
    print(f"CUSUM excludes replica 1 at its 3rd accused view (view 5): {ex} -> {'ok' if ok else 'FAIL'}")
    fails += not ok
    # 2. view-number expiry: released D = 100 views later
    rule = S.CusumExclusion(evidence="at", D=10)
    leaders = [-1] + [1, 0, 1, 0, 1] + [0] * 30
    st = run_rule(rule, 4, leaders, {1}, 45)
    rel = [e for e in st.rule_log if e[0] == "release"]
    ok = rel == [("release", 1, 15)]
    print(f"view expiry D=10: {rel} -> {'ok' if ok else 'FAIL'}")
    fails += not ok
    # 3. cap: at most floor(0.25 * 8) = 2 excluded; the third conviction is queued, then dropped after Wq,
    #    and must NOT be re-queued without new evidence (review M3)
    rule2 = S.CusumExclusion(evidence="at", D=1000, cap=0.25, Wq=5)
    leaders = [-1] + [1, 2, 3] * 3 + [0] * 40 + [3] * 3
    st2 = FactState(RunConfig(n=8, views=80, leader_rule=rule2, lag=10), leaders, set())
    for u in range(1, 10):                  # replicas 1, 2, 3 are accused only in views 1..9
        st2.nr_count[u] = st2.cfg.quorum
    rule2._advance(st2, 75)
    kinds = [(e[0], e[1]) for e in st2.rule_log]
    ok = kinds[:4] == [("exclude", 1), ("exclude", 2), ("queue", 3), ("drop", 3)] and kinds.count(("queue", 3)) == 1
    print(f"cap 2 of 8, queue, drop, no re-queue without evidence: {kinds} -> {'ok' if ok else 'FAIL'}")
    fails += not ok
    # 4. commit expiry: released after D further successful views (proxy: proposal extends the view)
    rule = S.CusumExclusion(evidence="at", D=3, expiry="commit")
    leaders = [-1] + [1, 0, 1, 0, 1] + [0] * 30
    st = FactState(RunConfig(n=4, views=60, leader_rule=rule, lag=10), leaders, {1})
    st.prop_parent[1:40] = np.arange(0, 39)       # every view extends the previous one: all succeed
    rule._advance(st, 45)
    rel = [e for e in st.rule_log if e[0] == "release"]
    ok = len(rel) == 1 and rel[0][2] == 8
    print(f"commit expiry D=3 (excluded at 5, successes at 6, 7, 8): {rel} -> {'ok' if ok else 'FAIL'}")
    fails += not ok
    # 5. slot_score: the score stays within the range of honest reports whatever colluders report
    #    or which reports a colluding assembler picks (b <= f), and a TC view scores at least tau
    rng = np.random.default_rng(1)
    bad_band = 0
    for trial in range(200):
        n = 10
        byz = [7, 8, 9]
        cfg = RunConfig(n=n, views=20, byzantine=byz, tau_ms=2000.0)
        st = State(cfg)
        st.know[0, :] = 0.0
        st.know[1, :] = rng.uniform(100, 400, n)
        st.know[0, :] = rng.uniform(0, 50, n)
        st.leaders[1] = int(rng.integers(n))
        st.leaders[2] = int(rng.integers(n))
        H = np.flatnonzero(st.honest)
        e = st.know[1, H] - st.know[0, H]
        x = S.slot_score(st, 1, lie=True)
        if not (e.min() - 1e-9 <= x <= e.max() + 1e-9):
            bad_band += 1
    st.tc_exists[1] = True
    floor_ok = S.slot_score(st, 1) >= 2000.0
    ok = bad_band == 0 and floor_ok
    print(f"slot_score within honest band in 200 random lying cases (violations {bad_band}), TC floor {floor_ok} -> {'ok' if ok else 'FAIL'}")
    fails += not ok
    # 6. PerfTilt weights: within [1/K, 1]; a replica slower than the baseline gets a lower weight;
    #    samples older than V views are replaced by the baseline
    rule = S.PerfTilt(L=1 / 100, K=20, W=4, V=50)
    cfg = RunConfig(n=4, views=200, leader_rule=rule, lag=10)
    st = State(cfg)
    st.leaders[:] = -1
    st._lead_known = 10**9
    s = rule._scores(st, 11)                     # initialise the cache, then script samples
    s["samples"] = [[(100, 150.0)] * 4, [(100, 160.0)] * 4, [(100, 400.0)] * 4, [(5, 900.0)] * 4]
    s["done"] = 10**9
    w = rule.weights(110, st)
    ok = (np.all(w >= 1 / 20 - 1e-12) and np.all(w <= 1 + 1e-12) and w[2] < w[0]
          and abs(w[3] - 1.0) < 1e-12)           # replica 3's samples are stale -> neutral weight 1
    print(f"PerfTilt weights {np.round(w, 3)} (bounded, slow replica down-weighted, stale replica neutral) -> {'ok' if ok else 'FAIL'}")
    fails += not ok
    if fails:
        print(f"FAILED: {fails}")
        sys.exit(1)
    print("ALL RULE UNIT TESTS PASSED")


if __name__ == "__main__":
    main()

"""M0 checks: engine cross-check, forwarding coverage, commits, analytic case, invariants.
Run from the repository root:
    python -m sim2.tests.test_m0
"""
import sys
import time

import numpy as np

from sim2 import engine_event, engine_fast
from sim2.common import RunConfig, block_parents, commit_times
from sim2.net import NetConfig, Network, uniform_network

PRESETS = {
    "3reg_j2": dict(regions=3, jitter_max_ms=2.0),
    "6reg_j10": dict(regions=6, jitter_max_ms=10.0, region_c0_ms=8.0),
    "1reg_j1": dict(regions=1, jitter_max_ms=1.0),
    # violates the triangle inequality by more than the slack, so forwarded certificates can beat
    # a replica's own vote count (review B2); used with a short timeout
    "tri_violate": dict(regions=2, region_c0_ms=1.0, region_c1_ms=20.0, access_lo_ms=0.0,
                        access_hi_ms=1.0, jitter_max_ms=15.0),
    # model P: messages late beyond the timeout with probability eps
    "P_eps1e-2": dict(regions=3, jitter_max_ms=2.0, eps_late=0.01),
    "P_eps5e-2": dict(regions=3, jitter_max_ms=2.0, eps_late=0.05),
}
MODEL_S = ("3reg_j2", "6reg_j10", "1reg_j1", "tri_violate")
TAU_OVERRIDE = {"tri_violate": 60.0}
# jitter comparable to the slot time: known to produce cert(v) before cert(v-1) (review §2)
ANOMALY_PRONE = dict(regions=1, region_c0_ms=0.0, access_lo_ms=0.0, access_hi_ms=0.01, jitter_max_ms=10.0)


def same(a, b):
    both_inf = np.isinf(a) & np.isinf(b)
    return bool(np.all(both_inf | np.isclose(a, b, rtol=0, atol=1e-9)))


def compare(cfg, net, check_qc_know=True):
    re = engine_event.run(cfg, net)
    rf = engine_fast.run(cfg, net)
    alive = rf.alive
    parts = {
        "know": same(rf.know, re.know),
        "qc_know": (not check_qc_know) or same(rf.qc_know, re.qc_know),
        "cert_type": np.array_equal(rf.cert_type[:, alive], re.cert_type[:, alive]),
        "cert_hq": np.array_equal(rf.cert_hq[:, alive], re.cert_hq[:, alive]),
        "qc_exists": np.array_equal(rf.qc_exists, re.qc_exists),
        "tc_exists": np.array_equal(rf.tc_exists, re.tc_exists),
        "prop_parent": np.array_equal(rf.prop_parent, re.prop_parent),
    }
    if not all(parts.values()):
        bad = [k for k, ok in parts.items() if not ok]
        diff = np.argwhere(~(np.isclose(rf.know, re.know, atol=1e-9) | (np.isinf(rf.know) & np.isinf(re.know))))
        return "MISMATCH", f"differs in {bad}; first know diffs (view, replica): {diff[:5].tolist()}", rf
    return "ok", "", rf


def scenarios(n):
    f = (n - 1) // 3
    yield "honest_rr", dict()
    yield "honest_random_leader", dict(leader_mode="random")
    yield "crash_f_replicas", dict(crashed=list(range(n - f, n)))
    yield "crash_one_leader_TC", dict(crashed=[1])
    yield "crash_f_random", dict(crashed=list(range(1, 1 + f)), leader_mode="random")
    yield "short_tau_mixed", dict(tau_ms=None)


def main():
    failures = 0
    assert RunConfig(n=4).quorum == 3 and RunConfig(n=5).quorum == 4 and RunConfig(n=100).quorum == 67
    stats = {"ok": 0, "MISMATCH": 0}
    fb_total = 0
    fwd_matters = 0
    t0 = time.time()
    for n in (4, 7, 10, 16):
        for pname, p in PRESETS.items():
            for seed in range(4):
                net = Network(NetConfig(n=n, seed=seed, **p))
                for sname, s in scenarios(n):
                    s = dict(s)
                    if s.get("tau_ms", 0) is None:
                        s["tau_ms"] = 2.2 * float(np.median(net.base[net.base > 0]))
                    elif pname in TAU_OVERRIDE:
                        s["tau_ms"] = TAU_OVERRIDE[pname]
                    cfg = RunConfig(n=n, views=150, seed=seed, **s)
                    status, msg, rf = compare(cfg, net)
                    stats[status] += 1
                    if rf is not None:
                        fb_total += rf.fallback_views
                    if status != "ok":
                        print(f"[{status}] n={n} {pname} seed={seed} {sname}: {msg}")
                        failures += 1
                    if pname == "tri_violate" and status == "ok":
                        cfg_nf = RunConfig(n=n, views=150, seed=seed, forward=False, **s)
                        r_nf = engine_event.run(cfg_nf, net)
                        fwd_matters += not same(r_nf.know, rf.know)
    print(f"cross-check: {stats}, fallback views exercised: {fb_total}, {time.time() - t0:.1f}s")
    print(f"forwarding changes the outcome in {fwd_matters} of {4 * 4 * 6} tri_violate runs")
    if fwd_matters == 0:
        print("FAILED: forwarding path not exercised")
        failures += 1

    # anomaly-prone network: the fast engine re-solves windows with the event engine; the result
    # must equal the global event engine (qc_know of pre-window views may differ, see engine_event)
    windows, mism, qc_diff = 0, 0, 0
    for seed in range(40):
        for n in (4, 7):
            net = Network(NetConfig(n=n, seed=seed, **ANOMALY_PRONE))
            cfg = RunConfig(n=n, views=300, seed=seed)
            st, msg, rf = compare(cfg, net, check_qc_know=False)
            windows += rf.window_views > 0
            if st != "ok":
                mism += 1
                print(f"[anomaly-window MISMATCH] n={n} seed={seed}: {msg}")
            qc_diff += not same(rf.qc_know, engine_event.run(cfg, net).qc_know)
    print(f"anomaly-prone: {windows} of 80 runs needed event-engine windows; mismatches {mism}; "
          f"runs with differing pre-window qc_know {qc_diff}")
    if windows == 0 or mism:
        failures += 1

    # TC highQC coverage: scenarios where TCs carry a highQC older than v-1, plus a planted bug
    # (timeouts report a highQC one view too low in the fast engine) that the cross-check must catch
    hq_scen = [
        lambda s: (NetConfig(n=7, seed=s, regions=3, jitter_max_ms=2.0),
                   RunConfig(n=7, views=150, seed=s, crashed=[1, 2])),
        lambda s: (NetConfig(n=7, seed=s, regions=3, jitter_max_ms=2.0, eps_late=0.15, late_extra_ms=400.0),
                   RunConfig(n=7, views=150, seed=s, tau_ms=250.0)),
    ]
    old_hq = agree = caught = 0
    for mk in hq_scen:
        for s in range(4):
            nc, rc = mk(s)
            net = Network(nc)
            st, msg, rf = compare(rc, net)
            agree += st == "ok"
            if st != "ok":
                print(f"[highQC MISMATCH] seed={s}: {msg}")
            V = rf.know.shape[0]
            old_hq += int(((rf.cert_hq < np.arange(V)[:, None] - 1) & (rf.cert_type == 2)).sum())
            orig = engine_fast.held_qc
            engine_fast.held_qc = lambda qk, k, t, upto: max(0, orig(qk, k, t, upto) - 1)
            try:
                caught += compare(rc, net)[0] != "ok"
            finally:
                engine_fast.held_qc = orig
    print(f"TC highQC: {agree}/8 runs agree; {old_hq} TC certs carry a highQC older than v-1; "
          f"planted highQC bug caught in {caught}/8 runs")
    if agree < 8 or old_hq == 0 or caught < 6:
        failures += 1

    # parents after TC views: block v extends the highest QC'd view below it
    r = engine_fast.run(RunConfig(n=4, views=40, tau_ms=100.0, crashed=[1]), uniform_network(4, 10.0))
    par = block_parents(r)
    for v in range(2, 41):
        if par[v] >= 0:
            expect = max(u for u in range(v) if r.qc_exists[u])
            assert par[v] == expect, f"block {v} extends {par[v]}, expected {expect}"
    # analytic TC case: n=4, replica 1 (leader of 2, 6, 10, ...) crashed, uniform delay 10, tau 100
    alive = r.alive
    assert np.all(r.cert_type[2, alive] == 2) and np.all(r.cert_hq[2, alive] == 1), "TC(2) must carry highQC 1"
    assert all(par[v] == -1 for v in range(2, 41, 4)), "a crashed leader's view must have no block"
    print("parents after TC views: ok (TC(2).highQC = 1; no blocks for crashed leaders)")

    # analytic: uniform delay d, no jitter -> every view takes exactly 2d, commit latency 4d
    d = 10.0
    for n in (4, 16):
        r = engine_fast.run(RunConfig(n=n, views=50), uniform_network(n, d))
        assert np.allclose(r.know, (2 * d * np.arange(51))[:, None]), "uniform network: view time is not 2d"
        c = commit_times(r)
        assert np.allclose(c[1:49, 0] - r.know[0:48, 0], 4 * d), "uniform network: commit latency is not 4d"
    # indirect commits after TC views (review B1): crashed leader of views 2, 6, 10, ...
    r = engine_fast.run(RunConfig(n=4, views=30, tau_ms=100.0, crashed=[1]), uniform_network(4, d))
    c = commit_times(r)
    proposed = [v for v in range(1, 27) if r.alive[r.leaders[v]]]
    missing = [v for v in proposed if np.isnan(c[v, 0])]
    assert not missing, f"blocks never committed: {missing}"
    print(f"analytic checks: ok (view 2d, commit 4d; block 1 commits at t={c[1, 0]:.0f} via indirect commit)")

    # invariants (PM): honest entry skew <= Delta_fwd, |e_j - S_t| <= Delta_fwd
    worst_skew, worst_dist = 0.0, 0.0
    for pname in MODEL_S:
        p = PRESETS[pname]
        for seed in range(3):
            for crashed in ([], list(range(21, 31))):
                net = Network(NetConfig(n=31, seed=seed, **p))
                tau = TAU_OVERRIDE.get(pname, 2000.0)
                r = engine_fast.run(RunConfig(n=31, views=300, seed=seed, leader_mode="random",
                                              crashed=crashed, tau_ms=tau), net)
                D = net.delta_fwd()
                k = r.know[:, r.alive]
                skew = (k.max(1) - k.min(1)).max() / D
                E = k.min(1)
                dist = np.abs((k[1:] - k[:-1]) - np.diff(E)[:, None]).max() / D
                worst_skew, worst_dist = max(worst_skew, skew), max(worst_dist, dist)
                if skew > 1 + 1e-9 or dist > 1 + 1e-9:
                    print(f"FAILED invariant: {pname} seed {seed} crashed={len(crashed)}")
                    failures += 1
    print(f"invariants: max entry skew = {worst_skew:.3f} Delta_fwd, max |e_j - S_t| = {worst_dist:.3f} Delta_fwd (<= 1)")

    if failures:
        print(f"FAILED: {failures} problems")
        sys.exit(1)
    print("ALL M0 CHECKS PASSED")


if __name__ == "__main__":
    main()

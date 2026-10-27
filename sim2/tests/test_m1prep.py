"""Checks for the refactored architecture: P1, Byzantine roles with adversary plans, dynamic leaders.
Run from the repository root:  python -m sim2.tests.test_m1prep"""
import sys
import time

import numpy as np

from sim2 import adversary as A
from sim2 import engine_event, engine_fast
from sim2 import schedule as S
from sim2.common import RunConfig
from sim2.net import NetConfig, Network, uniform_network
from sim2.tests.test_m0 import PRESETS, TAU_OVERRIDE, same


def compare(cfg, net):
    re, rf = engine_event.run(cfg, net), engine_fast.run(cfg, net)
    al = rf.alive
    parts = {
        "know": same(rf.know, re.know), "qc_know": same(rf.qc_know, re.qc_know),
        "cert_type": np.array_equal(rf.cert_type[:, al], re.cert_type[:, al]),
        "cert_hq": np.array_equal(rf.cert_hq[:, al], re.cert_hq[:, al]),
        "qc_exists": np.array_equal(rf.qc_exists, re.qc_exists),
        "tc_exists": np.array_equal(rf.tc_exists, re.tc_exists),
        "prop_parent": np.array_equal(rf.prop_parent, re.prop_parent),
        "leaders": np.array_equal(rf.leaders, re.leaders),
    }
    return [k for k, ok in parts.items() if not ok], rf, re


def failed_honest_rate(r):
    """Fraction of views led by honest replicas recorded as failed (schedule.succeeded is False:
    the first proposal sent after the view does not extend its block)."""
    V = r.know.shape[0] - 1
    us = [u for u in range(1, V - 10) if r.honest[r.leaders[u]]]
    return np.mean([not S.succeeded(r.prop_parent, u, V) for u in us]), len(us)


def main():
    failures = 0
    t0 = time.time()

    # 1. P1 cross-check over the same presets and scenarios as M0, plus Byzantine adversaries
    stats = {"ok": 0, "bad": 0}
    advs = [None, A.CollectorFraming(), A.WithholdVotesOnHonest(), A.SilentLeader(), A.PartialSend(1),
            A.Compose([A.CollectorFraming(), A.PartialSend(1)])]
    for proto in ("P1", "P2"):
        for n in (4, 7, 10):
            f = (n - 1) // 3
            for pname, p in PRESETS.items():
                for seed in range(2):
                    net = Network(NetConfig(n=n, seed=seed, **p))
                    tau = TAU_OVERRIDE.get(pname, 2000.0)
                    for adv in advs:
                        for mode in ("round_robin", "random"):
                            cfg = RunConfig(n=n, views=120, seed=seed, protocol=proto, tau_ms=tau,
                                            leader_mode=mode, byzantine=list(range(n - f, n)) if adv else [],
                                            adversary=adv)
                            diff, rf, _ = compare(cfg, net)
                            stats["ok" if not diff else "bad"] += 1
                            if diff:
                                failures += 1
                                if stats["bad"] <= 8:
                                    print(f"[MISMATCH] {proto} n={n} {pname} seed={seed} "
                                          f"{adv.name if adv else 'none'} {mode}: {diff}")
    print(f"P1/P2 x adversaries cross-check: {stats} ({time.time() - t0:.0f}s)")

    # 2. P1 analytic: uniform delay d -> the collector enters v+1 at 2d after entering v, others d later
    d = 10.0
    r = engine_fast.run(RunConfig(n=4, views=40, protocol="P1"), uniform_network(4, d))
    for v in range(1, 40):
        C = r.leaders[v + 1]
        others = np.arange(4) != C
        assert np.isclose(r.know[v, C], 2 * d * v), f"P1 collector timing wrong at view {v}"
        assert np.allclose(r.know[v, others], 2 * d * v + d), f"P1 replica timing wrong at view {v}"
    print("P1 analytic check: ok (collector enters after 2d, others after 3d)")

    # 3. Framing rates against theory (round robin, n = 31, f = 10 Byzantine at the end)
    n, f = 31, 10
    byz = list(range(n - f, n))
    net_s = Network(NetConfig(n=n, seed=5, regions=3, jitter_max_ms=2.0))
    # P1, model S: honest leader framed iff the next leader is Byzantine
    r = engine_fast.run(RunConfig(n=n, views=930, protocol="P1", byzantine=byz,
                                  adversary=A.CollectorFraming()), net_s)
    rate, cnt = failed_honest_rate(r)
    V = r.know.shape[0] - 1
    expect = np.mean([r.roles[r.leaders[u + 1]] == 2 for u in range(1, V - 10) if r.honest[r.leaders[u]]])
    print(f"P1 collector framing, model S: honest failure rate {rate:.3f} (theory: share of Byzantine next leaders {expect:.3f})")
    if abs(rate - expect) > 1e-9:
        failures += 1
    # P2, model S: withholding votes cannot frame (r = 1 needs an honest timing fault)
    r = engine_fast.run(RunConfig(n=n, views=930, protocol="P2", byzantine=byz,
                                  adversary=A.WithholdVotesOnHonest()), net_s)
    rate, _ = failed_honest_rate(r)
    print(f"P2 vote withholding, model S: honest failure rate {rate:.3f} (theory: 0)")
    if rate != 0:
        failures += 1
    # P2, model P: an honest leader fails iff one of the other 2f honest replicas misses the proposal
    for eps in (0.005, 0.01):
        rates = []
        for seed in range(3):
            net_p = Network(NetConfig(n=n, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps))
            r = engine_fast.run(RunConfig(n=n, views=1500, protocol="P2", byzantine=byz, seed=seed,
                                          adversary=A.WithholdVotesOnHonest()), net_p)
            rates.append(failed_honest_rate(r)[0])
        theory = 1 - (1 - eps) ** (2 * f)
        print(f"P2 vote withholding, model P eps={eps}: honest failure rate {np.mean(rates):.3f} "
              f"(theory 1-(1-eps)^(2f) = {theory:.3f})")
        if abs(np.mean(rates) - theory) > 0.25 * theory + 0.01:
            failures += 1

    # 4. Dynamic leaders: both engines compute leaders independently (lag consistency)
    rules = [S.Uniform(), S.ExpProfile(eta=5.0, horizon=60), S.Tiers(theta=0.1, K=20, horizon=30),
             S.CarouselLike(horizon=15), S.ForgetExp(eta=4.0, W=50, prior=0.01),
             S.ForgetThreshold(theta=0.1, W=50, prior=0.01)]
    dyn = {"ok": 0, "bad": 0}
    for proto, adv in (("P1", A.CollectorFraming()), ("P2", A.WithholdVotesOnHonest())):
        for rule in rules:
            for seed in range(3):
                for pname in ("3reg_j2", "P_eps5e-2"):
                    n = 10
                    net = Network(NetConfig(n=n, seed=seed, **PRESETS[pname]))
                    cfg = RunConfig(n=n, views=200, seed=seed, protocol=proto, leader_rule=rule,
                                    byzantine=[7, 8, 9], adversary=adv, rho_nat=0.05 * (seed % 2))
                    diff, rf, re = compare(cfg, net)
                    stale = S.verify_leaders(rf, cfg) + S.verify_leaders(re, cfg)
                    dyn["ok" if not diff and not stale else "bad"] += 1
                    if diff or stale:
                        failures += 1
                        print(f"[DYN MISMATCH] {proto} {rule.name} seed={seed} {pname}: {diff}, stale leaders {stale}")
    print(f"dynamic-leader cross-check + post-hoc recompute from final facts: {dyn}")

    # 5. Dynamic rules react to framing: under P1 collector framing, R1 should raise the
    #    Byzantine leader share above its base share (the D4 feedback loop) while R0 should not
    n, byz = 31, list(range(21, 31))
    net = Network(NetConfig(n=n, seed=2, regions=3, jitter_max_ms=2.0))
    shares = {}
    for rule in (S.Uniform(), S.ExpProfile(eta=8.0, horizon=300)):
        r = engine_fast.run(RunConfig(n=n, views=3000, seed=2, protocol="P1", leader_rule=rule,
                                      byzantine=byz, adversary=A.CollectorFraming()), net)
        shares[rule.name] = np.mean(r.roles[r.leaders[1000:3001]] == 2)
    print(f"Byzantine leader share under P1 framing: R0 {shares['R0_uniform']:.3f}, "
          f"R1(eta=8) {shares['R1_exp']:.3f} (base share {len(byz) / n:.3f})")
    if not shares["R1_exp"] > shares["R0_uniform"] + 0.03:
        failures += 1

    # 6. TC kernel: coverage and planted bugs (the cross-check must catch them)
    cases = []
    heavy = dict(regions=3, jitter_max_ms=2.0, eps_late=0.15, late_extra_ms=400.0)
    for proto, adv in (("P1", A.CollectorFraming()), ("P2", A.WithholdVotesOnHonest()),
                       ("P2", A.SilentLeader()), ("P1", A.PartialSend(1))):
        for pname in ("3reg_j2", "P_eps5e-2", "tri_violate", "heavy_late_short_tau"):
            for seed in range(2):
                n = 7
                p = heavy if pname == "heavy_late_short_tau" else PRESETS[pname]
                tau = 250.0 if pname == "heavy_late_short_tau" else TAU_OVERRIDE.get(pname, 2000.0)
                cases.append((NetConfig(n=n, seed=seed, **p),
                              RunConfig(n=n, views=150, seed=seed, protocol=proto, tau_ms=tau,
                                        byzantine=[5, 6], adversary=adv, leader_mode="random")))
    tck, agree = 0, 0
    for nc, rc in cases:
        d, rf, _ = compare(rc, Network(nc))
        agree += not d
        tck += rf.tc_kernel_views
    orig = engine_fast._closure_labels
    engine_fast._closure_labels = lambda x, lab, W: orig(x, np.maximum(lab - 1, 0), W)
    try:
        caught = sum(bool(compare(rc, Network(nc))[0]) for nc, rc in cases)
    finally:
        engine_fast._closure_labels = orig
    # the fixed point and late votes only matter in extreme timing (scenarios from the refactor review)
    anom = dict(regions=1, region_c0_ms=0.0, access_lo_ms=0.0, access_hi_ms=0.01, jitter_max_ms=10.0)
    hard = []
    for seed in range(5):
        for proto, adv in (("P1", A.CollectorFraming()), ("P2", A.SilentLeader())):
            hard.append((NetConfig(n=7, seed=seed, **anom),
                         RunConfig(n=7, views=200, seed=seed, protocol=proto, tau_ms=25.0, byzantine=[5, 6],
                                   adversary=adv, leader_mode="random")))
            hard.append((NetConfig(n=7, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=0.3, late_extra_ms=150.0),
                         RunConfig(n=7, views=200, seed=seed, protocol=proto, tau_ms=120.0, byzantine=[5, 6],
                                   adversary=adv, leader_mode="random")))
    hard_ok = sum(not compare(rc, Network(nc))[0] for nc, rc in hard)
    mut_caught = {}
    for mut in ("no_fixed_point", "no_late_votes"):
        engine_fast._TEST_MUTATION = mut
        try:
            mut_caught[mut] = sum(bool(compare(rc, Network(nc))[0]) for nc, rc in hard)
        finally:
            engine_fast._TEST_MUTATION = None
    print(f"TC kernel extreme-timing runs: {hard_ok}/{len(hard)} agree")
    if hard_ok < len(hard):
        failures += 1
    print(f"TC kernel: {agree}/{len(cases)} agree, {tck} views solved by it; planted bugs caught: "
          f"label {caught}, no_fixed_point {mut_caught['no_fixed_point']}, "
          f"no_late_votes {mut_caught['no_late_votes']} (label: of {len(cases)} runs; others: of {len(hard)})")
    if agree < len(cases) or tck == 0 or caught < len(cases) // 2 or min(mut_caught.values()) == 0:
        failures += 1

    if failures:
        print(f"FAILED: {failures} problems")
        sys.exit(1)
    print(f"ALL M1-PREP CHECKS PASSED ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()

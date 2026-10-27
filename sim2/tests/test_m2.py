"""M2 checks: AT NR bits, CUSUM exclusion rules, exclusion cap, pre-GST asynchrony.
Run from the repository root:  python -m sim2.tests.test_m2"""
import sys
import time

import numpy as np

from sim2 import adversary as A
from sim2 import engine_event, engine_fast
from sim2 import schedule as S
from sim2.common import RunConfig
from sim2.net import NetConfig, Network
from sim2.tests.test_m0 import PRESETS, same


def compare(cfg, net):
    re, rf = engine_event.run(cfg, net), engine_fast.run(cfg, net)
    al = rf.alive
    parts = {
        "know": same(rf.know, re.know), "qc_know": same(rf.qc_know, re.qc_know),
        "cert_type": np.array_equal(rf.cert_type[:, al], re.cert_type[:, al]),
        "cert_hq": np.array_equal(rf.cert_hq[:, al], re.cert_hq[:, al]),
        "prop_parent": np.array_equal(rf.prop_parent, re.prop_parent),
        "leaders": np.array_equal(rf.leaders, re.leaders),
        "nr_count": np.array_equal(rf.nr_count, re.nr_count),
        "rule_log": rf.rule_log == re.rule_log,
    }
    stale = S.verify_leaders(rf, cfg)
    return [k for k, ok in parts.items() if not ok] + (["stale_leaders"] if stale else []), rf


def main():
    failures = 0
    t0 = time.time()
    rules = [None,
             S.CusumExclusion(evidence="at", D=60),
             S.CusumExclusion(evidence="failed", rho_bar=0.2, D=60),
             S.CusumExclusion(evidence="at", D=60, cap=0.3, Wq=100),
             S.CusumExclusion(evidence="at", D=8, expiry="commit"),
             S.ForgetThreshold(theta=0.1, W=30, prior=0.01, evidence="at")]
    advs = [A.Compose([A.CollectorFraming(), A.LieNR()]), A.Compose([A.WithholdVotesOnHonest(), A.LieNR()]),
            A.SilentLeader(0.5), A.PartialSend(1, start_view=60)]
    nets = {"3reg_j2": PRESETS["3reg_j2"], "P_eps5e-2": PRESETS["P_eps5e-2"],
            "async": dict(regions=3, jitter_max_ms=2.0, async_views=60, async_p=0.5, async_extra_ms=3000.0),
            "async_honest_only": dict(regions=3, jitter_max_ms=2.0, async_views=60, async_p=0.6,
                                      async_extra_ms=3000.0, async_senders=list(range(7)))}
    stats = {"ok": 0, "bad": 0}
    nr_views = 0
    for proto in ("P1", "P2"):
        for rule in rules:
            for adv in advs:
                for nname, p in nets.items():
                    for seed in range(2):
                        n = 10
                        cfg = RunConfig(n=n, views=200, seed=seed, protocol=proto, leader_rule=rule,
                                        leader_mode="random", byzantine=[7, 8, 9], adversary=adv, rho_nat=0.02)
                        diff, rf = compare(cfg, Network(NetConfig(n=n, seed=seed, **p)))
                        nr_views += int((rf.nr_count > 0).sum())
                        stats["ok" if not diff else "bad"] += 1
                        if diff:
                            failures += 1
                            if stats["bad"] <= 8:
                                print(f"[MISMATCH] {proto} {rule.name if rule else 'static'} {adv.name} {nname} "
                                      f"seed={seed}: {diff}")
    print(f"M2 cross-check (AT bits, CUSUM rules, cap, async): {stats}; views with NR>0: {nr_views} "
          f"({time.time() - t0:.0f}s)")

    # AT soundness, model S: lying Byzantine NR bits cannot accuse an honest leader (r = f+1)
    n, byz = 31, list(range(21, 31))
    net = Network(NetConfig(n=n, seed=3, regions=3, jitter_max_ms=2.0))
    r = engine_fast.run(RunConfig(n=n, views=1500, seed=3, protocol="P1", leader_rule=S.Uniform(), byzantine=byz,
                                  adversary=A.Compose([A.CollectorFraming(), A.LieNR()])), net)
    hv = [u for u in range(1, 1490) if r.honest[r.leaders[u]]]
    acc_h = np.mean([r.nr_count[u] >= r.quorum for u in hv])
    fail_h = np.mean([not S.succeeded(r.prop_parent, u, 1500) for u in hv])
    print(f"P1 framing + lying NR, model S: honest failed-proposer rate {fail_h:.3f}, honest accusation rate {acc_h:.3f} (AT: 0)")
    if acc_h != 0 or fail_h < 0.2:
        failures += 1
    # AT completeness: a silent Byzantine leader is always accused; a partial sender (k=1) never
    for adv, expect in ((A.SilentLeader(1.0), 1.0), (A.PartialSend(1), 0.0)):
        r = engine_fast.run(RunConfig(n=n, views=1500, seed=4, protocol="P2", leader_rule=S.Uniform(), byzantine=byz,
                                      adversary=adv), net)
        bv = [u for u in range(1, 1490) if r.roles[r.leaders[u]] == 2]
        acc_b = np.mean([r.nr_count[u] >= r.quorum for u in bv])
        print(f"{adv.name}: Byzantine-leader accusation rate {acc_b:.3f} (TR: {expect})")
        if acc_b != expect:
            failures += 1

    # planted bug: Byzantine NR claims ignored in the TC kernel; the cross-check must catch it
    cases = []
    for proto in ("P1", "P2"):
        for seed in range(4):
            frame = A.CollectorFraming() if proto == "P1" else A.WithholdVotesOnHonest()
            cases.append((NetConfig(n=10, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=0.05),
                          RunConfig(n=10, views=200, seed=seed, protocol=proto, leader_rule=S.CusumExclusion(D=60),
                                    byzantine=[7, 8, 9], adversary=A.Compose([frame, A.LieNR(), A.SilentLeader(0.5)]),
                                    rho_nat=0.02)))
    engine_fast._TEST_MUTATION = "nr_no_lie"
    try:
        caught = sum(bool(compare(rc, Network(nc))[0]) for nc, rc in cases)
    finally:
        engine_fast._TEST_MUTATION = None
    print(f"planted NR-claim bug caught in {caught}/{len(cases)} runs")
    if caught == 0:
        failures += 1

    if failures:
        print(f"FAILED: {failures} problems")
        sys.exit(1)
    print(f"ALL M2 CHECKS PASSED ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()

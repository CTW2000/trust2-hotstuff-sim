"""M3 checks: block data / fetching, parent-data switch, per-recipient votes, tilt rule.
Run from the repository root:  python -m sim2.tests.test_m3"""
import sys
import time

import numpy as np

from sim2 import adversary as A
from sim2 import engine_fast
from sim2 import schedule as S
from sim2.common import RunConfig
from sim2.net import NetConfig, Network
from sim2.tests.test_m2 import compare


def main():
    failures = 0
    t0 = time.time()
    stats = {"ok": 0, "bad": 0}
    advs = [A.DataWithhold(k=1), A.DataWithhold(k=0), A.DataWithhold(k=1, p=0.5), A.SkewVotes(g=3),
            A.Compose([A.SkewVotes(g=3), A.DataWithhold(k=1), A.LieNR()])]
    rules = [None, S.PerfTilt(L=1 / 200, K=20, W=10, V=400, exclusion=S.CusumExclusion(evidence="at", D=200, cap=0.5))]
    nets = {"6reg": dict(regions=6, region_c0_ms=8.0, region_c1_ms=120.0, jitter_max_ms=10.0),
            "6reg_P": dict(regions=6, region_c0_ms=8.0, region_c1_ms=120.0, jitter_max_ms=10.0, eps_late=0.03)}
    fetch_views = 0
    for proto in ("P1", "P2"):
        for parent_switch in (False, True):
            for adv in advs:
                for rule in rules:
                    for nname, p in nets.items():
                        for seed in range(2):
                            cfg = RunConfig(n=10, views=250, seed=seed, protocol=proto, leader_rule=rule,
                                            leader_mode="random", byzantine=[7, 8, 9], adversary=adv,
                                            vote_needs_parent=parent_switch)
                            d, rf = compare(cfg, Network(NetConfig(n=10, seed=seed, **p)))
                            stats["ok" if not d else "bad"] += 1
                            if d:
                                failures += 1
                                if stats["bad"] <= 8:
                                    print(f"[MISMATCH] {proto} parent={parent_switch} {adv.name} "
                                          f"{rule.name if rule else 'static'} {nname} seed={seed}: {d}")
    print(f"M3 cross-check (data withholding, fetching, parent data, vote targets, tilt): {stats} ({time.time() - t0:.0f}s)")

    # data withholding with k = 0: the view fails but AT does not accuse (every honest replica got the header)
    n, byz = 31, list(range(22, 31))
    net = Network(NetConfig(n=n, seed=2, regions=3, jitter_max_ms=2.0))
    r = engine_fast.run(RunConfig(n=n, views=2000, seed=2, protocol="P2", leader_rule=S.Uniform(), byzantine=byz,
                                  adversary=A.DataWithhold(k=0)), net)
    bv = [u for u in range(1, 1990) if r.roles[r.leaders[u]] == 2]
    fail = np.mean([not S.succeeded(r.prop_parent, u, 2000) for u in bv])
    acc = np.mean([r.nr_count[u] >= r.quorum for u in bv])
    print(f"data withholding k=0: colluder views fail {fail:.3f}, accused by AT {acc:.3f} (expected 1 and 0)")
    if fail < 0.99 or acc > 0:
        failures += 1
    # fix: NR requires the data -> the same attack is accused; cross-check the fix in both engines
    cfgd = RunConfig(n=n, views=2000, seed=2, protocol="P2", leader_rule=S.Uniform(), byzantine=byz,
                     adversary=A.DataWithhold(k=0), nr_requires_data=True)
    rd = engine_fast.run(cfgd, net)
    accd = np.mean([rd.nr_count[u] >= rd.quorum for u in bv])
    hv = [u for u in range(1, 1990) if rd.honest[rd.leaders[u]]]
    acch = np.mean([rd.nr_count[u] >= rd.quorum for u in hv])
    print(f"with NR requiring the data: withholding colluder views accused {accd:.3f}, honest views accused {acch:.3f}")
    if accd < 0.99 or acch > 0:
        failures += 1
    agree = 0
    for seed in range(4):
        for proto in ("P1", "P2"):
            c = RunConfig(n=10, views=250, seed=seed, protocol=proto, leader_mode="random", byzantine=[7, 8, 9],
                          adversary=A.Compose([A.DataWithhold(k=0, p=0.5), A.LieNR()]), nr_requires_data=True,
                          leader_rule=S.CusumExclusion(evidence="at", D=100))
            agree += not compare(c, Network(NetConfig(n=10, seed=seed, regions=6, region_c0_ms=8.0,
                                                      region_c1_ms=120.0, jitter_max_ms=10.0, eps_late=0.03)))[0]
    print(f"NR-requires-data cross-check: {agree}/8 agree")
    if agree < 8:
        failures += 1
    # fetching makes the view slower but still successful (k = 1)
    r1 = engine_fast.run(RunConfig(n=n, views=2000, seed=2, protocol="P2", leader_rule=S.Uniform(), byzantine=byz,
                                   adversary=A.DataWithhold(k=1)), net)
    r0 = engine_fast.run(RunConfig(n=n, views=2000, seed=2, protocol="P2", leader_rule=S.Uniform(), byzantine=byz), net)
    E1 = np.diff(r1.know[:, r1.honest].min(1))
    E0 = np.diff(r0.know[:, r0.honest].min(1))
    bmask = r1.roles[r1.leaders[1:2001]] == 2
    fail1 = np.mean([not S.succeeded(r1.prop_parent, u, 2000) for u in bv])
    print(f"data withholding k=1: colluder views fail {fail1:.3f}; their slot {E1[bmask].mean():.0f} ms vs "
          f"{E0[bmask].mean():.0f} ms without withholding")
    if fail1 > 0.01 or not E1[bmask].mean() > E0[bmask].mean() + 20:
        failures += 1

    if failures:
        print(f"FAILED: {failures} problems")
        sys.exit(1)
    print(f"ALL M3 CHECKS PASSED ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()

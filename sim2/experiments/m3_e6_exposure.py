"""M3 / E6b: colluders' maximum leader share ("exposure") under the tilt rules: colluders withhold
votes in honest leaders' views (making honest slots slower) but never fail or slow their own views,
and lie in slot-duration reports. Abstract models only.
Run from the repository root:  python -m sim2.experiments.m3_e6_exposure"""
import csv
import os
from multiprocessing import Pool

import numpy as np

from sim2 import adversary as A
from sim2 import engine_fast
from sim2.common import RunConfig
from sim2.experiments.m3_e6_perf import N, NET, OUT, TAU, VIEWS, WARM, make_rule, rules
from sim2.net import NetConfig, Network


def job(args):
    rn, f0, seed = args
    net = Network(NetConfig(n=N, seed=seed, **NET))
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol="P2", tau_ms=TAU, leader_rule=make_rule(rules()[rn]),
                    byzantine=list(range(N - f0, N)), adversary=A.WithholdVotesOnHonest())
    r = engine_fast.run(cfg, net)
    lead = r.leaders[WARM + 1:VIEWS - 9]
    E = r.know[:, r.honest].min(axis=1)
    return dict(rule=rn, f0=f0, seed=seed, colluder_share=float(np.mean(r.roles[lead] == 2)),
                slot_ms=float(np.diff(E)[WARM:VIEWS - 10].mean()))


def main():
    jobs = [(rn, f0, s) for rn in rules() for f0 in (9, 3) for s in range(3)]
    with Pool(8) as pool:
        out = pool.map(job, jobs)
    with open(os.path.join(OUT, "m3_e6_exposure.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print("| 规则 | f0=9：同伙份额 | 平均槽位 | f0=3：同伙份额 | 平均槽位 |")
    print("|---|---|---|---|---|")
    for rn in rules():
        a = [o for o in out if o["rule"] == rn and o["f0"] == 9]
        b = [o for o in out if o["rule"] == rn and o["f0"] == 3]
        m = lambda g, c: np.mean([o[c] for o in g])
        print(f"| {rn} | {m(a, 'colluder_share'):.3f} | {m(a, 'slot_ms'):.0f} | {m(b, 'colluder_share'):.3f} | {m(b, 'slot_ms'):.0f} |")


if __name__ == "__main__":
    main()

"""Save outputs of the pre-refactor engines (M0 + M1 prerequisites) as golden files.
Run once from the repository root:  python -m sim2.tests.make_golden"""
import os
import numpy as np
from sim2 import engine_event, engine_fast
from sim2.common import RunConfig, commit_times
from sim2.net import NetConfig, Network
from sim2.tests.test_m0 import PRESETS, TAU_OVERRIDE, scenarios

OUT = os.path.join(os.path.dirname(__file__), "golden")


def cases():
    for n in (4, 10):
        for pname, p in PRESETS.items():
            for seed in (0, 1):
                net_kw = dict(n=n, seed=seed, **p)
                net = Network(NetConfig(**net_kw))
                for sname, s in scenarios(n):
                    s = dict(s)
                    if s.get("tau_ms", 0) is None:
                        s["tau_ms"] = 2.2 * float(np.median(net.base[net.base > 0]))
                    elif pname in TAU_OVERRIDE:
                        s["tau_ms"] = TAU_OVERRIDE[pname]
                    yield f"{n}_{pname}_{seed}_{sname}", net_kw, dict(n=n, views=120, seed=seed, **s)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    count = 0
    for name, net_kw, run_kw in cases():
        net = Network(NetConfig(**net_kw))
        r = engine_event.run(RunConfig(**run_kw), net)
        np.savez_compressed(os.path.join(OUT, name + ".npz"), know=r.know, qc_know=r.qc_know,
                            cert_type=r.cert_type, cert_hq=r.cert_hq, qc_exists=r.qc_exists,
                            tc_exists=r.tc_exists, prop_parent=r.prop_parent, leaders=r.leaders,
                            commit=commit_times(r))
        count += 1
    print("golden cases written:", count)

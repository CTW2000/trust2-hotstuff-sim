"""Regression: the refactored engines must reproduce the pre-refactor golden outputs exactly.
Run from the repository root:  python -m sim2.tests.test_regression"""
import os
import sys

import numpy as np

from sim2 import engine_event, engine_fast
from sim2.common import RunConfig, commit_times
from sim2.net import NetConfig, Network
from sim2.tests.make_golden import OUT, cases


def same(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a.shape != b.shape:
        return False
    nan = np.isnan(a) & np.isnan(b)
    inf = np.isinf(a) & np.isinf(b) & (np.sign(a) == np.sign(b))
    return bool(np.all(nan | inf | np.isclose(a, b, rtol=0, atol=1e-9)))


def check(r, g):
    al = r.alive
    parts = {
        "know": same(r.know, g["know"]), "qc_know": same(r.qc_know, g["qc_know"]),
        "cert_type": np.array_equal(r.cert_type[:, al], g["cert_type"][:, al]),
        "cert_hq": np.array_equal(r.cert_hq[:, al], g["cert_hq"][:, al]),
        "qc_exists": np.array_equal(r.qc_exists, g["qc_exists"]),
        "tc_exists": np.array_equal(r.tc_exists, g["tc_exists"]),
        "prop_parent": np.array_equal(r.prop_parent, g["prop_parent"]),
        "leaders": np.array_equal(r.leaders[1:len(g["leaders"])], g["leaders"][1:]),
        "commit": same(commit_times(r), g["commit"]),
    }
    return [k for k, ok in parts.items() if not ok]


def main():
    bad = 0
    total = 0
    for name, net_kw, run_kw in cases():
        g = np.load(os.path.join(OUT, name + ".npz"))
        net = Network(NetConfig(**net_kw))
        cfg = RunConfig(**run_kw)
        for eng in (engine_event, engine_fast):
            total += 1
            diff = check(eng.run(cfg, net), g)
            if diff:
                bad += 1
                if bad <= 10:
                    print(f"[REGRESSION] {eng.__name__.split('.')[-1]} {name}: {diff}")
    print(f"regression: {total - bad}/{total} engine runs reproduce the golden outputs")
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()

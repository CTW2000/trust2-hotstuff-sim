"""Test vectors for prototype/consensus/src/ttru.rs from the simulator's reference implementation.

Populations as in the simulations (sim2/ttru.py `population`: licensed / uncertified / small, Pareto stakes),
with the stakes rounded to integers (the prototype's base weights are integers); the reference base weights
are computed from those integers with `base_weights(..., K=0, pi=0, cap, u_max)`.
Run from the repository root:  python prototype/scripts/gen_ttru_vectors.py
"""
import json
import os

import numpy as np

from sim2 import ttru

OUT = os.path.join(os.path.dirname(__file__), "..", "consensus", "src", "tests", "ttru_vectors.json")
CASES = [  # (name, licensed, uncertified, small, cap, u_max, seed, pareto alpha)
    *[("n31", 10, 12, 9, 0.10, 0.25, s, 1.16) for s in range(5)],
    *[("n100", 20, 50, 30, 0.05, 0.25, s, 1.16) for s in range(3)],
    ("n31-heavy", 10, 12, 9, 0.10, 0.25, 0, 0.8),
    ("n31-umax15", 10, 12, 9, 0.10, 0.15, 1, 1.16),
    ("n7-loose", 4, 2, 1, 0.30, 0.25, 2, 1.16),
]


def main():
    out = []
    for name, nl, nu, na, cap, u_max, seed, alpha in CASES:
        cls, s = ttru.population(nl, nu, na, seed, alpha=alpha)
        w = np.rint(s * 1e12).astype(np.int64)
        base = ttru.base_weights(cls, w.astype(float), 0.0, 0.0, cap, u_max)
        out.append(dict(name=f"{name}-s{seed}", certified=[bool(c == "L") for c in cls], weights=[int(x) for x in w],
                        cap_ppm=round(cap * 1e6), u_max_ppm=round(u_max * 1e6), base=[float(x) for x in base]))
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1)
    print(f"{len(out)} cases -> {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()

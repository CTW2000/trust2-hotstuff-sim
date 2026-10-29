"""G1 test vectors for prototype/consensus/src/punish.rs from the simulator's graded punishment.

sim2/punish.py `GradedPunishment` (方案说明 v0.12 §3.3: levels L1-L4, suspension cap L_max with a FIFO queue,
governance stand-in, eviction with CapNorm recomputed for fork culprits) runs on scripted evidence items
(entity, class, sign epoch, chain epoch, malicious, fork); an item is visible at the table of epoch k when its
chain epoch is < k, as on the prototype's ledger. Parameters are the adopted defaults (repeat_evict=False).
Run from the repository root:  PYTHONPATH=. python prototype/scripts/gen_g1_vectors.py
"""
import json
import os

import numpy as np

from sim2 import ttru
from sim2.punish import GradedPunishment

OUT = os.path.join(os.path.dirname(__file__), "..", "consensus", "src", "tests", "g1_vectors.json")
EPOCHS = 60
CAP, U_MAX = 0.10, 0.25
PARAMS = dict(epoch=100, l_max=0.10, sus=(0, 0, 4, 32), lead_bar=1, win_chain=32, lookback=64, gov_delay=2,
              recompute="fork", repeat_evict=False)


class Scripted(GradedPunishment):
    """GradedPunishment fed with scripted evidence instead of simulated views and injections."""

    def __init__(self, *args, script=(), **kw):
        super().__init__(*args, **kw)
        self.script = sorted(script, key=lambda x: x[3])

    def _intake(self, st, k, horizon):
        while self.next_inj < len(self.script) and self.script[self.next_inj][3] < k:
            i, kind, es, ec, mal, fork = self.script[self.next_inj]
            self._add(i, kind, es, ec, mal, fork)
            self.next_inj += 1


def script_of(name, base, rng):
    n = len(base)
    order = list(np.argsort(base))                     # cheapest first
    if name == "live-repeat":                          # an NR liar caught again and again: L1, L2, L3, L3
        return [(3, "live", e, e, True, False) for e in (2, 5, 9, 12)] + [(7, "live", 20, 21, True, False)]
    if name == "iso":                                  # isolated client faults at random
        return [(int(rng.integers(n)), "safe", e, e, False, False) for e in range(2, EPOCHS - 5) if rng.random() < 0.15]
    if name == "safe-repeat":                          # one entity: L2, L3, then L4 downgraded to L3
        return [(5, "safe", e, e, False, False) for e in (3, 8, 13)]
    if name == "correlated":                           # colluders in one window, more than cap but below 1/3
        who, acc = [], 0.0
        for i in order:
            who.append(int(i))
            acc += base[i]
            if acc > CAP + 0.03:
                break
        return [(i, "safe", 3 + j, 3 + j, True, False) for j, i in enumerate(who)]
    if name == "bug":                                  # a client bug: over 40% of the base in one window
        who, acc = [], 0.0
        for i in order[::-1]:
            if acc >= 0.40:
                break
            who.append(int(i))
            acc += base[i]
        return [(i, "safe", 10, 10, False, False) for i in who]
    if name == "fork":                                 # two conflicting commit proofs: culprits above 1/3
        who, acc = [], 0.0
        for i in order[::-1]:
            if acc > 0.36:
                break
            who.append(int(i))
            acc += base[i]
        return [(i, "safe", 10, 10, True, True) for i in who]
    if name == "malicious":                            # above 1/3, no fork, confirmed malicious
        who, acc = [], 0.0
        for i in order:
            if acc > 0.36:
                break
            who.append(int(i))
            acc += base[i]
        return [(i, "safe", 6, 6, True, False) for i in who]
    raise ValueError(name)


def main():
    out = []
    names = ["live-repeat", "iso", "safe-repeat", "correlated", "bug", "fork", "malicious"]
    for seed, name in enumerate(names):
        cls, s = ttru.population(10, 12, 9, seed % 3, alpha=1.16)
        w = np.rint(s * 1e12).astype(np.int64)
        base = ttru.base_weights(cls, w.astype(float), 0.0, 0.0, CAP, U_MAX)
        script = script_of(name, base, np.random.default_rng([seed, 7]))
        pun = Scripted(cls, w.astype(float), CAP, U_MAX, script=script, **PARAMS)
        epochs, seen = [], 0
        for k in range(1, EPOCHS + 1):
            z, b = pun.update(None, k, 0)
            epochs.append(dict(z=[bool(x) for x in z > 0], bars=[bool(x) for x in pun.bars(k)],
                               base=[float(x) for x in b], queue=[int(q[0]) for q in pun.queue],
                               events=[[ev, int(i), int(kk)] for ev, i, kk in pun.log[seen:]]))
            seen = len(pun.log)
        out.append(dict(name=name, certified=[bool(c == "L") for c in cls], weights=[int(x) for x in w],
                        cap_ppm=round(CAP * 1e6), u_max_ppm=round(U_MAX * 1e6),
                        script=[[i, kind, es, ec, mal, fork] for i, kind, es, ec, mal, fork in script],
                        epochs=epochs))
        kinds = {}
        for e in pun.log:
            kinds[e[0]] = kinds.get(e[0], 0) + 1
        print(name, len(script), "items", kinds, "max wait", pun.max_wait, "infeasible", pun.infeasible)
    with open(OUT, "w") as fh:
        json.dump(out, fh)
    print(f"{len(out)} cases -> {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()

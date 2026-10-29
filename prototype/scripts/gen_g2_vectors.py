"""G2 test vectors for prototype/consensus/src/reputation.rs from the simulator's reference rules.

The leader rule (sim2/schedule.py `CusumExclusion`: AT evidence, CUSUM, exclusion cap on base weight, strict
FIFO queue) and the reputation update (sim2/ttru.py `TtruWeights`: step, r_min, recovery, budget b_rep) run on
synthetic accusation facts with the recommended parameters (信任2.0_协议级验证 §4.4). Leaders follow the
prototype's schedule (prototype/DESIGN.md §12.2): in each epoch, round robin by member index over the members
not excluded when the epoch starts. Epochs are E rounds long; at the terminal round kE the facts of rounds
<= kE + 1 - lag are processed and the table of the next epoch is computed.
Run from the repository root:  PYTHONPATH=. python prototype/scripts/gen_g2_vectors.py
"""
import json
import os

import numpy as np

from sim2 import schedule as S
from sim2 import ttru

OUT = os.path.join(os.path.dirname(__file__), "..", "consensus", "src", "tests", "g2_vectors.json")
E, LAG, EPOCHS = 100, 10, 40
RULE = dict(q=0.5, rho_bar=0.1, gamma=1e4, D=500, cap=0.5, Wq=500, evidence="at")
WEIGHTS = dict(epoch=E, r_min=0.7, b_rep=0.10, step=0.1, recover=0.02)
CASES = [  # (name, base, silent members, probability that another leader's round is accused, seed)
    ("silent3-n31-equal", "equal31", [0, 5, 9], 0.0, 1),
    ("silent3-frame-n31", "pop31", [2, 7, 30], 0.03, 2),
    ("silent18-cap-n31", "pop31", list(range(0, 31, 2)) + [1, 3], 0.0, 3),
    ("frame-budget-n7", "equal7", [], 0.4, 4),
    ("silent12-budget-n31", "pop31", list(range(19, 31)), 0.01, 5),
]


class Cfg:
    def __init__(self, n):
        self.n, self.lag, self.vote_weights = n, LAG, None


class State:
    """The parts of a simulator run that CusumExclusion and TtruWeights read."""

    def __init__(self, n, rounds):
        self.cfg = Cfg(n)
        self.leaders = np.full(rounds + 2, -1)
        self.accused = np.zeros(rounds + 2, bool)
        self.rule_log = []


def at_fact(st, u, v, evidence, tau=None):
    return bool(st.accused[u])


def base_of(kind):
    if kind == "equal31":
        return np.full(31, 1 / 31)
    if kind == "equal7":
        return np.full(7, 1 / 7)
    cls, s = ttru.population(10, 12, 9, 0, alpha=1.16)          # as the n31-s0 case of gen_ttru_vectors.py
    w = np.rint(s * 1e12).astype(np.int64)
    return ttru.base_weights(cls, w.astype(float), 0.0, 0.0, 0.10, 0.25)


def run(name, kind, silent, frame, seed):
    base = base_of(kind)
    n = len(base)
    rng = np.random.default_rng(seed)
    st = State(n, E * EPOCHS)
    rule = S.CusumExclusion(cap_weights=base, **RULE)
    weights = ttru.TtruWeights(base, rule=rule, **WEIGHTS)
    epochs, seen = [], 0
    for k in range(1, EPOCHS + 1):
        eligible = np.flatnonzero(~rule._state(st)["excluded"])
        for u in range((k - 1) * E + 1, k * E + 1):
            leader = int(eligible[u % len(eligible)])
            st.leaders[u] = leader
            st.accused[u] = leader in silent or rng.random() < frame
        table = weights(st, k * E + 1)                       # processes rounds <= kE + 1 - lag
        s = rule._state(st)
        epochs.append(dict(
            accused=[int(u) for u in np.flatnonzero(st.accused[(k - 1) * E + 1:k * E + 1]) + (k - 1) * E + 1],
            events=[[ev, int(node), int(view)] for ev, node, view in st.rule_log[seen:]],
            r_ppm=[int(round(x * 1e6)) for x in weights._state(st)["r"]],
            excluded=[bool(x) for x in s["excluded"]],
            queue=[int(e[0]) for e in s["queue"]],
            table=[float(x) for x in table],
        ))
        seen = len(st.rule_log)
    return dict(name=name, base=[float(x) for x in base], epoch_length=E, lag=LAG, epochs=epochs)


def main():
    S.bad_fact = at_fact                    # the AT facts are given (accusations on the ledger)
    out = [run(*case) for case in CASES]
    with open(OUT, "w") as fh:
        json.dump(out, fh)
    for case in out:
        ev = [e for x in case["epochs"] for e in x["events"]]
        kinds = {k: sum(1 for e in ev if e[0] == k) for k in ("exclude", "release", "queue", "drop")}
        print(case["name"], kinds, "min r", min(min(x["r_ppm"]) for x in case["epochs"]))
    print(f"{len(out)} cases -> {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()

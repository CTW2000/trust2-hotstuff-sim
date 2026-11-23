"""The tolerance of unresponsive weight (dirTtruMargin):
- adversary.Offline: a replica is silent as leader and as voter from its view on, and not before;
- tolerated(): the others hold a quorum on the table exactly when the base share of the replicas that do not vote
  is below (1 + 2 D_N - D_O)/3;
- a short run of the experiment: with 11 of 31 equal replicas down from the start (35.5%) nothing commits without
  reputation, and the schedule of the experiment puts each replica down at its view.
Run from the repository root:  python -m sim2.tests.test_margin   (or pytest: test_margin)"""
from types import SimpleNamespace

import numpy as np

from sim2 import adversary as A
from sim2.common import W_QUORUM
from sim2.experiments import dirTtruMargin as M


def test_offline_replicas_neither_propose_nor_vote_from_their_view_on():
    st = SimpleNamespace(cfg=SimpleNamespace(n=4), leader=lambda w: w % 4)
    adv = A.Offline({1: 10, 2: 20})
    p = adv.plan(9, st)                      # replica 1 leads and is still up
    assert p.prop_targets is None and p.silent_voters == frozenset()
    p = adv.plan(13, st)                     # replica 1 leads and is down
    assert not p.prop_targets.any() and p.silent_voters == frozenset({1})
    p = adv.plan(22, st)                     # replica 2 leads and is down, as is replica 1
    assert not p.prop_targets.any() and p.silent_voters == frozenset({1, 2})
    p = adv.plan(23, st)                     # replica 3 leads
    assert p.prop_targets is None and p.silent_voters == frozenset({1, 2})


def test_tolerated_share_is_the_quorum_condition():
    assert abs(M.tolerated(0.0, 0.0) - 1 / 3) < 1e-12
    assert abs(M.tolerated(0.10, 0.0) - 0.40) < 1e-12
    assert abs(M.tolerated(0.0, 0.10) - 0.30) < 1e-12
    rng = np.random.default_rng(3)
    for _ in range(20000):
        u = rng.random()
        d_n, d_o = rng.random() * min(u, 0.3), rng.random() * min(1 - u, 0.3)
        others = (1 - u - d_o) / (1 - d_n - d_o)          # their share on the table
        if abs(others - W_QUORUM) > 1e-9:
            assert (others > W_QUORUM) == (u < M.tolerated(d_n, d_o))


def test_the_schedule_puts_each_replica_down_at_its_view():
    starts = M.starts_of(5)
    assert len(starts) == M.DOWN[-1][1]
    for view, count in M.DOWN:
        assert sum(1 for s in starts.values() if s <= view) == count
    assert [c for _, _, c in M.phases()] == [c for _, c in M.DOWN]
    assert M.phases()[0][0] == 1 and M.phases()[-1][1] == M.VIEWS - 10


def test_without_reputation_nothing_commits_above_one_third():
    saved = M.DOWN
    try:
        M.DOWN = ((1, 11),)                  # 11 of 31 down from the start: 35.5%
        rows = M.job((0.0, 1, 400))
    finally:
        M.DOWN = saved
    assert len(rows) == 1 and rows[0]["down"] == 11
    assert rows[0]["commit"] == 0.0
    assert rows[0]["epochs_no_quorum"] == rows[0]["epochs"]


if __name__ == "__main__":
    for fn_name, fn in sorted(globals().items()):
        if fn_name.startswith("test_"):
            fn()
            print("ok", fn_name)

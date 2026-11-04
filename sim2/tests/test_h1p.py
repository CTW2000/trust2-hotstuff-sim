"""H1' (prototype/DESIGN.md §15.11): the next table known an epoch ahead.
- GradedPunishment(delay=1): evidence of chain epoch e is visible from the table of epoch e + 2, one table later than
  with delay 0, and the suspension then lasts as long;
- ttru.scheme(25): the defaults given for epochs of 100 views keep their length in views at 25 views per epoch.
Run from the repository root:  python -m sim2.tests.test_h1p   (or pytest: test_h1p)"""
import numpy as np

from sim2 import ttru
from sim2.punish import GradedPunishment

CAP, UMAX = 0.10, 0.25


def suspended_tables(delay):
    cls, s = ttru.population(10, 12, 9, 0)
    p0 = GradedPunishment(cls, s, CAP, UMAX, liveness=False)
    i = int(np.argmin(p0.base))
    p = GradedPunishment(cls, s, CAP, UMAX, liveness=False, injected=[(i, 1, 1, True)], delay=delay)
    return [k for k in range(1, 12) if p.update(None, k, 0)[0][i] == 0]


def check_delay():
    assert suspended_tables(0) == [2, 3, 4, 5], suspended_tables(0)
    assert suspended_tables(1) == [3, 4, 5, 6], suspended_tables(1)
    print("delay 1: the suspension starts one table later and lasts as long")


def check_scheme():
    weights, graded = ttru.scheme(25)
    assert weights == dict(epoch=25, recover=0.005, table_lag=1)
    assert graded == dict(epoch=25, sus=(0, 0, 16, 128), lead_bar=4, win_chain=128, lookback=256, gov_delay=8,
                          delay=1, sign_window=4)
    print("scheme(25): durations x4 in epochs, recovery / 4 per epoch")


def main():
    check_delay()
    check_scheme()
    print("ALL H1' CHECKS PASSED")


def test_h1p():
    main()


if __name__ == "__main__":
    main()

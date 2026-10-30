"""T_tru weighted voting for the protocol-level simulator (信任2.0_方案重构说明 v0.4). Abstract only.

Base weight b = CapNorm(V), V_i = stake_i + pi * K for licensed entities (forfeitable value: stake
plus the license value K discounted by the enforcement probability pi); the uncertified class gets
min(its natural share, u_max, n_U * cap) of the total, the licensed class the rest, and inside each
class no entity exceeds the cap (water-filling). The weights always sum to 1: if the licensed class
cannot hold its share under the cap, its cap is relaxed to the smallest feasible value (方案 §3.3);
with no licensed entity the uncertified class is the whole weight (and its cap is relaxed likewise).
Voting shares per epoch: T = b * r * z normalized, where reputation r in [r_min, 1] is lowered by
`step` in an epoch with at least one conviction of the replica by the leader rule (CusumExclusion
"exclude" events of views <= B - lag, B the first view of the epoch), stays put while the replica is
excluded, and recovers by `recover` per epoch otherwise (recovering during the exclusion would undo a
conviction when D * recover / epoch >= step); the total removed weight is at most b_rep (removed
weight is not redistributed); z = 0 for proven liars (G1, contradictions of views <= B - lag) when
g1 is set. Soft exclusions ("exclude_soft") do not touch r at all (no cut, no frozen recovery).
Log entries are read by their view field (<= B - lag), not by log position, because "g1" entries are
logged with view v - lag and the log is not sorted by view.
Graded G1 punishment (方案 v0.12 §3.3): with punish = punish.GradedPunishment, z and the base weights
of every table come from it (suspension, eviction with CapNorm recomputed) instead of g1; formula A
of v0.12 is base_weights(..., K=0) (punish builds its own base from stake). The punish object is a
template: every State gets its own copy (punisher(st)), so verify_leaders can replay a run. bars(st, v)
gives the replicas barred from leading by the punishment (for CusumExclusion.bars).
Epoch hand-over (理论_可问责安全与纪元交接 定理 4): the simulator switches tables at fixed views and does
not model forks; the protocol must let a new table take effect only after the last block of the old
epoch is committed, otherwise the bound needs beta0 < (1 - 2 b_rep)/3 (cuts that never recover) or
tighter (理论 定理 6).
"""
import copy

import numpy as np

from . import schedule as S


def population(n_L, n_U, n_A, seed, alpha=1.16, base=(3.0, 1.0, 0.2)):
    rng = np.random.default_rng([seed, 1])
    cls = np.array(["L"] * n_L + ["U"] * n_U + ["A"] * n_A)
    b = np.where(cls == "L", base[0], np.where(cls == "U", base[1], base[2]))
    s = b * (1.0 + rng.pareto(alpha, cls.size))
    return cls, s / s.sum()


def cap_normalize(w, cap, total=1.0):
    w = np.asarray(w, float)
    if cap * len(w) < total - 1e-12:
        raise ValueError(f"infeasible cap: {len(w)} x {cap} < {total}")
    fixed = np.zeros(len(w), bool)
    out = w / w.sum() * total
    for _ in range(len(w)):
        free = ~fixed
        out = np.where(fixed, cap, w * (total - cap * fixed.sum()) / w[free].sum())
        over = (out > cap + 1e-12) & free
        if not over.any():
            return out
        fixed |= over
    return np.where(fixed, cap, out)


def base_weights(cls, s, K, pi, cap, u_max):
    V = s + np.where(cls == "L", pi * K, 0.0)
    unc = cls != "L"
    n_L, n_U = int((~unc).sum()), int(unc.sum())
    U = 1.0 if n_L == 0 else min(V[unc].sum() / V.sum(), u_max, n_U * cap)
    w = np.zeros(len(s))
    if n_L > 0:
        w[~unc] = cap_normalize(V[~unc], max(cap, (1.0 - U) / n_L), 1.0 - U)
    if n_U > 0:
        w[unc] = cap_normalize(V[unc], max(cap, U / n_U), U)
    return w


def max_weight_set(w, cost, budget, grid=4000):
    """Node set of maximum weight with total cost <= budget (0/1 knapsack over a weight grid)."""
    units = np.ceil(w * grid).astype(int)
    T = int(units.sum())
    INF = np.inf
    dp = np.full(T + 1, INF)
    dp[0] = 0.0
    take = np.zeros((len(w), T + 1), bool)
    for i, (u, c) in enumerate(zip(units, cost)):
        if u <= 0:
            continue
        cand = np.full(T + 1, INF)
        cand[u:] = dp[:-u] + c
        better = cand < dp
        take[i] = better
        dp = np.where(better, cand, dp)
    ok = np.flatnonzero(dp <= budget + 1e-12)
    best = int(ok.max())
    chosen = np.zeros(len(w), bool)
    j = best
    for i in range(len(w) - 1, -1, -1):
        if take[i, j]:
            chosen[i] = True
            j -= units[i]
    return chosen


class TtruWeights:
    """Callable (st, v) -> voting shares of view v (epoch tables, computed lazily and cached on st)."""

    def __init__(self, base, epoch=100, r_min=0.7, b_rep=0.10, step=0.1, recover=0.02, rule=None, g1=False,
                 punish=None):
        self.base = np.asarray(base, float)
        self.punish = punish
        assert abs(self.base.sum() - 1.0) < 1e-9, "base weights must sum to 1 (b_rep is a share)"
        self.epoch, self.r_min, self.b_rep, self.step, self.recover = epoch, r_min, b_rep, step, recover
        self.rule, self.g1 = rule, g1

    def _state(self, st):
        c = st.__dict__.setdefault("_ttru_cache", {})
        if id(self) not in c:
            n = len(self.base)
            c[id(self)] = dict(tables=[self.base.copy()], r=np.ones(n), z=np.ones(n), seen=0,
                               rs=[np.ones(n)], excl=np.zeros(n, bool), liar=np.zeros(n, bool), liar_done=0,
                               pend=[], pun=copy.deepcopy(self.punish))
        return c[id(self)]

    def __call__(self, st, v):
        s = self._state(st)
        e = max(0, (v - 1) // self.epoch)
        n = len(self.base)
        while len(s["tables"]) <= e:
            k = len(s["tables"])
            B = k * self.epoch + 1                       # first view of epoch k; facts <= B - lag
            horizon = B - st.cfg.lag
            convicted = np.zeros(n, bool)
            if self.rule is not None:
                self.rule._advance(st, B)
                log = st.rule_log
                s["pend"].extend(log[s["seen"]:])
                s["seen"] = len(log)
                ready = [x for x in s["pend"] if x[2] <= horizon]   # never read convictions after B - lag
                s["pend"] = [x for x in s["pend"] if x[2] > horizon]
                for ev, node, _ in sorted(ready, key=lambda x: x[2]):   # stable: log order within a view
                    if ev == "exclude":
                        convicted[node] = True
                        s["excl"][node] = True
                    elif ev == "release":
                        s["excl"][node] = False
                    # "exclude_soft": soft evidence bars the replica from leading only; r is untouched
            r = s["r"]
            r = np.where(convicted, np.maximum(self.r_min, r - self.step),
                         np.where(s["excl"], r, np.minimum(1.0, r + self.recover)))
            s["r"] = r
            base = self.base
            if self.punish is not None:
                s["z"], base = s["pun"].update(st, k, horizon)
            elif self.g1:
                for u in range(max(1, s["liar_done"] + 1), horizon + 1):
                    s["liar"] |= S.contradictions(st, u)
                s["liar_done"] = max(s["liar_done"], horizon)
                s["z"] = np.where(s["liar"], 0.0, 1.0)
            cut = base * (1.0 - r)
            if cut.sum() > self.b_rep:
                cut *= self.b_rep / cut.sum()
            t = (base - cut) * s["z"]
            s["tables"].append(t / t.sum())
            s["rs"].append(r.copy())
            s.setdefault("cuts", [np.zeros(n)]).append(cut.copy())
        return s["tables"][e]

    def table(self, st, e):
        return self._state(st)["tables"][e]

    def bars(self, st, v):
        self(st, v)
        if self.punish is None:
            return np.zeros(len(self.base), bool)
        return self._state(st)["pun"].bars(max(0, (v - 1) // self.epoch))

    def punisher(self, st):
        """The graded-punishment state of this run (None without punish)."""
        return self._state(st)["pun"]

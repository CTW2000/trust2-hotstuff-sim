"""Graded G1 punishment for T_tru (信任2.0_方案重构说明 v0.12 §3.3). Abstract only.

Evidence classes:
  liveness  NR self-contradiction (schedule.contradictions), read from the simulated views;
  safety    E1/E2/E3, injected at the weight layer (the simulator does not model forks): items
            (entity, sign_epoch, chain_epoch, malicious); fork events (culprits, chain_epoch) carry
            two conflicting commit proofs.
Evidence of chain epoch e becomes visible at the table of epoch e + 1; NR contradictions of views
<= B - lag are visible at the table whose first view is B (same horizon as the reputation).

Counting (all on base shares, the CapNorm output, never on table shares):
  c         safety evidence only: max(share of the entities with safety evidence signed in the same
            epoch, share of the entities with safety evidence on chain in the last `win_chain` epochs);
            recomputed at every table while the item is inside its chain window, so late evidence can
            only raise a level, never lower it.
  one per window   an entity is punished at most once per (class, sign epoch); further evidence of the
            same window only feeds upgrades.
  k         earlier punished windows of the same class within `lookback` epochs.
Levels: liveness L1 + k, at most L3; safety L2 (c <= cap), L3 (cap < c <= 1/3), L4 (c > 1/3 or a
fork), plus k, at most L4.
Effects (durations in epochs):
  L1  barred from leading for `lead_bar` epochs (G1 never falls on honest replicas, so the bar does
      not count against the AT exclusion cap);
  L2, L3  suspension (z = 0, also barred from leading) for sus[level] epochs from the epoch it takes
      effect; suspended base share <= l_max at all times, further suspensions wait in a strict FIFO
      queue (an upgrade while queued updates the entry, an upgrade while suspended extends it); a
      queued entity is barred from leading meanwhile (outside the cap: G1 never falls on honest
      replicas, and leading does not touch the weight table);
  L4  decided by governance `gov_delay` epochs later: a fork or malicious evidence leads to eviction (removed from the set, CapNorm recomputed over the rest). If the recomputation
      is infeasible (licensed count x cap < licensed class total 1 - U) the entity cap is relaxed to the
      smallest feasible value (1 - U) / licensed count, a stand-in for the governance decision that keeps the
      class cap; flagged "infeasible" (cap_used records the cap). Without any licensed entity left the
      old base is kept with the evicted entities at zero. recompute = "fork" (default, 方案 v0.12 §3.3):
      only evictions of fork culprits recompute CapNorm; other evictions (repeat offences, confirmed
      malicious evidence) just zero the entity, like a permanent suspension, so its weight is not handed
      to the uncapped entities of its class (a recomputation can give all of it to colluders);
      recompute = "all" recomputes after every eviction (kept for comparison);
      evidence of a client fault (malicious = False, no fork) is downgraded to L2 and queued.
      an L4 reached only through repeats, without malicious evidence or a fork, is downgraded to L3 and
      queued instead of evicted (方案 v0.12 §3.3, adopted 2026-10-28 after 验证 §4.7), so that evictions of
      honest-but-faulty entities do not shrink the honest weight outside l_max; repeat_evict = True restores
      the earlier rule (any repeat reaching L4 is evicted), used by the runs made before the adoption.
Logs (entity, epoch) events in self.log: ("L1".."L4", i, k), ("queue", i, k), ("suspend", i, k),
("release", i, k), ("evict", i, k), ("downgrade", i, k).
"""
import numpy as np

from . import schedule as S
from . import ttru


class GradedPunishment:
    def __init__(self, cls, stake, cap, u_max, epoch=100, l_max=0.10, sus=(0, 0, 4, 32), lead_bar=1,
                 win_chain=32, lookback=64, gov_delay=2, liveness=True, injected=(), forks=(), recompute="fork",
                 repeat_evict=False):
        self.cls, self.stake = np.asarray(cls), np.asarray(stake, float)
        self.cap, self.u_max, self.epoch, self.l_max = cap, u_max, epoch, l_max
        self.sus, self.lead_bar, self.win_chain, self.lookback = sus, lead_bar, win_chain, lookback
        self.gov_delay, self.liveness, self.recompute = gov_delay, liveness, recompute
        self.repeat_evict = repeat_evict
        self.injected = sorted(injected, key=lambda x: x[2])
        self.forks = sorted(forks, key=lambda x: x[1])
        n = len(self.cls)
        self.base = ttru.base_weights(self.cls, self.stake, 0.0, 0.0, cap, u_max)
        # CapNorm relaxes the cap for a committee too small to respect it. L_max rises with it, or the strict FIFO
        # queue would stall for good at an entity above it; and one entity alone is still not a correlated fault.
        largest = float(self.base.max())
        self.l_max, self.correlated = max(l_max, largest), max(cap, largest)
        self.items = []                     # dicts: i, kind, es, ec, mal, fork, level, applied
        self.windows = {}                   # (i, kind, es) -> item index (one punishment per window)
        self.bar_until = np.zeros(n, int)   # barred from leading in epochs < bar_until
        self.sus_until = np.full(n, -1)     # suspended in epochs < sus_until (-1: not suspended)
        self.queue = []                     # [i, duration, epoch queued]
        self.gov = []                       # [i, decide epoch, item index]
        self.evicted = np.zeros(n, bool)
        self.infeasible = False
        self.cap_used = cap
        self.log = []
        self.done_view, self.next_inj, self.next_fork = 0, 0, 0
        self.tables_done = 0
        self.max_wait = 0
        self.history = []                   # per epoch: suspended base share, queue length
        self.bar_hist = [np.zeros(n, bool)]  # per epoch: replicas barred from leading (fixed when built)

    # ---- evidence intake -------------------------------------------------------------------------
    def _add(self, i, kind, es, ec, mal=True, fork=False):
        key = (int(i), kind, int(es))
        if key in self.windows:
            it = self.items[self.windows[key]]
            it["fork"] |= fork
            it["mal"] |= mal
            return
        self.windows[key] = len(self.items)
        self.items.append(dict(i=int(i), kind=kind, es=int(es), ec=int(ec), mal=mal, fork=fork, level=0, k=0))

    def _repeats(self, i, kind, ec):
        return sum(1 for it in self.items if it["i"] == i and it["kind"] == kind and it["level"] > 0
                   and it["ec"] >= ec - self.lookback)

    def _intake(self, st, k, horizon):
        if self.liveness and st is not None:
            for u in range(self.done_view + 1, horizon + 1):
                if u >= 1:
                    for i in np.flatnonzero(S.contradictions(st, u)):
                        self._add(i, "live", (u - 1) // self.epoch, k)
            self.done_view = max(self.done_view, horizon)
        while self.next_inj < len(self.injected) and self.injected[self.next_inj][2] < k:
            i, es, ec, mal = self.injected[self.next_inj]
            self._add(i, "safe", es, ec, mal)
            self.next_inj += 1
        while self.next_fork < len(self.forks) and self.forks[self.next_fork][1] < k:
            culprits, ec = self.forks[self.next_fork]
            for i in culprits:
                self._add(i, "safe", ec, ec, True, fork=True)
            self.next_fork += 1

    # ---- levels ----------------------------------------------------------------------------------
    def _c(self, it, k):
        safe = [x for x in self.items if x["kind"] == "safe"]
        sig = {x["i"] for x in safe if x["es"] == it["es"]}
        c = float(self.base0[list(sig)].sum())
        if it["ec"] > k - self.win_chain:
            chain = {x["i"] for x in safe if k - self.win_chain < x["ec"] <= k}
            c = max(c, float(self.base0[list(chain)].sum()))
        return c

    def _level(self, it, k):
        if it["kind"] == "live":
            return min(1 + it["k"], 3)
        c = self._c(it, k)
        lvl = 4 if (it["fork"] or c > 1 / 3 + 1e-12) else (3 if c > self.correlated + 1e-12 else 2)
        return min(lvl + it["k"], 4)

    # ---- effects ---------------------------------------------------------------------------------
    def _suspend_request(self, i, dur, k):
        if self.evicted[i]:
            return
        if self.sus_until[i] > k:                       # already suspended: extend
            start = self.sus_until[i] - self._cur_dur[i]
            if start + dur > self.sus_until[i]:
                self.sus_until[i] = start + dur
                self._cur_dur[i] = dur
            return
        for q in self.queue:
            if q[0] == i:
                q[1] = max(q[1], dur)
                return
        self.queue.append([i, dur, k])
        self.log.append(("queue", i, k))

    def _apply(self, it, lvl, k):
        i = it["i"]
        self.log.append((f"L{lvl}", i, k))
        if lvl == 1:
            self.bar_until[i] = max(self.bar_until[i], k + self.lead_bar)
        elif lvl in (2, 3):
            self._suspend_request(i, self.sus[lvl], k)
        else:
            if not any(g[0] == i for g in self.gov):
                self.gov.append([i, k + self.gov_delay, self.items.index(it)])

    def _evict(self, i, k, fork=True):
        self.evicted[i] = True
        self.sus_until[i] = -1
        self.queue = [q for q in self.queue if q[0] != i]
        self.log.append(("evict", i, k))
        keep = ~self.evicted
        if self.recompute == "fork" and not fork:
            self.base = np.where(keep, self.base, 0.0)
            return
        n_lic = int((self.cls[keep] == "L").sum())
        if n_lic == 0:
            self.infeasible = True
            self.base = np.where(keep, self.base, 0.0)
            return
        cap = self.cap
        unc = self.cls[keep] != "L"
        st_k = self.stake[keep]
        lic_total = 1.0 - min(st_k[unc].sum() / st_k.sum(), self.u_max)   # as in ttru.base_weights
        if n_lic * cap < lic_total - 1e-12:
            cap = lic_total / n_lic
            self.infeasible = True
        self.cap_used = max(self.cap_used, cap)
        b = np.zeros(len(self.cls))
        b[keep] = ttru.base_weights(self.cls[keep], self.stake[keep], 0.0, 0.0, cap, self.u_max)
        self.base = b

    def update(self, st, k, horizon):
        """State for the table of epoch k; returns (z, base)."""
        if not hasattr(self, "base0"):
            self.base0 = self.base.copy()
            self._cur_dur = np.zeros(len(self.cls), int)
        assert k == self.tables_done + 1, "tables must be built in order"
        self.tables_done = k
        self._intake(st, k, horizon)
        for it in self.items:                           # new punishments and upgrades
            if self.evicted[it["i"]]:
                continue
            if it["level"] == 0:                        # repeats are counted when the window is first punished
                it["k"] = self._repeats(it["i"], it["kind"], it["ec"])
            lvl = self._level(it, k)
            if lvl > it["level"]:
                it["level"] = lvl
                self._apply(it, lvl, k)
        for g in [g for g in self.gov if g[1] <= k]:    # governance decisions
            self.gov.remove(g)
            i, _, idx = g
            it = self.items[idx]
            if it["fork"] or it["mal"] or (it["k"] > 0 and self.repeat_evict):
                self._evict(i, k, it["fork"])
            elif it["k"] > 0:                           # repeat without malicious evidence: long suspension
                self.log.append(("downgrade", i, k))
                self._suspend_request(i, self.sus[3], k)
            else:
                self.log.append(("downgrade", i, k))
                self._suspend_request(i, self.sus[2], k)
        for i in np.flatnonzero((self.sus_until >= 0) & (self.sus_until <= k)):
            self.sus_until[i] = -1
            self.log.append(("release", int(i), k))
        keep = []
        blocked = False
        for i, dur, t in self.queue:                    # strict FIFO under the l_max cap
            room = self.base[self.sus_until > k].sum() + self.base[i] <= self.l_max + 1e-12
            if not blocked and room:
                self.sus_until[i] = k + dur
                self._cur_dur[i] = dur
                self.max_wait = max(self.max_wait, k - t)
                self.log.append(("suspend", i, k))
            else:
                blocked = True
                keep.append([i, dur, t])
        self.queue = keep
        susp = (self.sus_until > k) | self.evicted
        self.history.append((float(self.base[self.sus_until > k].sum()), len(self.queue)))
        queued = np.zeros(len(self.cls), bool)
        queued[[q[0] for q in self.queue]] = True
        self.bar_hist.append((self.bar_until > k) | susp | queued)
        return np.where(susp, 0.0, 1.0), self.base.copy()

    def bars(self, k):
        """Replicas barred from leading in epoch k, as fixed when the table of epoch k was built."""
        return self.bar_hist[k]

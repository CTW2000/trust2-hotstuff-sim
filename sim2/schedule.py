"""Leader rules with a lag (pluggable reputation rules R1-R3; R0 is the static schedule).

Outcome facts: view u "succeeded" iff the first proposal actually sent after view u extends block
u (QC(u) reached the chain); otherwise the leader of u is recorded as a failed proposer. This is
the "failed proposer" signal of DiemBFT/Aptos-style designs, abstracted. A missing proposal in
u+1 (crashed, silent or glitching next leader) therefore does not count against the leader of u.
The leader of view v may only use facts of views u <= v - lag, and the search for the next
proposal only reads rows <= v - 3; if no proposal is found in u+1..v-3 the view counts as failed,
so the lag must leave room for that search (lag >= MIN_LAG, asserted). These facts are treated as
an agreed on-chain record. Engines agreeing does NOT prove the facts were final when read (both
could read the same unfinished row); verify_leaders() recomputes the schedule from the final facts.
Adversary plans must not query leader(w+2) or later (the fast engine computes up to leader(x+2)). Whether the lag is long enough for
those facts to be final when they are used is checked by tests (engines compute leaders
independently and must agree).
Randomness: numpy Generator keyed by (seed, 17, v), so both engines draw the same leader.
"""
import numpy as np

from .common import W_QUORUM, weighted_hit


class LeaderRule:
    name = "base"

    def leader(self, v: int, st) -> int:
        raise NotImplementedError


def succeeded(prop_parent: np.ndarray, u: int, limit: int) -> bool:
    """True iff the first proposal sent in views u+1..limit extends block u."""
    for w in range(u + 1, limit + 1):
        if prop_parent[w] >= 0:
            return prop_parent[w] == u
    return False


def rec(st, u: int, tau: int = None) -> bool:
    """Direction A v0.2: rec_tau(u) = at least tau distinct vote-carrying timeouts of u exist
    (third-party verifiable; tau = None means the quorum q)."""
    return bool(st.tmo_votes[u] >= (st.cfg.quorum if tau is None else tau))


def bad_fact(st, u: int, v: int, evidence: str, tau: int = None) -> bool:
    """Evidence against the leader of u, as seen when choosing the leader of v.
    evidence = "failed":   failed proposer (the first proposal after u does not extend u);
    evidence = "failed_A": direction A, failed proposer unless rec_tau(u) (QC(u) reconstructible
                           from tau vote-carrying timeouts: the leader is exonerated, see
                           collector_fault);
    evidence = "at":       AT accusation (2f+1 timeouts of u with NR=1; weighted: NR=1 share above
                           cfg.at_share, default 2/3);
    evidence = "noqc":     soft (G3, P2 with broadcast votes): no QC of u exists. After GST an honest
                           leader always gets a QC when the Byzantine share is < 1/3, but late
                           messages plus withheld Byzantine votes can fail its view;
    evidence = "slot":     soft (G3), weighted voting: the robust slot-duration score of u
                           (weighted_slot_score) exceeds cfg.slot_theta_ms (slow or failed view);
    evidence = "omit":     inclusion attestations (G2): block u is certified but leaves out a due,
                           non-exempt transaction (cfg.txlayer, txlayer.TxLayer.omit);
    a tuple of evidences:  bad if any of them is."""
    if isinstance(evidence, tuple):
        return any(bad_fact(st, u, v, e, tau) for e in evidence)
    if evidence == "omit":
        return st.cfg.txlayer.omit(st, u)
    if evidence == "noqc":
        return not bool(st.qc_exists[u])
    if evidence == "slot":
        return weighted_slot_score(st, u) > st.cfg.slot_theta_ms
    if evidence == "at":
        if st.cfg.vote_weights is not None:
            thr = W_QUORUM if st.cfg.at_share is None else st.cfg.at_share
            return weighted_hit(st.nr_w[u], thr)
        return bool(st.nr_count[u] >= st.cfg.quorum)
    failed = not succeeded(st.prop_parent, u, v - 3)
    if evidence == "failed_A":
        return failed and not rec(st, u, tau)
    return failed


def collector_fault(st, u: int, v: int, tau: int = None) -> bool:
    """Direction A: block u was orphaned although rec_tau(u) holds. Blames the collector of u
    (leader of u+1); with pair evidence it means "the leader of u or its collector is faulty"."""
    return rec(st, u, tau) and not succeeded(st.prop_parent, u, v - 3)


# ---- NR self-contradiction (G1; 证据扩展设计 第一部分), needs cfg.track_signed

def contradictions(st, u: int) -> np.ndarray:
    """Replicas caught in view u: a signed timeout of u with NR=1 and a signed vote of u held by an
    honest replica or contained in a published QC (transferable proof; honest replicas never produce
    it, theorem NRC-1)."""
    return st.nr1[u] & (st.vote_seen[u] | st.qc_pub[u])


def liars(st, v: int) -> np.ndarray:
    """The proven-liar set K as of the leader choice of view v: replicas caught in some view
    u <= v - lag (the proof is on chain with the leader-rule lag; membership is permanent).
    Cached incrementally on the State."""
    c = st.__dict__.setdefault("_liar_cache", {"done": 0, "K": np.zeros(st.cfg.n, bool)})
    for u in range(c["done"] + 1, v - st.cfg.lag + 1):
        if u >= 1:
            c["K"] |= contradictions(st, u)
    c["done"] = max(c["done"], v - st.cfg.lag)
    return c["K"].copy()


def accused_tight(st, u: int, K: np.ndarray) -> bool:
    """AT with the report pool purged of K (theorem NRC-2): NR=1 signatures of replicas outside K,
    threshold q - |K|. Framing still needs f+1 honest violations; a partial-send leader is caught
    with |K| more honest recipients than under the plain threshold."""
    k = int(K.sum())
    return bool((st.nr1[u] & ~K).sum() >= st.cfg.quorum - k)


def presence_seen(st, rows) -> np.ndarray:
    """Presence evidence per (view, replica) for the given views (review S1/S2): the vote was received
    by an honest replica before that replica's own timer of the view (receipts are put on chain by
    honest proposers, so no single assembler can drop them), or it is in a QC published by a Byzantine
    assembler, or, in a view that ended without a QC, it was carried by a timeout. Votes carried by
    timeouts in views that formed a QC do not count (broadcasting one's vote without sending it to
    the collector gives no presence)."""
    rows = np.asarray(rows, dtype=int)
    carried = st.vote_carried[rows] & ~st.qc_exists[rows][:, None]
    return st.vote_timely[rows] | st.qc_pub[rows] | carried


def presence(st, v: int, window: int) -> np.ndarray:
    """Vote presence (NRC-3): per replica, the share of the views u in the last `window` facts
    (u <= v - lag) whose leader sent a proposal, in which presence evidence exists (presence_seen).
    The denominator is views with a proposal, not views with a QC (review S1: with QC views only,
    the more a withholder makes views fail, the higher its presence)."""
    hi = v - st.cfg.lag
    lo = max(1, hi - window + 1)
    rows = [u for u in range(lo, hi + 1) if st.prop_parent[u] >= 0]
    if not rows:
        return np.ones(st.cfg.n)
    return presence_seen(st, rows).mean(axis=0)


def outcome_counts(st, v: int, horizon: int, evidence: str = "failed"):
    """(led, failed) counts per replica over facts of views in [v-lag-horizon+1, v-lag]."""
    n, lag = st.cfg.n, st.cfg.lag
    led = np.zeros(n)
    failed = np.zeros(n)
    hi = v - lag
    lo = max(1, hi - horizon + 1)
    for u in range(lo, hi + 1):
        L = st.leaders[u]
        if L < 0:
            continue
        led[L] += 1
        if bad_fact(st, u, v, evidence):
            failed[L] += 1
    return led, failed


def base_share(st, v: int) -> np.ndarray:
    """Leader share before any rule-specific bars: the voting shares under weighted voting
    (cfg.vote_weights), equal shares otherwise."""
    if st.cfg.vote_weights is None:
        return np.ones(st.cfg.n)
    return np.asarray(st.cfg.vote_weights(st, v), float)


def _draw(st, v: int, weights: np.ndarray) -> int:
    rng = np.random.default_rng([st.cfg.seed, 17, v])
    p = weights / weights.sum()
    return int(rng.choice(st.cfg.n, p=p))


class Uniform(LeaderRule):
    """R0 as a dynamic rule: uniform random leader each view (ignores facts)."""
    name = "R0_uniform"

    def leader(self, v, st):
        return _draw(st, v, base_share(st, v))


class ExpProfile(LeaderRule):
    """R1: weight exp(-eta * failure rate) over the last `horizon` facts (T3-dyn D4)."""
    name = "R1_exp"

    def __init__(self, eta: float, horizon: int = 200):
        self.eta, self.horizon = eta, horizon

    def leader(self, v, st):
        led, failed = outcome_counts(st, v, self.horizon)
        rate = np.divide(failed, led, out=np.zeros_like(led), where=led > 0)
        return _draw(st, v, np.exp(-self.eta * rate))


class Tiers(LeaderRule):
    """R2: two tiers, weight 1 if failure rate <= theta else 1/K (D4-W threshold profile;
    an abstraction of tiered weights such as Aptos-style {1000, 10, 1})."""
    name = "R2_tiers"

    def __init__(self, theta: float, K: float, horizon: int = 50):
        self.theta, self.K, self.horizon = theta, K, horizon

    def leader(self, v, st):
        led, failed = outcome_counts(st, v, self.horizon)
        rate = np.divide(failed, led, out=np.zeros_like(led), where=led > 0)
        return _draw(st, v, np.where(rate <= self.theta, 1.0, 1.0 / self.K))


class CarouselLike(LeaderRule):
    """R3: exclude replicas that failed as leader within the last `horizon` facts; uniform among
    the rest (an abstraction of excluding recently failed leaders)."""
    name = "R3_carousel"

    def __init__(self, horizon: int = 20):
        self.horizon = horizon

    def leader(self, v, st):
        led, failed = outcome_counts(st, v, self.horizon)
        w = (failed == 0).astype(float)
        if w.sum() == 0:
            w[:] = 1.0
        return _draw(st, v, w)


class _ForgetEstimate(LeaderRule):
    """Per-replica forgetting estimate of its own failure rate, updated only on its own led views
    (exactly the estimator of the abstract simulation sim/d4_sim.py): r_hat = F / O with
    F <- keep F + fail, O <- keep O + 1 on each own opportunity, keep = 1 - 1/W, and a prior worth
    W opportunities at rate `prior`. Facts are consumed in order; the running estimate is cached
    on the State (so each engine keeps its own).
    Direction A (P1, vote-carrying timeouts): blame_collector also scores each replica's collector
    turns (leader of u+1) with collector_fault(u) = rec_tau(u) and u orphaned; rec_tau = None is the
    quorum q (v0.1), q + floor(f/2) is the identifiability threshold of 方向A v0.2 (A4); pair = True
    charges the leader too on collector_fault (pair evidence A5), so the leader is charged on every
    orphaned block and the collector on the reconstructible ones."""

    def __init__(self, W: int, prior: float, evidence: str = "failed", blame_collector: bool = False,
                 rec_tau: int = None, pair: bool = False):
        self.W, self.prior, self.evidence, self.blame_collector = W, prior, evidence, blame_collector
        self.rec_tau, self.pair = rec_tau, pair

    def rates(self, v, st):
        c = st.__dict__.setdefault("_forget_cache", {})
        key = id(self)
        if key not in c:
            n = st.cfg.n
            c[key] = [np.full(n, self.prior * self.W), np.full(n, float(self.W)), 0]
        F, O, done = c[key]
        keep = 1.0 - 1.0 / self.W
        for u in range(done + 1, v - st.cfg.lag + 1):
            if u < 1:
                continue
            L = st.leaders[u]
            if L < 0:
                continue
            cf = self.blame_collector and collector_fault(st, u, v, self.rec_tau)
            F[L] = keep * F[L] + (bad_fact(st, u, v, self.evidence, self.rec_tau) or (self.pair and cf))
            O[L] = keep * O[L] + 1.0
            if self.blame_collector:
                # direction A: every collector turn is an opportunity of the collector's own record
                # (v0.2; v0.1 counted an opportunity only when the collector was blamed)
                C = st.leaders[u + 1]
                if C >= 0:
                    F[C] = keep * F[C] + cf
                    O[C] = keep * O[C] + 1.0
        c[key][2] = max(done, v - st.cfg.lag)
        return F / O


class ForgetExp(_ForgetEstimate):
    """R1 (as in D4): weight exp(-eta * r_hat)."""
    name = "R1_forget_exp"

    def __init__(self, eta: float, W: int = 200, prior: float = 0.0, evidence: str = "failed",
                 blame_collector: bool = False, rec_tau: int = None, pair: bool = False):
        super().__init__(W, prior, evidence, blame_collector, rec_tau, pair)
        self.eta = eta

    def leader(self, v, st):
        return _draw(st, v, np.exp(-self.eta * self.rates(v, st)))


class ForgetThreshold(_ForgetEstimate):
    """R2 (as in D4-W): weight K if r_hat < theta else 1."""
    name = "R2_forget_threshold"

    def __init__(self, theta: float, W: int = 200, K: float = 1000.0, prior: float = 0.0,
                 evidence: str = "failed", blame_collector: bool = False, rec_tau: int = None,
                 pair: bool = False):
        super().__init__(W, prior, evidence, blame_collector, rec_tau, pair)
        self.theta, self.K = theta, K

    def leader(self, v, st):
        return _draw(st, v, np.where(self.rates(v, st) < self.theta, self.K, 1.0))


class CusumExclusion(LeaderRule):
    """R5, the Phase-1 module (阶段1 §4): constant share before conviction (uniform over replicas
    that are not excluded), a CUSUM per replica over its own led views, exclusion when the CUSUM
    reaches h = ln(gamma), an exclusion period, an optional exclusion cap with a FIFO queue.

    increments: ln(q/rho_bar) on a bad fact, ln((1-q)/(1-rho_bar)) otherwise (T3).
    expiry = "view":   an exclusion ends D views after it started (view numbers advance through
                       TCs, so this always ends);
    expiry = "commit": an exclusion ends after D further successful views (a proxy for committed
                       blocks). If every leader candidate is silent, nothing succeeds and the
                       exclusions never end: the absorbing state of DQ扩展 Lemma D.
    cap:   at most floor(cap * n) replicas excluded at once (equal weights); further convictions
           wait in a strict FIFO queue (one entry per replica; while the queue is non-empty every new
           conviction joins it, and the queue is served head first) and are dropped after Wq views.
    soft_evidence: a second CUSUM per replica over soft evidence (e.g. "noqc") with its own
           soft_rho / soft_q (same h); a soft conviction excludes the replica from leading like a
           CUSUM crossing (same cap, queue, expiry) but is logged as "exclude_soft", so the T_tru
           reputation (which reads "exclude" only) never moves on soft evidence. The soft/hard kind
           travels with the queue entry (k, t, soft); a hard conviction of a queued replica turns its
           entry hard; soft evidence never touches the hard CUSUM W (review v0.5 code #1-#3).
           "noqc" reads qc_exists (some replica ever formed QC(u)), a simulator proxy for the on-chain
           fact "QC(u) is carried by a later proposal"; they differ in about 1/700 views.
    cap_weights: weighted voting: the cap bounds the excluded WEIGHT instead (sum of cap_weights over
           excluded replicas <= cap; leaders are drawn by weight, so a count cap would let framing
           remove most of the honest leader share). cap_weights are base weights; the leader draw uses
           the current T_tru table, which differs from them by the reputation renormalization.
    Events are logged in st.rule_log as ("exclude", replica, view), ("release", replica, view),
    ("queue", replica, view), ("drop", replica, view).

    NR self-contradiction (G1, needs cfg.track_signed):
    g1 = True:   proven liars (liars(st, v)) are barred from leading at once and for good; this
                 evidence never falls on honest replicas (NRC-1), so these bars do not count against
                 the cap (logged as ("g1", replica, view)).
    presence_theta: a replica whose vote presence over the last presence_window facts (views with a
                 proposal, presence_seen) is below the threshold is convicted like a CUSUM crossing,
                 with the same cap, queue and expiry (soft evidence; logged as ("presence", ...)).
                 Checked every presence_every views once at least half the window has facts.
                 Note: presence convictions are logged as hard "exclude" (kept for the earlier
                 experiments); do not combine presence_theta with T_tru reputation."""
    name = "R5_cusum"

    def __init__(self, q: float = 0.5, rho_bar: float = 0.01, gamma: float = 1e4, D: int = 200,
                 cap: float = None, Wq: int = 1000, expiry: str = "view", evidence: str = "at",
                 g1: bool = False, presence_theta: float = None, presence_window: int = 300,
                 presence_every: int = 10, cap_weights=None, soft_evidence: str = None,
                 soft_rho: float = 0.3, soft_q: float = 0.9):
        self.q, self.rho_bar, self.h = q, rho_bar, float(np.log(gamma))
        self.cap_weights = None if cap_weights is None else np.asarray(cap_weights, float)
        self.soft_evidence = soft_evidence
        if soft_evidence is not None:
            self.s_up = float(np.log(soft_q / soft_rho))
            self.s_down = float(np.log((1 - soft_q) / (1 - soft_rho)))
        self.up = float(np.log(q / rho_bar))
        self.down = float(np.log((1 - q) / (1 - rho_bar)))
        self.D, self.cap, self.Wq, self.expiry, self.evidence = D, cap, Wq, expiry, evidence
        self.g1, self.presence_theta = g1, presence_theta
        self.presence_window, self.presence_every = presence_window, presence_every

    def _state(self, st):
        c = st.__dict__.setdefault("_cusum_cache", {})
        if id(self) not in c:
            n = st.cfg.n
            c[id(self)] = dict(W=np.zeros(n), W2=np.zeros(n), until=np.full(n, -1.0), excluded=np.zeros(n, bool),
                               queue=[], commits=0, done=0, g1=np.zeros(n, bool))
        return c[id(self)]

    def _room(self, s, k, cap_n):
        if self.cap_weights is None or self.cap is None:
            return s["excluded"].sum() < cap_n
        return self.cap_weights[s["excluded"]].sum() + self.cap_weights[k] <= self.cap + 1e-12

    def _convict(self, st, s, k, u, cap_n, soft=False):
        q = s["queue"]
        pos = next((i for i, e in enumerate(q) if e[0] == k), None)
        if pos is None and not q and self._room(s, k, cap_n):
            self._exclude(st, s, k, u, soft)
        elif pos is None:
            q.append((k, u, soft))      # strict FIFO: a non-empty queue is served first
            s["W"][k] = 0.0
            s["W2"][k] = 0.0
            st.rule_log.append(("queue", int(k), int(u)))
        elif soft:
            s["W2"][k] = self.h         # already queued: cap the soft CUSUM, never touch the hard one
        else:
            s["W"][k] = self.h          # already queued: do not let evidence pile up
            q[pos] = (k, q[pos][1], False)  # a hard conviction while queued: the exclusion is hard

    def _exclude(self, st, s, k, u, soft=False):
        s["excluded"][k] = True
        s["until"][k] = (u + self.D) if self.expiry == "view" else (s["commits"] + self.D)
        s["W"][k] = 0.0
        s["W2"][k] = 0.0
        st.rule_log.append(("exclude_soft" if soft else "exclude", int(k), int(u)))

    def _advance(self, st, v):
        s = self._state(st)
        n = st.cfg.n
        cap_n = n if self.cap is None else int(np.floor(self.cap * n))
        if self.g1:
            K = liars(st, v)
            for k in np.flatnonzero(K & ~s["g1"]):
                st.rule_log.append(("g1", int(k), int(v - st.cfg.lag)))
            s["g1"] = K
        for u in range(s["done"] + 1, v - st.cfg.lag + 1):
            if u < 1:
                continue
            if self.expiry == "commit" and succeeded(st.prop_parent, u, v - 3):
                s["commits"] += 1
            clock = u if self.expiry == "view" else s["commits"]
            for k in np.flatnonzero(s["excluded"] & (s["until"] <= clock)):
                s["excluded"][k] = False
                st.rule_log.append(("release", int(k), int(u)))
            keep = []
            blocked = False
            for k, t, sf in s["queue"]:
                if u - t > self.Wq:
                    # a dropped conviction starts over: evidence accumulated while queued is discarded,
                    # otherwise the replica would be re-queued without any new evidence
                    s["W"][k] = 0.0
                    s["W2"][k] = 0.0
                    st.rule_log.append(("drop", int(k), int(u)))
                elif not blocked and not s["excluded"][k] and self._room(s, k, cap_n):
                    self._exclude(st, s, k, u, sf)
                else:
                    if not s["excluded"][k]:
                        blocked = True          # strict FIFO: later entries wait behind the head
                    keep.append((k, t, sf))
            s["queue"] = keep
            if self.presence_theta is not None and u % self.presence_every == 0:
                rows = [x for x in range(max(1, u - self.presence_window + 1), u + 1) if st.prop_parent[x] >= 0]
                if len(rows) >= self.presence_window // 2:
                    pres = presence_seen(st, rows).mean(axis=0)
                    queued = {e[0] for e in s["queue"]}
                    for k in np.flatnonzero((pres < self.presence_theta) & ~s["excluded"] & ~s["g1"] & st.alive):
                        if k not in queued:
                            st.rule_log.append(("presence", int(k), int(u)))
                            self._convict(st, s, k, u, cap_n)
            L = st.leaders[u]
            if L < 0 or s["excluded"][L]:
                continue
            s["W"][L] = max(0.0, s["W"][L] + (self.up if bad_fact(st, u, v, self.evidence) else self.down))
            if s["W"][L] >= self.h:
                self._convict(st, s, L, u, cap_n)
            elif self.soft_evidence is not None:
                s["W2"][L] = max(0.0, s["W2"][L] + (self.s_up if bad_fact(st, u, v, self.soft_evidence) else self.s_down))
                if s["W2"][L] >= self.h:
                    self._convict(st, s, L, u, cap_n, soft=True)
        s["done"] = max(s["done"], v - st.cfg.lag)
        return s

    def blocked(self, st, v):
        """Replicas that may not lead view v: soft exclusions plus proven liars (G1)."""
        s = self._advance(st, v)
        return s["excluded"] | s["g1"]

    def leader(self, v, st):
        s = self._advance(st, v)
        w = (~(s["excluded"] | s["g1"])).astype(float) * base_share(st, v)
        if w.sum() == 0:
            w = base_share(st, v)
        return _draw(st, v, w)


def slot_score(st, u: int, lie: bool = True, excl: np.ndarray = None, shift_index: bool = False) -> float:
    """Slot-duration score of view u (评分与性能 v0.2 §1-§2, §6.1).

    Honest replica j reports e_j = entry_j(u+1) - entry_j(u) = know[u, j] - know[u-1, j]. The
    certificate carries q = 2f+1 reports and the score is their (f+1)-th smallest. Colluders lie
    (lie=True): they report +inf for an honest leader and 0 for a colluding leader; a colluding
    certificate assembler (the leader of u+1) includes all colluder reports and picks the honest
    reports that suit it best, an honest assembler takes the colluder reports and the honest
    reports that arrive first (smallest entry into u+1). A view ended by TC scores at least tau
    (the independently submitted TC, v0.2 §1). Facts are read with the leader-rule lag.
    excl (NRC-2): replicas removed from the report pool (proven liars, K); the certificate takes q
    reports from the rest and the score stays the (f+1)-th smallest (review M1: this already removes
    the liars' leverage without moving the statistic); shift_index=True takes the (f-k+1)-th instead.
    A colluding assembler picks the honest reports even when no colluder is left in the pool (M2)."""
    cfg = st.cfg
    q, f = cfg.quorum, cfg.f
    pool = st.alive.copy() if excl is None else (st.alive & ~excl)
    if excl is not None and shift_index:
        f = f - int(excl.sum())
    H = np.flatnonzero(st.honest & pool)
    e = st.know[u, H] - st.know[u - 1, H]
    e = e[np.isfinite(e)]
    b = int((st.byz & pool).sum())
    L, C = st.leaders[u], st.leaders[u + 1]
    leader_byz = st.byz[L] if L >= 0 else False
    if lie and (b or (C >= 0 and st.byz[C])):
        byz_val = 0.0 if leader_byz else np.inf
        take = max(0, q - b)
        if st.byz[C]:
            hon = np.sort(e)[:take] if leader_byz else np.sort(e)[::-1][:take]
        else:
            first = np.argsort(st.know[u, H][np.isfinite(st.know[u, H] - st.know[u - 1, H])])[:take]
            hon = e[first]
        rep = np.concatenate([hon, np.full(b, byz_val)])
    else:
        rep = np.sort(e)[:q]
    rep = np.sort(rep)
    x = float(rep[min(f, len(rep) - 1)]) if len(rep) else cfg.tau_ms
    if st.tc_exists[u]:
        x = max(x, cfg.tau_ms)
    return x


def weighted_slot_score(st, u: int, lie: bool = True) -> float:
    """Weighted slot-duration score of view u (信任2.0_协议级验证 §3.6; weighted analogue of slot_score).

    Replica j reports e_j = entry_j(u+1) - entry_j(u) (know[u, j] - know[u-1, j]). The next certificate
    carries reports of a set with voting share strictly above 2/3 (W_QUORUM) and the score is the
    weighted 1/3-quantile: the smallest reported value x such that the reports <= x hold a share above
    1/3 of the whole table. With a Byzantine share below 1/3, x lies between the smallest and the largest
    honest report in the certificate: colluders cannot pull it below the fastest honest report (shield)
    nor above the slowest (frame).
    Colluders lie (lie=True): they report 0 for a colluding leader and +inf for an honest one. A colluding
    certificate assembler (leader of u+1) includes all colluder reports and the honest reports that suit
    it best (fastest to shield, slowest to frame); an honest assembler takes the colluder reports and the
    honest reports that arrive first. Without colluders (or lie=False) the first reports of all replicas
    are taken. A view ended by TC scores at least tau (as slot_score). Facts are read with the leader-rule
    lag (entries of u+1 are fixed by then)."""
    cfg = st.cfg
    w = np.asarray(base_share(st, u), float)
    w = w / w.sum()
    alive = st.alive
    L, C = st.leaders[u], (st.leaders[u + 1] if u + 1 < len(st.leaders) else -1)
    leader_byz = bool(L >= 0 and st.byz[L])
    byz_ids = np.flatnonzero(st.byz & alive)
    lying = lie and byz_ids.size > 0
    pool = np.flatnonzero((st.honest if lying else np.ones(cfg.n, bool)) & alive)
    e = st.know[u, pool] - st.know[u - 1, pool]
    ok = np.isfinite(e)
    pool, e = pool[ok], e[ok]
    vals, wts, acc = [], [], 0.0
    if lying:
        val = 0.0 if leader_byz else np.inf
        for k in byz_ids:
            vals.append(val)
            wts.append(w[k])
            acc += w[k]
        if C >= 0 and st.byz[C]:
            order = np.argsort(e, kind="stable") if leader_byz else np.argsort(-e, kind="stable")
        else:
            order = np.argsort(st.know[u, pool], kind="stable")
    else:
        order = np.argsort(st.know[u, pool], kind="stable")
    for i in order:
        if weighted_hit(acc):
            break
        vals.append(float(e[i]))
        wts.append(w[pool[i]])
        acc += w[pool[i]]
    x = cfg.tau_ms
    if weighted_hit(acc):
        idx = np.argsort(vals, kind="stable")
        cum = np.cumsum(np.asarray(wts)[idx])
        j = int(np.argmax(cum > 1 / 3 + 1e-9))
        x = float(np.asarray(vals)[idx][j])
    if st.tc_exists[u]:
        x = max(x, cfg.tau_ms)
    return x


class PerfTilt(LeaderRule):
    """R6: R5 (AT + CUSUM exclusion, optional) plus a bounded tilt on slot-duration scores
    (评分与性能 v0.2 §5-§6): estimate = mean of the replica's last W own scores, samples older than
    V views are dropped and missing samples filled with the baseline b = (f+1)-th smallest estimate
    among replicas with samples; weight clip(exp(-L (estimate - b)), 1/K, 1). L is per ms.
    clean = True (NRC-2, needs cfg.track_signed): each view's score is taken from the report pool
    without the proven liars known at the time (slot_score(excl=liars)), keeping the (f+1)-th smallest."""
    name = "R6_perf_tilt"

    def __init__(self, L: float, K: float = 20.0, W: int = 20, V: int = 2000, lie: bool = True,
                 exclusion: "CusumExclusion" = None, clean: bool = False):
        self.L, self.K, self.W, self.V, self.lie, self.exclusion = L, K, W, V, lie, exclusion
        self.clean = clean

    def _scores(self, st, v):
        c = st.__dict__.setdefault("_tilt_cache", {})
        if id(self) not in c:
            c[id(self)] = dict(samples=[[] for _ in range(st.cfg.n)], done=0)
        s = c[id(self)]
        K = liars(st, v) if self.clean else None
        for u in range(s["done"] + 1, v - st.cfg.lag + 1):
            if u < 1:
                continue
            L = st.leaders[u]
            if L >= 0:
                s["samples"][L].append((u, slot_score(st, u, self.lie, excl=K)))
        s["done"] = max(s["done"], v - st.cfg.lag)
        return s

    def weights(self, v, st):
        s = self._scores(st, v)
        n, f = st.cfg.n, st.cfg.f
        est = np.full(n, np.nan)
        cnt = np.zeros(n, int)
        for i in range(n):
            recent = [x for (u, x) in s["samples"][i][-self.W:] if u >= v - self.V]
            cnt[i] = len(recent)
            if recent:
                est[i] = float(np.mean(recent))
        have = np.flatnonzero(cnt > 0)
        base = float(np.sort(est[have])[min(f, len(have) - 1)]) if len(have) else 0.0
        for i in range(n):            # fill missing samples with the baseline (neutral)
            if cnt[i] < self.W:
                tot = (est[i] * cnt[i] if cnt[i] else 0.0) + base * (self.W - cnt[i])
                est[i] = tot / self.W
        w = np.clip(np.exp(-self.L * (est - base)), 1.0 / self.K, 1.0)
        if self.exclusion is not None:
            ex = self.exclusion.blocked(st, v)
            w = np.where(ex, 0.0, w)
            if w.sum() == 0:
                w[:] = 1.0
        return w

    def leader(self, v, st):
        return _draw(st, v, self.weights(v, st))


def project_box_simplex(w: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Scale w by lambda and clip to [lo, hi] so that it sums to 1 (bisection on lambda);
    requires n*lo <= 1 <= n*hi."""
    w = np.maximum(w, 1e-300)
    a_, b_ = 0.0, 1.0
    while np.clip(w * b_, lo, hi).sum() < 1.0:
        b_ *= 2.0
    for _ in range(100):
        m = 0.5 * (a_ + b_)
        if np.clip(w * m, lo, hi).sum() < 1.0:
            a_ = m
        else:
            b_ = m
    p = np.clip(w * b_, lo, hi)
    return p / p.sum()


class CappedHedge(PerfTilt):
    """R7 (direction C): exponential weights on slot-duration estimates that REWARD fast replicas as
    well as penalise slow ones, projected onto the box {a/n <= p_i <= c/n} of the simplex. The cap
    bounds the colluders' exposure by c * beta0 deterministically (C2); the floor keeps every replica
    sampled. eta is per ms. Same estimates (window W, expiry V, baseline fill) as R6."""
    name = "R7_capped_hedge"

    def __init__(self, eta: float, a: float = 0.5, c: float = 2.0, W: int = 20, V: int = 2000, lie: bool = True,
                 exclusion: "CusumExclusion" = None):
        super().__init__(L=eta, K=1.0, W=W, V=V, lie=lie, exclusion=exclusion)
        self.eta, self.a, self.c = eta, a, c

    def weights(self, v, st):
        s = self._scores(st, v)
        n, f = st.cfg.n, st.cfg.f
        est = np.full(n, np.nan)
        cnt = np.zeros(n, int)
        for i in range(n):
            recent = [x for (u, x) in s["samples"][i][-self.W:] if u >= v - self.V]
            cnt[i] = len(recent)
            if recent:
                est[i] = float(np.mean(recent))
        have = np.flatnonzero(cnt > 0)
        base = float(np.sort(est[have])[min(f, len(have) - 1)]) if len(have) else 0.0
        for i in range(n):
            if cnt[i] < self.W:
                est[i] = ((est[i] * cnt[i]) if cnt[i] else 0.0) / self.W + base * (self.W - cnt[i]) / self.W
        raw = np.exp(-self.eta * (est - est.min()))
        alive_mask = np.ones(n, bool)
        if self.exclusion is not None:
            alive_mask = ~self.exclusion.blocked(st, v)
        m = int(alive_mask.sum())
        p = np.zeros(n)
        if m == 0:
            return np.ones(n)
        lo, hi = self.a / m, min(1.0, self.c / m)
        p[alive_mask] = project_box_simplex(raw[alive_mask], lo, hi)
        return p


MIN_LAG = 6   # facts of view u read prop_parent rows up to v-3; the fast engine reads leader(x+2)


def verify_leaders(res, cfg) -> int:
    """Recompute the dynamic schedule from the FINAL outcome facts and count views whose leader
    differs from the one used in the run (0 means no leader was computed from stale facts)."""
    if cfg.leader_rule is None:
        return 0
    from .common import State
    st = State(cfg)
    V = cfg.views
    st.prop_parent[: V + 1] = res.prop_parent[: V + 1]
    st.nr_count[: V + 1] = res.nr_count[: V + 1]
    if getattr(res, "nr_w", None) is not None:
        st.nr_w[: V + 1] = res.nr_w[: V + 1]
    st.qc_via_tmo[: V + 1] = res.qc_via_tmo[: V + 1]
    if res.tmo_votes is not None:
        st.tmo_votes[: V + 1] = res.tmo_votes[: V + 1]
    for name in ("nr1", "vote_seen", "vote_timely", "vote_carried", "qc_pub"):
        if getattr(res, name, None) is not None:
            getattr(st, name)[: V + 1] = getattr(res, name)[: V + 1]
    st.qc_exists[: V + 1] = res.qc_exists[: V + 1]
    st.prop_time[: V + 1] = res.prop_time[: V + 1]
    st.know[:] = res.know
    st.tc_exists[:] = res.tc_exists
    fill_leaders(st, V)
    return int((st.leaders[1:V + 1] != res.leaders[1:V + 1]).sum())


def fill_leaders(st, w: int) -> None:
    """Compute leaders up to view w in order (dynamic rule)."""
    if st.cfg.lag < MIN_LAG:
        raise ValueError(f"lag={st.cfg.lag} < {MIN_LAG}: outcome facts would be read before they are final")
    rule = st.cfg.leader_rule
    top = min(w, len(st.leaders) - 1)
    for v in range(st._lead_known + 1, top + 1):
        st.leaders[v] = rule.leader(v, st)
    st._lead_known = max(st._lead_known, top)


def e3_violators(st) -> np.ndarray:
    """Accountable-safety evidence E3 (理论_可问责安全与纪元交接 §2.3) from the signed logs (needs
    cfg.track_signed): replica k signed a vote of v1 for a block whose justify view is j and a timeout of
    v2 >= v1 whose hq view is h < j. Returns a bool array over replicas."""
    n = st.cfg.n
    vmax = {}                                         # k -> list of (v1, j)
    for k, v, j in st.sig_votes:
        vmax.setdefault(k, []).append((v, j))
    out = np.zeros(n, bool)
    for k, v2, h in st.sig_tmos:
        if out[k]:
            continue
        for v1, j in vmax.get(k, ()):
            if v2 >= v1 and h < j:
                out[k] = True
                break
    return out

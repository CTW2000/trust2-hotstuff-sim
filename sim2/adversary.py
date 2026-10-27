"""Adversary plugins. An adversary decides, per view, what the Byzantine replicas do differently
from the protocol. Plans are pure functions of (view, leaders, roles), so both engines apply the
same plan. Fields only affect Byzantine replicas.

ViewPlan fields (view w):
  prop_targets       bool mask of replicas that receive the proposal of w (Byzantine leader); None = all
  prop_extra_ms      extra delay per recipient of that proposal (Byzantine leader); None = 0
  silent_voters      Byzantine replicas that do not vote in w
  collector_withhold P1 only: a Byzantine leader of w+1 ignores the votes of w (forms no QC(w))
  nr_claim           None: Byzantine timeouts of w report NR truthfully; 1 or 0: they claim that value
                     (1 frames an honest leader, 0 shields a colluding leader)
  payload_targets    Byzantine leader of w: replicas that receive the block data together with the
                     header (others get the signed header only and must fetch the data); None = all
  vote_targets       Byzantine voters in w send their vote only to these replicas; None = normal
  tmo_vote_omit      Byzantine timeouts of w do not carry the sender's vote (direction A)
  tmo_extra_ms       extra delay per receiver of Byzantine timeouts of w (direction A attacks)
  tmo_early_ms       Byzantine replicas time out early in w (direction A, review A-3)
  prop_before_timeout_ms, vote_pad_to   late-proposal attack on an honest collector (review v0.3 S1)
"""
from dataclasses import dataclass, field
from typing import FrozenSet, List, Optional

import numpy as np


@dataclass
class ViewPlan:
    prop_targets: Optional[np.ndarray] = None
    prop_extra_ms: Optional[np.ndarray] = None
    silent_voters: FrozenSet[int] = field(default_factory=frozenset)
    collector_withhold: bool = False
    nr_claim: Optional[int] = None
    payload_targets: Optional[np.ndarray] = None
    vote_targets: Optional[np.ndarray] = None
    tmo_vote_omit: bool = False          # Byzantine timeouts of w do not carry their vote
    tmo_extra_ms: Optional[np.ndarray] = None  # extra delay per receiver of Byzantine timeouts of w; None = 0
    tmo_early_ms: Optional[float] = None       # Byzantine replicas time out this long after entering w
                                               # (instead of tau); None = at tau
    prop_before_timeout_ms: Optional[float] = None  # Byzantine leader of w: each recipient gets the proposal
                                               # this long before its own timer of w fires (needs the
                                               # recipient's entry time: an omniscient model-S scheduler)
    vote_pad_to: Optional[np.ndarray] = None   # model-S scheduling of honest messages: votes of w to these
                                               # receivers take the full Delta (net.delta_max())
    qc_exclude: FrozenSet[int] = field(default_factory=frozenset)  # a Byzantine replica forming QC(w) leaves
                                               # these voters out of it (presence framing through signer choice)
    tmo_after_vote: FrozenSet[int] = field(default_factory=frozenset)  # these Byzantine voters of w broadcast
                                               # their timeout of w (with the nr_claim) right after voting
                                               # ("greedy liar", NR self-contradiction)


class Adversary:
    name = "follow_protocol"

    def plan(self, w: int, st) -> ViewPlan:
        return ViewPlan()


class WithholdVotesOnHonest(Adversary):
    """A2 (P2 framing): Byzantine replicas do not vote in views led by honest replicas. In model P an
    honest leader then fails whenever one honest replica misses its proposal."""
    name = "A2_withhold_votes"

    def plan(self, w, st):
        if st.honest[st.leader(w)]:
            return ViewPlan(silent_voters=frozenset(np.flatnonzero(st.byz).tolist()))
        return ViewPlan()


class CollectorFraming(Adversary):
    """A1 (P1 framing): a Byzantine next leader ignores the votes for an honest leader's block, so
    the view ends by TC and the block is orphaned. With omit_tmo_votes, colluders also leave their
    votes out of their timeouts (against direction A's QC reconstruction). With early_ms, colluders
    also time out early (review A-3: the TC forms from their timeouts plus the earliest honest ones,
    so later honest replicas leave by the forwarded TC without timing out themselves)."""
    name = "A1_collector_framing"

    def __init__(self, omit_tmo_votes: bool = True, early_ms: float = None):
        self.omit, self.early = omit_tmo_votes, early_ms

    def plan(self, w, st):
        if st.honest[st.leader(w)] and st.byz[st.leader(w + 1)]:
            return ViewPlan(collector_withhold=True, tmo_vote_omit=self.omit, tmo_early_ms=self.early)
        return ViewPlan()


class SilentLeader(Adversary):
    """A3: a Byzantine leader sends no proposal (attributable by AT), in each of its views with
    probability p (seeded per view)."""
    name = "A3_silent_leader"

    def __init__(self, p: float = 1.0, start_view: int = 0):
        self.p, self.start_view = p, start_view

    def plan(self, w, st):
        if w >= self.start_view and st.byz[st.leader(w)]:
            if self.p >= 1.0 or np.random.default_rng([st.cfg.seed, 31, w]).random() < self.p:
                return ViewPlan(prop_targets=np.zeros(st.cfg.n, bool))
        return ViewPlan()


class SlowLeader(Adversary):
    """A5: a colluding leader delays its proposal to every recipient by xi ms (slow but successful
    while xi stays well below the timeout), in each of its views with probability p."""
    name = "A5_slow_leader"

    def __init__(self, xi_ms: float, p: float = 1.0):
        self.xi, self.p = xi_ms, p

    def plan(self, w, st):
        if st.byz[st.leader(w)]:
            if self.p >= 1.0 or np.random.default_rng([st.cfg.seed, 41, w]).random() < self.p:
                return ViewPlan(prop_extra_ms=np.full(st.cfg.n, self.xi))
        return ViewPlan()


class DataWithhold(Adversary):
    """A7: a colluding leader sends the signed header to everyone but the block data only to the
    colluders and k honest replicas; the others must fetch the data (colluders refuse to serve).
    k = 0: no honest replica can get the data, nobody honest can vote, the view fails, and yet
    every honest replica holds the signed header (NR = 0), so AT does not accuse the leader.
    Applied in each colluder-led view with probability p."""
    name = "A7_data_withhold"

    def __init__(self, k: int = 1, p: float = 1.0):
        self.k, self.p = k, p

    def plan(self, w, st):
        if not st.byz[st.leader(w)]:
            return ViewPlan()
        if self.p < 1.0 and np.random.default_rng([st.cfg.seed, 47, w]).random() >= self.p:
            return ViewPlan()
        mask = st.byz.copy()
        if self.k > 0:
            honest_idx = np.flatnonzero(st.honest)
            rng = np.random.default_rng([st.cfg.seed, 53, w])
            mask[rng.choice(honest_idx, size=min(self.k, honest_idx.size), replace=False)] = True
        silent = frozenset(np.flatnonzero(st.byz).tolist()) if self.k == 0 else frozenset()
        return ViewPlan(payload_targets=mask, silent_voters=silent)


class SkewVotes(Adversary):
    """Cost shifting through entry skew (v0.2 review M2): in colluder-led views the colluders send
    their votes only to a group of g honest replicas, which then enter the next view early while
    the other honest replicas wait for all honest votes; in honest-led views they withhold."""
    name = "skew_votes"

    def __init__(self, g: int = 5):
        self.g = g

    def plan(self, w, st):
        byz_ids = frozenset(np.flatnonzero(st.byz).tolist())
        if st.honest[st.leader(w)]:
            return ViewPlan(silent_voters=byz_ids)
        tg = st.byz.copy()
        tg[np.flatnonzero(st.honest)[: self.g]] = True
        return ViewPlan(vote_targets=tg)


class FrameCollector(Adversary):
    """Against direction A (P1): when the collector (leader of w+1) is honest, colluders vote but
    send their vote only to replicas other than the collector, so the honest collector may miss 2f+1
    votes while the votes reappear in the colluders' timeouts (making it look as if the collector
    withheld). Combined with CollectorFraming when the collector is a colluder."""
    name = "frame_collector"

    def plan(self, w, st):
        C = st.leader(w + 1)
        if st.honest[C]:
            tg = np.ones(st.cfg.n, bool)
            tg[C] = False
            return ViewPlan(vote_targets=tg)
        return ViewPlan()


class LieNR(Adversary):
    """Byzantine replicas lie in their AT bits: NR=1 in views of honest leaders (framing through
    AT) and NR=0 in views of colluding leaders (shielding them)."""
    name = "lie_NR"

    def __init__(self, start_view: int = 0):
        self.start_view = start_view

    def plan(self, w, st):
        if w < self.start_view:
            return ViewPlan()
        return ViewPlan(nr_claim=1 if st.honest[st.leader(w)] else 0)


class PartialSend(Adversary):
    """A4: a Byzantine leader sends its proposal to the Byzantine replicas and to only k honest
    replicas, and the Byzantine replicas do not vote, so the view fails (not attributable by AT
    when k is large enough), in each of its views with probability p.
    targeted=True (weighted voting): the k honest recipients are the heaviest by the voting shares of
    the view (the adversary minimises the NR=1 share left for AT)."""
    name = "A4_partial_send"

    def __init__(self, k: int = 1, start_view: int = 0, p: float = 1.0, targeted: bool = False):
        self.k, self.start_view, self.p, self.targeted = k, start_view, p, targeted

    def plan(self, w, st):
        if w < self.start_view or not st.byz[st.leader(w)]:
            return ViewPlan()
        if self.p < 1.0 and np.random.default_rng([st.cfg.seed, 43, w]).random() >= self.p:
            return ViewPlan()
        honest_idx = np.flatnonzero(st.honest)
        if self.targeted and st.cfg.vote_weights is not None:
            sh = np.asarray(st.cfg.vote_weights(st, w), float)[honest_idx]
            chosen = honest_idx[np.argsort(-sh, kind="stable")[:self.k]]
        else:
            rng = np.random.default_rng([st.cfg.seed, 23, w])
            chosen = rng.choice(honest_idx, size=min(self.k, honest_idx.size), replace=False)
        mask = st.byz.copy()
        mask[chosen] = True
        return ViewPlan(prop_targets=mask, silent_voters=frozenset(np.flatnonzero(st.byz).tolist()))


class AdaptivePartialSend(Adversary):
    """Rule-aware targeted partial send (信任2.0_协议级验证 §3.4): a colluding leader knows the soft
    "noqc" CUSUM of the leader rule (s_up, s_down, h) and runs its own copy over the outcomes of its
    led views (qc_exists, which it observes); it attacks (sends to the k heaviest honest replicas,
    colluders do not vote) only when one more failure keeps its copy below (1 - margin) * h.
    It reads the public rule log: when the rule excludes, queues or drops it, the rule's soft CUSUM is
    reset, so it resets its copy too. A threshold strategy, not a proven worst case."""
    name = "adaptive_partial_send"

    def __init__(self, k: int, s_up: float, s_down: float, h: float, margin: float = 0.0):
        self.k, self.s_up, self.s_down, self.h, self.margin = k, s_up, s_down, h, margin
        self._W, self._seen, self._logpos = {}, {}, {}

    def plan(self, w, st):
        L = st.leader(w)
        if not st.byz[L]:
            return ViewPlan()
        sid = id(st)
        for ev, node, u in st.rule_log[self._logpos.get(sid, 0):]:
            if ev in ("exclude", "exclude_soft", "queue", "drop") and st.byz[node]:
                self._W[(sid, node)] = 0.0
                self._seen[(sid, node)] = max(self._seen.get((sid, node), 0), u)
        self._logpos[sid] = len(st.rule_log)
        W, last = self._W.get((sid, L), 0.0), self._seen.get((sid, L), 0)
        for u in range(last + 1, w):              # replay the outcomes of its own past views
            if st.leaders[u] == L:
                W = max(0.0, W + (self.s_down if st.qc_exists[u] else self.s_up))
        self._W[(sid, L)], self._seen[(sid, L)] = W, max(last, w - 1)
        if W + self.s_up >= (1.0 - self.margin) * self.h:
            return ViewPlan()
        honest_idx = np.flatnonzero(st.honest)
        if st.cfg.vote_weights is None:
            sh = np.ones(honest_idx.size)
        else:
            sh = np.asarray(st.cfg.vote_weights(st, w), float)[honest_idx]
        chosen = honest_idx[np.argsort(-sh, kind="stable")[:self.k]]
        mask = st.byz.copy()
        mask[chosen] = True
        return ViewPlan(prop_targets=mask, silent_voters=frozenset(np.flatnonzero(st.byz).tolist()))


def _timed_plan(st, w, k, margin, base_lat, tau):
    """Proposal only to colluders and the k heaviest honest replicas R, released so that R receives it
    about `margin` ms before its own timeout (the leader knows the base latencies); colluders do not vote."""
    L = st.leader(w)
    honest_idx = np.flatnonzero(st.honest)
    if st.cfg.vote_weights is None:
        sh = np.ones(honest_idx.size)
    else:
        sh = np.asarray(st.cfg.vote_weights(st, w), float)[honest_idx]
    chosen = honest_idx[np.argsort(-sh, kind="stable")[:k]]
    mask = st.byz.copy()
    mask[chosen] = True
    extra = np.zeros(st.cfg.n)
    extra[chosen] = np.maximum(0.0, tau - margin - base_lat[L, chosen])
    return ViewPlan(prop_targets=mask, prop_extra_ms=extra, silent_voters=frozenset(np.flatnonzero(st.byz).tolist()))


class TimedRelease(Adversary):
    """Timed release (review v0.8 结论与文档 #7): partial send to the k heaviest honest replicas R, timed to
    reach R about `margin` ms before its timeout. With proposal forwarding the forwarded copies reach the
    other replicas only after their timeouts, so the view still fails, and R (which holds the proposal)
    keeps the NR=1 share below the AT threshold when its share exceeds 1 - beta - x."""
    name = "timed_release"

    def __init__(self, k: int, margin: float, base_lat, tau: float):
        self.k, self.margin, self.base, self.tau = k, margin, base_lat, tau

    def plan(self, w, st):
        if not st.byz[st.leader(w)]:
            return ViewPlan()
        return _timed_plan(st, w, self.k, self.margin, self.base, self.tau)


class AdaptiveTimedRelease(AdaptivePartialSend):
    """Rule-aware timed release: attacks (timed release) only while its copy of the soft CUSUM stays
    below (1 - margin) h, as AdaptivePartialSend."""
    name = "adaptive_timed_release"

    def __init__(self, k, s_up, s_down, h, release_margin, base_lat, tau, margin=0.0):
        super().__init__(k, s_up, s_down, h, margin)
        self.release_margin, self.base, self.tau = release_margin, base_lat, tau

    def plan(self, w, st):
        p = super().plan(w, st)
        if p.prop_targets is None:
            return p
        return _timed_plan(st, w, self.k, self.release_margin, self.base, self.tau)


class LieNRVote(Adversary):
    """NR liars with a share of greedy ones (NR self-contradiction, E-NRC2/3). In views of honest
    leaders every colluder claims NR=1 (framing through AT); the first round(greedy * f0) colluders
    also vote (keeping their vote presence) and broadcast that timeout right after voting, which an
    honest replica holding their vote turns into a transferable proof; the others withhold their
    vote (consistent liars, undetectable). claim=False: nobody lies about NR (with greedy = 0 this is
    plain vote withholding). wp < 1: each non-greedy colluder withholds in each such view only with
    probability wp (partial withholding; it votes otherwise). In views of colluding leaders the
    colluders claim NR=0 (shield)."""
    name = "lie_NR_vote"

    def __init__(self, greedy: float = 1.0, claim: bool = True, wp: float = 1.0):
        self.greedy, self.claim, self.wp = greedy, claim, wp

    def plan(self, w, st):
        byz_ids = np.flatnonzero(st.byz)
        if st.byz[st.leader(w)]:
            return ViewPlan(nr_claim=0 if self.claim else None)
        g = int(round(self.greedy * len(byz_ids)))
        greedy = frozenset(int(k) for k in byz_ids[:g])
        rest = [int(k) for k in byz_ids[g:]]
        if self.wp < 1.0:
            rest = [k for k in rest if np.random.default_rng([st.cfg.seed, 61, w, k]).random() < self.wp]
        rest = frozenset(rest)
        return ViewPlan(nr_claim=1 if self.claim else None, silent_voters=rest, tmo_after_vote=greedy)


class PresenceFrame(Adversary):
    """Presence framing through signer choice (review S2): whenever a colluder forms a QC (P1: as the
    collector), it leaves the target honest replicas out of the QC; colluders otherwise follow the
    protocol. In P1 the target's vote then only counts through the colluder's own receipt, which it
    does not publish; in P2 the honest replicas' receipts keep it."""
    name = "presence_frame"

    def __init__(self, targets=(0,)):
        self.targets = frozenset(targets)

    def plan(self, w, st):
        return ViewPlan(qc_exclude=self.targets)


class Compose(Adversary):
    """Combine several adversaries: union of silent voters, intersection of proposal targets,
    sum of extra delays, OR of collector_withhold."""

    def __init__(self, parts: List[Adversary]):
        self.parts = parts
        self.name = "+".join(p.name for p in parts)

    def plan(self, w, st):
        out = ViewPlan()
        for p in self.parts:
            q = p.plan(w, st)
            if q.prop_targets is not None:
                out.prop_targets = q.prop_targets if out.prop_targets is None else (out.prop_targets & q.prop_targets)
            if q.prop_extra_ms is not None:
                out.prop_extra_ms = q.prop_extra_ms if out.prop_extra_ms is None else out.prop_extra_ms + q.prop_extra_ms
            out.silent_voters = out.silent_voters | q.silent_voters
            out.collector_withhold = out.collector_withhold or q.collector_withhold
            if q.nr_claim is not None:
                out.nr_claim = q.nr_claim
            out.tmo_vote_omit = out.tmo_vote_omit or q.tmo_vote_omit
            if q.tmo_extra_ms is not None:
                out.tmo_extra_ms = q.tmo_extra_ms if out.tmo_extra_ms is None else out.tmo_extra_ms + q.tmo_extra_ms
            out.tmo_after_vote = out.tmo_after_vote | q.tmo_after_vote
            out.qc_exclude = out.qc_exclude | q.qc_exclude
            if q.tmo_early_ms is not None:
                out.tmo_early_ms = q.tmo_early_ms if out.tmo_early_ms is None else min(out.tmo_early_ms, q.tmo_early_ms)
            for fld in ("payload_targets", "vote_targets"):
                a, b = getattr(out, fld), getattr(q, fld)
                if b is not None:
                    setattr(out, fld, b if a is None else (a & b))
        return out


def _partial_frame_plan(w, st, C, delay_ms, delay_all_ms=1000.0):
    """Plan of the 方向A v0.2 counterexample A2' (colluding leader of w, honest collector C):
    the proposal reaches the colluders and exactly q-1 honest replicas including C, so C gets q-1
    direct votes; colluders vote but not to C (in P1: no direct vote) and carry their votes in their
    timeouts, which reach C delay_ms late and everybody else delay_all_ms late (so that no replica
    reconstructs QC(w) and forwards it to C before C has formed TC(w); without this, C is rescued
    by the forwarded QC whenever its own TC is slow). C ends w by TC and extends below w, while the
    other replicas hold (q-1) + f0 >= q carried votes: rec_q(w) holds and the honest collector is
    blamed."""
    n, q = st.cfg.n, st.cfg.quorum
    hon = [int(k) for k in np.flatnonzero(st.honest) if k != C]
    e = len(hon) + 1 - (q - 1)                   # honest replicas left without the proposal
    if e < 1:
        return ViewPlan()
    rng = np.random.default_rng([st.cfg.seed, 99, w])
    mask = np.ones(n, bool)
    mask[rng.choice(hon, size=e, replace=False)] = False
    tg = np.ones(n, bool)
    tg[C] = False
    extra = np.full(n, delay_all_ms)
    extra[C] = delay_ms
    return ViewPlan(prop_targets=mask, vote_targets=tg, tmo_extra_ms=extra)


def _late_prop_plan(w, st, C, before_ms=1.0, delay_all_ms=1000.0):
    """Late-proposal framing of an honest collector C (review v0.3 S1; colluding leader of w).
    Every replica except C gets the proposal before_ms before its own timer of w fires, and honest
    votes to C take the full Delta (model-S scheduling), so C, which has no vote of its own, ends w
    by TC holding q-1 votes; colluders vote only inside their timeouts, which arrive delay_all_ms
    late. Everybody else sees up to n-1 carried votes and a single NR=1 (C's): for every tau <= n-1
    this signed record equals the one of a colluding C that withholds and lies NR=1, so without the
    tc_wait rule no threshold separates the two (A4 positive half fails); with tc_wait C collects
    every honest vote before proposing and the block is rescued."""
    n = st.cfg.n
    tg = np.ones(n, bool)
    tg[C] = False
    pad = np.zeros(n, bool)
    pad[C] = True
    return ViewPlan(prop_targets=tg, prop_before_timeout_ms=before_ms, vote_pad_to=pad, vote_targets=tg.copy(),
                    tmo_extra_ms=np.full(n, delay_all_ms))


class LateProposalFramer(Adversary):
    """Every colluder-led view with an honest collector: the late-proposal framing (_late_prop_plan)."""
    name = "late_prop_framer"

    def plan(self, w, st):
        L, C = st.leader(w), st.leader(w + 1)
        if st.byz[L] and st.honest[C]:
            return _late_prop_plan(w, st, C)
        return ViewPlan()


class PartialFrameCollector(Adversary):
    """方向A v0.2 A2' (review A-1): in every view led by a colluder whose collector is honest, frame
    the honest collector (see _partial_frame_plan). Combine with CollectorFraming for the other side."""
    name = "A2p_partial_frame_collector"

    def __init__(self, delay_ms: float = 20000.0):
        self.delay = delay_ms

    def plan(self, w, st):
        L, C = st.leader(w), st.leader(w + 1)
        if st.byz[L] and st.honest[C]:
            return _partial_frame_plan(w, st, C, self.delay)
        return ViewPlan()


class AdaptiveFramer(Adversary):
    """Informed, budgeted framing against a threshold reputation rule (方向A v0.2, review A-2).
    Attacks by role:
      "a2p":      as leader with an honest collector, A2' (frame the collector);
      "late":     as leader with an honest collector, the late-proposal framing (review v0.3 S1);
                  only used when listed in `free` (otherwise A2' is the costly leader attack);
      "withhold": as collector of an honest leader, withhold QC(w) and omit its vote from timeouts
                  (frame the leader, CollectorFraming).
    Attacks listed in `free` never charge the attacker under the evidence scheme in use (the
    adversary knows the rules), so they are always run. Any other attack is run only while the
    attacker's own estimate under the rule (rule.rates when leader(w+1) is chosen) is below
    margin * theta: with lag and forgetting only on the attacker's own opportunities, a rule
    whose low tier is absorbing punishes any overshoot for good, so the margin is conservative.
    focus = True: focused framing. Only the current target is attacked: the lowest-numbered honest
    replica whose estimate is still below theta. Every attack then lands on one victim while the
    cost is spread over all colluders, and once the victim is in the low tier the next one is
    taken (sequential exclusion)."""
    name = "adaptive_framer"

    def __init__(self, rule, free=(), margin: float = 0.5, delay_ms: float = 20000.0, focus: bool = False):
        self.rule, self.free, self.margin, self.delay, self.focus = rule, frozenset(free), margin, delay_ms, focus

    def _go(self, kind, r, k):
        return kind in self.free or r[k] < self.margin * self.rule.theta

    def plan(self, w, st):
        L, C = st.leader(w), st.leader(w + 1)
        if not (st.byz[L] or st.byz[C]):
            return ViewPlan()
        r = self.rule.rates(w + 1, st)
        if self.focus:
            cand = [int(k) for k in np.flatnonzero(st.honest) if r[k] < self.rule.theta]
            victim = cand[0] if cand else -1
            if victim not in (L, C):
                return ViewPlan()
        if st.byz[L] and st.honest[C]:
            if "a2p" not in self.free and "late" in self.free:
                return _late_prop_plan(w, st, C)
            if self._go("a2p", r, L):
                return _partial_frame_plan(w, st, C, self.delay)
            return ViewPlan()
        if st.honest[L] and st.byz[C] and self._go("withhold", r, C):
            return ViewPlan(collector_withhold=True, tmo_vote_omit=True)
        return ViewPlan()

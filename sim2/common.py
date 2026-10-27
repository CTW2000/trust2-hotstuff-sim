"""Shared definitions: configuration, roles, simulation state, chain utilities.

The protocol rules themselves live in ONE place: engine_event.py (replica state machines).
engine_fast.py adds closed-form kernels for the common case and calls engine_event for every
view it cannot solve in closed form. See engine_event's docstring for the semantics of P1 and P2.
"""
from dataclasses import dataclass, field
from typing import Any, List, Optional

import numpy as np

W_QUORUM = 2 / 3                       # weighted quorum: a share strictly above 2/3 (tolerates any share < 1/3)
W_EPS = 1e-9                           # float slack; shares are sums of at most n floats


def weighted_hit(x: float, thr: float = W_QUORUM) -> bool:
    """Share x is strictly above thr (with float slack W_EPS: x must exceed thr + W_EPS)."""
    return x > thr + W_EPS

QC, TC = 1, 2
HONEST, CRASHED, BYZANTINE = 0, 1, 2


@dataclass
class RunConfig:
    n: int = 16
    views: int = 200
    tau_ms: float = 2000.0
    protocol: str = "P2"               # "P2": votes broadcast; "P1": votes to the next leader only
    leader_mode: str = "round_robin"   # static schedule when leader_rule is None: or "random"
    leader_rule: Any = None            # a schedule.LeaderRule (dynamic, uses facts with a lag)
    lag: int = 10                      # leader of view v uses outcome facts of views <= v - lag
    adversary: Any = None              # an adversary.Adversary; None = Byzantine replicas follow the protocol
    crashed: List[int] = field(default_factory=list)
    byzantine: List[int] = field(default_factory=list)
    seed: int = 0
    forward: bool = True               # certificate forwarding (PM); False only for tests
    rho_nat: float = 0.0               # natural failure: any leader sends no proposal w.p. rho_nat
    vote_needs_parent: bool = False    # voting on block v also requires the data of its parent block
    nr_requires_data: bool = False     # AT bit NR = "no usable proposal (header AND data) by the timeout";
                                       # False: NR only looks at the signed header
    timeout_votes: bool = False        # direction A: a timeout carries the sender's vote of that view (if any),
                                       # so a QC can be reconstructed from 2f+1 timeouts
    tmo_after_leave: bool = True       # direction A (v0.2): a replica that voted in v but left v without QC(v)
                                       # (forwarded TC, or voted after leaving) still broadcasts its vote-carrying
                                       # timeout of v; only used with timeout_votes
    vote_weights: Any = None           # T_tru weighted voting: callable (st, v) -> voting shares of view v (sum 1);
                                       # QC/TC need a share strictly above 2/3 (weighted_hit; equal shares reproduce
                                       # counting when n is not a multiple of 3); leaders are drawn in proportion
                                       # (Uniform, CusumExclusion); event engine only
    prop_forward: Optional[str] = None  # proposal forwarding by honest replicas (信任2.0_协议级验证 §3.8):
                                       # "full" = forward the whole proposal (header, and the block if held) on first
                                       # receipt; "hdr" = forward the signed header only, replicas without the block
                                       # fetch it from honest holders (cascading); None = off (default).
                                       # Byte counts per view in st.prop_bytes
    uplink_serial: bool = False        # a sender's copies of the same proposal leave one after another (the r-th
                                       # copy waits r * size / bandwidth), for the leader with or without forwarding;
                                       # with prop_forward also for forwards, and a holder serves block requests one at
                                       # a time. Default off (the golden outputs assume no uplink contention)
    slot_theta_ms: Optional[float] = None  # weighted slot-duration evidence "slot" (schedule.weighted_slot_score):
                                       # a view whose robust slot score exceeds this many ms is a soft bad fact
    slot_theta_rel: Optional[float] = None  # relative threshold: the score must also exceed this multiple of the
                                       # median score of the previous slot_window views (on-chain computable); the
                                       # effective threshold is max(slot_theta_ms or 0, slot_theta_rel * median)
    slot_window: int = 200
    at_share: Optional[float] = None   # weighted AT: accuse when the NR=1 timeout share is strictly above this
                                       # (None = 2/3, the quorum); any value above the tolerated Byzantine share
                                       # keeps framing impossible after GST
    txlayer: Any = None                # inclusion attestations (G2): a txlayer.TxLayer bound to this run's
                                       # network; read lazily by the "omit" evidence (schedule.bad_fact)
    track_signed: bool = False         # NR self-contradiction (G1): record per view the signed NR claims and the
                                       # votes seen by honest replicas (st.nr1, st.vote_seen); event engine only.
                                       # Also logs every signed vote (k, v, justify view) in st.sig_votes and every
                                       # signed timeout (k, v, hq view) in st.sig_tmos (accountable safety, E3)
    vote_monotone: bool = False        # R3 of 理论_可问责安全与纪元交接 (as Aptos/Jolteon): a replica votes in v only if
                                       # v is above every view it has signed a vote or timeout for (no late votes for
                                       # views it already left with a timeout of a later view); event engine only
    tc_wait_ms: float = None           # direction A v0.4: an honest leader of v+1 that entered by TC(v) without
                                       # holding QC(v) waits this long (entry skew + Delta) before proposing, so
                                       # that every honest vote of v reaches it (directly or carried by a
                                       # timeout); None = propose at once. Only used with timeout_votes

    def glitch(self, v: int) -> bool:
        """Natural failure of the leader of view v (same draw in both engines)."""
        if self.rho_nat <= 0:
            return False
        return bool(np.random.default_rng([self.seed, 29, v]).random() < self.rho_nat)

    @property
    def f(self) -> int:
        return (self.n - 1) // 3

    @property
    def quorum(self) -> int:
        # smallest q with 2q - n >= f + 1 (two quorums intersect in an honest replica); 2f+1 when n = 3f+1
        return (self.n + self.f) // 2 + 1

    def roles(self) -> np.ndarray:
        r = np.full(self.n, HONEST, dtype=np.int8)
        r[list(self.byzantine)] = BYZANTINE
        r[list(self.crashed)] = CRASHED
        return r


def static_leaders(cfg: RunConfig) -> np.ndarray:
    """Static schedule for views 0..views+2 (index 0 unused)."""
    m = cfg.views + 3
    if cfg.leader_mode == "round_robin":
        lead = (np.arange(m) - 1) % cfg.n
    else:
        rng = np.random.default_rng([cfg.seed, 3])
        lead = rng.integers(0, cfg.n, m)
    lead[0] = -1
    return lead


class State:
    """All per-view outcome arrays of one run, shared by the engines and written in place.

    know[v, k]      first time k learns cert(v) (entry into v+1)
    qc_know[v, k]   first time k holds QC(v)
    cert_type[v, k] QC or TC, as first learned; cert_hq[v, k] the highQC that certificate carries
    qc_exists[v], tc_exists[v]  some replica formed QC(v) / TC(v)
    prop_parent[v]  parent view of the proposal of v, -1 if no proposal was sent; prop_time[v]
    leaders[v]      leader of view v (filled lazily for dynamic rules)
    Writes to qc_know rows older than the writer's view are logged so they can be undone.
    """

    def __init__(self, cfg: RunConfig):
        V, n = cfg.views, cfg.n
        self.cfg = cfg
        self.roles = cfg.roles()
        self.alive = self.roles != CRASHED
        self.honest = self.roles == HONEST
        self.byz = self.roles == BYZANTINE
        self.know = np.full((V + 1, n), np.inf)
        self.qc_know = np.full((V + 1, n), np.inf)
        self.cert_type = np.zeros((V + 1, n), dtype=np.int8)
        self.cert_hq = np.full((V + 1, n), -1)
        self.qc_exists = np.zeros(V + 1, bool)
        self.tc_exists = np.zeros(V + 1, bool)
        self.prop_parent = np.full(V + 2, -1)
        self.prop_time = np.full(V + 2, np.inf)
        self.nr_count = np.zeros(V + 1, dtype=int)   # distinct timeout senders of v with NR=1
        self.nr_w = np.zeros(V + 1)                  # weighted voting: total share of NR=1 timeout senders
        self.payload_time = np.full((V + 2, cfg.n), np.inf)   # when k holds the data of block v
        self.qc_via_tmo = np.zeros(V + 1, bool)  # some replica formed QC(v) with a vote carried by a timeout
        self.tmo_votes = np.zeros(V + 1, dtype=int)  # distinct senders of a vote-carrying timeout of v (rec_tau)
        self.sig_votes = []                          # track_signed: (k, v, justify view of the block of v)
        self.sig_tmos = []                           # track_signed: (k, v, view of the hq k signed into it)
        self.sig_order = []                          # track_signed: ("vote" | "tmo", k, v) in signing order
        self.nr1 = np.zeros((V + 1, n), bool)        # track_signed: k signed a timeout of v with NR=1
        self.vote_seen = np.zeros((V + 1, n), bool)  # track_signed: an honest replica holds k's signed vote of v
                                                     # (any time, direct or carried): G1 evidence
        self.vote_timely = np.zeros((V + 1, n), bool)  # track_signed: an honest replica received k's vote of v
                                                     # directly before its own timer of v (presence receipt)
        self.vote_carried = np.zeros((V + 1, n), bool)  # track_signed: k's vote of v reached an honest replica
                                                     # inside a timeout
        self.qc_pub = np.zeros((V + 1, n), bool)     # track_signed: k signed a QC(v) formed by a Byzantine replica
                                                     # (published in its next proposal; the assembler picks the signers)
        a = self.alive
        self.know[0, a] = 0.0
        self.qc_know[0, a] = 0.0
        self.cert_type[0, a] = QC
        self.cert_hq[0, a] = 0
        self.qc_exists[0] = True
        if cfg.leader_rule is None:
            self.leaders = static_leaders(cfg)
            self._lead_known = cfg.views + 2
        else:
            self.leaders = np.full(cfg.views + 3, -1)
            self._lead_known = 0
        self._plans = {}
        self.rule_log = []               # leader-rule events, e.g. ("exclude", replica, view)
        self.qc_log = []                 # (writer view, row, replica, old value)
        self.fallback_views = 0
        self.tc_kernel_views = 0
        self.window_views = 0
        self.leave_tmo_sent = 0          # timeouts sent under the direction-A leave rule (engine_event)

    # ---- QC knowledge with undo log
    def hold(self, view: int, u: int, k: int, t: float) -> None:
        if u >= 0 and t < self.qc_know[u, k]:
            if u < view:
                self.qc_log.append((view, u, k, self.qc_know[u, k]))
            self.qc_know[u, k] = t

    def hold_vec(self, view: int, u: int, idx: np.ndarray, t: np.ndarray) -> None:
        if u < 0:
            return
        old = self.qc_know[u, idx]
        ch = t < old
        if not ch.any():
            return
        if u < view:
            for k, o in zip(idx[ch], old[ch]):
                self.qc_log.append((view, u, int(k), o))
        self.qc_know[u, idx[ch]] = t[ch]

    def undo_from(self, start: int) -> None:
        while self.qc_log and self.qc_log[-1][0] >= start:
            _, u, k, old = self.qc_log.pop()
            self.qc_know[u, k] = old

    def reset_rows(self, s: int, e: int) -> None:
        rows = slice(s, e + 1)
        self.know[rows], self.qc_know[rows] = np.inf, np.inf
        self.cert_type[rows], self.cert_hq[rows] = 0, -1
        self.qc_exists[rows], self.tc_exists[rows] = False, False
        self.prop_parent[s:e + 2], self.prop_time[s:e + 2] = -1, np.inf
        self.nr_count[rows] = 0
        self.nr_w[rows] = 0.0
        self.payload_time[s:e + 2] = np.inf
        self.qc_via_tmo[rows] = False
        self.tmo_votes[rows] = 0
        self.nr1[rows] = False
        self.vote_seen[rows] = False
        self.vote_timely[rows] = False
        self.vote_carried[rows] = False
        self.qc_pub[rows] = False

    # ---- leaders and adversary plans
    def leader(self, w: int) -> int:
        if w > self._lead_known:
            from .schedule import fill_leaders
            fill_leaders(self, w)
        return int(self.leaders[w])

    def plan(self, w: int):
        p = self._plans.get(w)
        if p is None:
            from .adversary import ViewPlan
            adv = self.cfg.adversary
            p = ViewPlan() if adv is None or not self.byz.any() else adv.plan(w, self)
            self._plans[w] = p
        return p


def _serial(D_row, tx):
    """Extra delay of each copy when one sender sends to all others one after another (nearest first):
    the r-th copy (r = 0, 1, ...) waits r * tx. tx = 0 means no uplink contention."""
    if tx <= 0:
        return np.zeros_like(D_row)
    extra = np.zeros_like(D_row)
    extra[np.argsort(D_row, kind="stable")] = np.arange(D_row.size) * tx
    return extra


def _relay(arr, D, relay, tx=0.0):
    """Arrival times when replicas in `relay` forward to all on first receipt (Dijkstra; n is small).
    With tx > 0 a forwarder's copies leave one after another (_serial)."""
    arr = arr.copy()
    done = np.zeros(arr.size, bool)
    for _ in range(arr.size):
        cand = np.where(done | ~relay, np.inf, arr)
        j = int(np.argmin(cand))
        if not np.isfinite(cand[j]):
            break
        done[j] = True
        arr = np.minimum(arr, arr[j] + D[j] + _serial(D[j], tx))
    return arr


def _fetch_cascade(a, data, Dreq, Dresp, serve, tx=0.0):
    """Block arrival when every honest replica that holds the block (directly or by fetching) serves
    requests. Holders are taken in order of their block time; holder j serves, in order of request arrival,
    every replica k it can improve: the request leaves k at its header time a_k and reaches j at
    a_k + Dreq[k, j]; j answers at max(request, data_j, its previous answer + tx) and the block arrives
    Dresp[j, k] later (tx = 0: no uplink contention). Dijkstra on block times; n is small."""
    data = data.copy()
    done = np.zeros(data.size, bool)
    for _ in range(data.size):
        cand = np.where(done | ~serve, np.inf, data)
        j = int(np.argmin(cand))
        if not np.isfinite(cand[j]):
            break
        done[j] = True
        req = a + Dreq[:, j]
        free = data[j]
        for k in np.argsort(req, kind="stable"):
            if done[k] or k == j or not np.isfinite(req[k]):
                continue
            start = max(req[k], data[j], free)
            arrive = start + Dresp[j, k]
            if arrive < data[k]:
                data[k] = arrive
                free = start + tx
    return data


def proposal_timing(cfg, net, st, w: int, L: int, t: float, parent: int):
    """Shared by both engines: timing of the proposal of view w sent by L at time t.

    Returns (a, vt): a[k] = arrival of the signed header at k (inf if k gets nothing; this is
    what the AT bit refers to), vt[k] = when k is ready to vote (has the header, the block data
    and, if cfg.vote_needs_parent, the parent's data). Also writes st.payload_time[w].
    Block data: a Byzantine leader may send the data only to plan.payload_targets; the others get
    the header and fetch the data from honest holders (request: type "vote", response: type
    "prop", both keyed w): fetch_k = min_h max(a_k + Dreq[k, h], data_h) + Dresp[h, k]. Byzantine
    replicas do not serve data. Data obtained by fetching is not re-served (no cascade). With
    cfg.prop_forward the timing comes from _forwarded_timing (forwarding and cascading fetch)."""
    n = cfg.n
    alive, byz = st.alive, st.byz
    D = net.delays(w, "prop")
    a = t + D[L]
    full = np.ones(n, bool)
    if byz[L]:
        p = st.plan(w)
        if p.prop_targets is not None:
            a = np.where(p.prop_targets, a, np.inf)
        if p.prop_extra_ms is not None:
            a = a + p.prop_extra_ms
        if p.payload_targets is not None:
            full = p.payload_targets.copy()
    mode = cfg.prop_forward
    if mode:
        return _forwarded_timing(cfg, net, st, w, L, t, parent, a, full, D)
    if cfg.uplink_serial:                           # the leader's copies leave one after another
        a = a + _serial(D[L], net.cfg.sizes_bytes.get("prop", 0.0) * 8.0 / (net.cfg.bw_mbps * 1e3))
    a[L] = t
    full[L] = True
    a = np.where(alive, a, np.inf)
    data = np.where(full, a, np.inf)
    hdr_only = np.isfinite(a) & ~full
    if hdr_only.any():
        holders = np.flatnonzero(full & np.isfinite(a) & st.honest)
        if holders.size:
            Dreq = net.delays(w, "vote")
            ks = np.flatnonzero(hdr_only)
            cand = np.maximum(a[ks][:, None] + Dreq[np.ix_(ks, holders)], data[holders][None, :]) \
                + D[np.ix_(holders, ks)].T
            data[ks] = cand.min(axis=1)
    st.payload_time[w] = data
    sz = net.cfg.sizes_bytes                        # proposal bytes of view w: the leader's copies
    n_blk = int((np.isfinite(data) & np.isfinite(a)).sum()) - 1
    st.__dict__.setdefault("prop_bytes", {})[w] = n_blk * sz.get("prop", 0.0) + \
        (int(np.isfinite(a).sum()) - 1 - n_blk) * sz.get("fwd", 0.0)
    return _with_parent(cfg, net, st, w, parent, a, data)


def _with_parent(cfg, net, st, w, parent, a, data):
    vt = np.maximum(a, data)
    if cfg.vote_needs_parent and parent >= 1:
        pdata = st.payload_time[parent]
        need = np.isfinite(vt) & ~np.isfinite(pdata)
        pd = pdata.copy()
        if need.any():
            holders = np.flatnonzero(np.isfinite(pdata) & st.honest)
            if holders.size:
                Dreq, Dresp = net.delays(w, "vote"), net.delays(w, "prop")
                ks = np.flatnonzero(need)
                cand = np.maximum(a[ks][:, None] + Dreq[np.ix_(ks, holders)], pdata[holders][None, :]) \
                    + Dresp[np.ix_(holders, ks)].T
                pd[ks] = cand.min(axis=1)
        vt = np.maximum(vt, pd)
    return a, vt


def _forwarded_timing(cfg, net, st, w, L, t, parent, a, full, D):
    """proposal_timing with proposal forwarding (cfg.prop_forward; review v0.8 code C1, C2, C4).
    a: arrival of the leader's copies (after the plan's targets and extra delays), full: who gets the block
    from the leader. Honest replicas forward on first receipt ("hdr": the header; "full": the header and,
    if they hold it, the block); replicas without the block fetch it from honest holders (cascading). A
    replica's block time is its direct block arrival, a relayed block, or a fetch -- never the header time
    of a forwarded copy. With cfg.uplink_serial a sender's copies leave one after another."""
    n = cfg.n
    alive = st.alive
    sz = net.cfg.sizes_bytes
    bw = net.cfg.bw_mbps * 1e3                      # bits per ms
    tx_blk = sz.get("prop", 0.0) * 8.0 / bw if cfg.uplink_serial else 0.0
    tx_hdr = sz.get("fwd", 0.0) * 8.0 / bw if cfg.uplink_serial else 0.0
    if cfg.uplink_serial:                           # the leader's own copies leave one after another
        a = a + _serial(D[L], tx_blk)
    a[L] = t
    full = full.copy()
    full[L] = True
    a0 = np.where(alive, a, np.inf)                 # direct header arrival
    data0 = np.where(full, a0, np.inf)              # direct block arrival
    serve = st.honest & alive                       # honest holders serve block requests (the leader too)
    relay = serve.copy()
    relay[L] = False                                # the leader's copies are its own sends; the others forward
    Dfwd, Dreq = net.delays(w, "fwd"), net.delays(w, "vote")
    if cfg.prop_forward == "full":
        data_r = _relay(data0, D, relay, tx_blk)    # the block spreads with forwarded proposals
        a = np.minimum(_relay(a0, Dfwd, relay, tx_hdr), data_r)
    else:
        data_r = data0
        a = _relay(a0, Dfwd, relay, tx_hdr)         # the signed header spreads through honest replicas
    data = _fetch_cascade(a, data_r, Dreq, D, serve, tx_blk)
    st.payload_time[w] = data
    # bytes: leader copies; forwards by honest replicas other than the leader (block if they forward a
    # block, else header); one block per replica that got its block by fetching
    lead_blk = int((np.isfinite(data0) & alive).sum()) - 1
    lead_hdr = int((np.isfinite(a0) & alive).sum()) - 1 - lead_blk
    fw = relay
    if cfg.prop_forward == "full":
        n_fwd_blk = int((fw & np.isfinite(data_r)).sum())
        n_fwd_hdr = int((fw & np.isfinite(a) & ~np.isfinite(data_r)).sum())
    else:
        n_fwd_blk, n_fwd_hdr = 0, int((fw & np.isfinite(a)).sum())
    n_fetch = int((np.isfinite(data) & (data < data_r - 1e-9) & alive).sum())   # block obtained by fetching
    st.__dict__.setdefault("prop_bytes", {})[w] = (lead_blk + (n - 1) * n_fwd_blk + n_fetch) * sz.get("prop", 0.0) + \
        (lead_hdr + (n - 1) * n_fwd_hdr) * sz.get("fwd", 0.0)
    return _with_parent(cfg, net, st, w, parent, a, data)


def held_qc(qc_know: np.ndarray, k: int, t: float, upto: int) -> int:
    """hq_k(t): highest view u <= upto with qc_know[u, k] <= t (-1 if none)."""
    lo = max(0, upto - 256)
    while True:
        idx = np.flatnonzero(qc_know[lo:upto + 1, k] <= t)
        if idx.size:
            return lo + int(idx.max())
        if lo == 0:
            return -1
        hi, lo = lo - 1, max(0, lo - 4096)
        upto = hi


@dataclass
class Result:
    know: np.ndarray
    cert_type: np.ndarray
    qc_know: np.ndarray
    cert_hq: np.ndarray
    qc_exists: np.ndarray
    tc_exists: np.ndarray
    leaders: np.ndarray
    alive: np.ndarray
    honest: np.ndarray
    roles: np.ndarray
    prop_parent: np.ndarray
    prop_time: np.ndarray
    nr_count: np.ndarray = None
    nr_w: np.ndarray = None
    quorum: int = 0
    rule_log: list = None
    qc_via_tmo: np.ndarray = None
    tmo_votes: np.ndarray = None
    nr1: np.ndarray = None
    vote_seen: np.ndarray = None
    vote_timely: np.ndarray = None
    vote_carried: np.ndarray = None
    qc_pub: np.ndarray = None
    fallback_views: int = 0
    window_views: int = 0
    tc_kernel_views: int = 0

    @staticmethod
    def from_state(st: State) -> "Result":
        V = st.cfg.views
        return Result(know=st.know, cert_type=st.cert_type, qc_know=st.qc_know, cert_hq=st.cert_hq,
                      qc_exists=st.qc_exists, tc_exists=st.tc_exists, leaders=st.leaders[: V + 2].copy(),
                      alive=st.alive, honest=st.honest, roles=st.roles,
                      prop_parent=st.prop_parent[: V + 1].copy(), prop_time=st.prop_time[: V + 1].copy(),
                      nr_count=st.nr_count.copy(), nr_w=st.nr_w.copy(), quorum=st.cfg.quorum, rule_log=list(st.rule_log),
                      qc_via_tmo=st.qc_via_tmo.copy(), tmo_votes=st.tmo_votes.copy(),
                      nr1=st.nr1.copy(), vote_seen=st.vote_seen.copy(), vote_timely=st.vote_timely.copy(),
                      vote_carried=st.vote_carried.copy(), qc_pub=st.qc_pub.copy(),
                      fallback_views=st.fallback_views, window_views=st.window_views,
                      tc_kernel_views=st.tc_kernel_views)


def accused(nr_count: np.ndarray, quorum: int, u: int) -> bool:
    """AT: an accusation of the leader of u exists iff 2f+1 distinct timeouts of u carry NR=1
    (timeouts are broadcast, so any honest replica can assemble the accusation transaction)."""
    return bool(nr_count[u] >= quorum)


def block_parents(res: Result) -> np.ndarray:
    """parent[v] = view of the block that the proposal of view v extends (-1 if no proposal)."""
    return res.prop_parent


def commit_times(res: Result) -> np.ndarray:
    """commit[v, k]: time replica k learns that block v is committed (nan if never).

    Two-chain (Jolteon) for both P1 and P2: block u is directly committed when block u+1 exists,
    extends u, and QC(u+1) exists; replica k learns it at qc_know[u+1, k]. Ancestors of u are
    committed at the same time if not earlier."""
    V, n = res.know.shape[0] - 1, res.know.shape[1]
    parent = res.prop_parent
    out = np.full((V + 1, n), np.inf)
    for u in range(1, V):
        if parent[u] < 0 or parent[u + 1] != u or not res.qc_exists[u + 1]:
            continue
        T = res.qc_know[u + 1]
        b = u
        while b > 0:
            new = np.minimum(out[b], T)
            if np.array_equal(new, out[b]):
                break
            out[b] = new
            b = parent[b]
    out[np.isinf(out)] = np.nan
    return out


def check_sizes(cfg: RunConfig, net) -> None:
    if net.cfg.n != cfg.n:
        raise ValueError(f"RunConfig.n={cfg.n} but NetConfig.n={net.cfg.n}")
    if set(cfg.crashed) & set(cfg.byzantine):
        raise ValueError("a replica cannot be both crashed and Byzantine")
    if cfg.protocol not in ("P1", "P2"):
        raise ValueError(f"unknown protocol {cfg.protocol}")

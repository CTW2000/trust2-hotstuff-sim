"""Fast engine: closed-form kernels for views that end without any timeout.

The protocol rules are defined only in engine_event.py. For view v, given the entry times
know[v-1], the kernel computes in closed form (numpy):
  proposal arrivals a_k = entry_L + D_prop[L, k] (+ adversary extra delay, recipients mask);
  votes at a_k from all voters (alive, received the proposal, not withholding);
  P2: QC(v) at every k = (2f+1)-th smallest of a_m + D_vote[m, k];
  P1: QC(v) only at the collector C = leader(v+1) (unless a Byzantine C withholds);
  know[v] = shortest-path closure of the QC times over certificate forwards (key v+1) and the
            proposal of v+1 (sent by the next leader when it enters v+1).
This equals engine_event exactly when no replica times out in view v; otherwise the view is
solved by engine_event.simulate in place.

Causality anomalies (a replica learning cert(v) before cert(v-1)) break the per-view
decomposition; the views around one are re-solved by engine_event.simulate as a window, after
undoing writes the discarded views made to older QC-knowledge rows.
"""
import numpy as np

from . import engine_event
from .common import QC, TC, Result, RunConfig, State, check_sizes, held_qc, proposal_timing

WINDOW_BACK, WINDOW_AHEAD = 3, 4
USE_TC_KERNEL = True
_TEST_MUTATION = None   # tests only: "no_fixed_point" or "no_late_votes" plants a bug in _tc_kernel


def cfg_tc_kernel(cfg) -> bool:
    return USE_TC_KERNEL


class CausalityAnomaly(RuntimeError):
    pass


def _closure(x: np.ndarray, W: np.ndarray) -> np.ndarray:
    while True:
        y = np.minimum(x, (x[:, None] + W).min(axis=0))
        if np.array_equal(y, x):
            return y
        x = y


def _kernel(cfg: RunConfig, net, st: State, v: int) -> bool:
    n, q, tau = cfg.n, cfg.quorum, cfg.tau_ms
    alive, byz = st.alive, st.byz
    entry = st.know[v - 1]
    L, L2 = st.leader(v), st.leader(v + 1)
    if not alive[L] or not np.isfinite(entry[L]) or cfg.glitch(v):
        return False
    pv = st.plan(v)
    if byz[L] and pv.prop_targets is not None and not pv.prop_targets.any():
        return False
    parent = held_qc(st.qc_know, L, entry[L], v - 1)
    a, vt = proposal_timing(cfg, net, st, v, L, entry[L], parent)
    voters = alive & np.isfinite(vt)
    if byz.any() and pv.silent_voters:
        sv = [k for k in pv.silent_voters if byz[k]]     # plans only affect Byzantine replicas
        voters[sv] = False
    if voters.sum() < q:
        return False
    Dv = net.delays(v, "vote")
    arr = vt[:, None] + Dv                                # arr[m, j]: vote of m arrives at j
    if byz.any() and pv.vote_targets is not None:
        arr[np.ix_(byz, ~pv.vote_targets)] = np.inf
    arr = arr[voters]
    if cfg.protocol == "P2":
        qcv = np.partition(arr, q - 1, axis=0)[q - 1]
        qcv[~alive] = np.inf
    else:
        C = L2
        if not alive[C] or (byz[C] and pv.collector_withhold):
            return False
        qcv = np.full(n, np.inf)
        qcv[C] = np.partition(arr[:, C], q - 1)[q - 1]
    W = net.delays(v + 1, "fwd").copy() if cfg.forward else np.full((n, n), np.inf)
    p2 = _next_prop_row(cfg, net, st, v)
    if p2 is not None:
        W[L2] = np.minimum(W[L2], p2)
    W[~alive, :] = np.inf
    x = _closure(qcv, W)
    x[~alive] = np.inf
    if not np.all(x[alive] <= entry[alive] + tau):
        return False
    # commit the view
    st.prop_parent[v], st.prop_time[v] = parent, entry[L]
    recv = np.flatnonzero(np.isfinite(a) & (np.arange(n) != L))
    st.hold_vec(v, parent, recv, a[recv])
    if st.cert_type[v - 1, L] == TC:
        st.hold_vec(v, int(st.cert_hq[v - 1, L]), recv, a[recv])
    st.know[v] = x
    st.qc_know[v] = x            # every replica first learns a QC, so first QC time = know
    st.cert_type[v, alive] = QC
    st.cert_hq[v, alive] = v
    st.qc_exists[v] = True
    st.nr_count[v] = 0           # no timeouts in this view
    return True


def _closure_labels(x: np.ndarray, lab: np.ndarray, W: np.ndarray):
    """Shortest-path closure that also carries the label (highQC) of the first-arriving certificate."""
    while True:
        cand = x[:, None] + W
        src = cand.argmin(axis=0)
        best = cand[src, np.arange(len(x))]
        better = best < x
        if not better.any():
            return x, lab
        x = np.where(better, best, x)
        lab = np.where(better, lab[src], lab)


def _proposal_arrivals(cfg, net, st, v):
    """(header arrivals, vote-ready times, parent) of the proposal of v, or None if no proposal is
    sent (crashed, glitching or silent leader)."""
    alive, byz = st.alive, st.byz
    entry = st.know[v - 1]
    L = st.leader(v)
    if not alive[L] or not np.isfinite(entry[L]) or cfg.glitch(v):
        return None
    pv = st.plan(v)
    if byz[L] and pv.prop_targets is not None and not pv.prop_targets.any():
        return None
    parent = held_qc(st.qc_know, L, entry[L], v - 1)
    a, vt = proposal_timing(cfg, net, st, v, L, entry[L], parent)
    return a, vt, parent


def _next_prop_row(cfg, net, st, v):
    """Delays of the proposal of v+1 from its leader (inf where not sent), or None if there is
    no such proposal (crashed or silent leader, or a natural failure in v+1)."""
    L2 = st.leader(v + 1)
    if not st.alive[L2] or cfg.glitch(v + 1):
        return None
    p2 = net.delays(v + 1, "prop")[L2].copy()
    if st.byz[L2]:
        pn = st.plan(v + 1)
        if pn.prop_targets is not None:
            if not pn.prop_targets.any():
                return None
            p2 = np.where(pn.prop_targets, p2, np.inf)
        if pn.prop_extra_ms is not None:
            p2 = p2 + pn.prop_extra_ms
    p2[L2] = np.inf
    return p2


def _tc_kernel(cfg: RunConfig, net, st: State, v: int) -> bool:
    """Closed form for a view that ends by TC everywhere and in which no QC can ever form.

    Timeouts: replica m sends one at T_m = entry_m + tau iff it has not learned cert(v) by then.
    The sender set is the fixed point S = {m : x_m(S) > T_m}, where x(S) is the closure of the TC
    times formed from S. A QC can never form if fewer than 2f+1 replicas ever vote (P1: or the
    collector withholds). Every condition is checked; otherwise the caller falls back."""
    n, q, tau = cfg.n, cfg.quorum, cfg.tau_ms
    alive, byz = st.alive, st.byz
    alive_idx = np.flatnonzero(alive)
    entry = st.know[v - 1]
    L, L2 = st.leader(v), st.leader(v + 1)
    pv = st.plan(v)
    log_mark = len(st.qc_log)
    pa = _proposal_arrivals(cfg, net, st, v)
    sent = pa is not None
    parent = -1
    if sent:
        a, vt, parent = pa
        recv = np.flatnonzero(np.isfinite(a) & (np.arange(n) != L))
        st.hold_vec(v, parent, recv, a[recv])
        if st.cert_type[v - 1, L] == TC:
            st.hold_vec(v, int(st.cert_hq[v - 1, L]), recv, a[recv])
    else:
        a = np.full(n, np.inf)
        vt = a

    def abort():
        # undo the proposal holds (all writes above went to rows < v and were logged)
        while len(st.qc_log) > log_mark:
            _, u, k, old = st.qc_log.pop()
            st.qc_know[u, k] = old
        return False

    T = np.where(alive, entry + tau, np.inf)
    Dt = net.delays(v, "tmo")
    hq_send = np.array([held_qc(st.qc_know, m, T[m], v - 1) if alive[m] else -1 for m in range(n)])
    W = net.delays(v + 1, "fwd").copy() if cfg.forward else np.full((n, n), np.inf)
    p2 = _next_prop_row(cfg, net, st, v)
    if p2 is not None:
        W[L2] = np.minimum(W[L2], p2)
    W[~alive, :] = np.inf

    S = alive.copy()
    for _ in range(20):
        if S.sum() < q:
            return abort()
        A = T[S][:, None] + Dt[S]                      # arrivals of timeouts at every replica
        order = np.argsort(A, axis=0, kind="stable")[:q]
        tc_time = np.take_along_axis(A, order, axis=0)[q - 1]
        tc_hq = hq_send[np.flatnonzero(S)][order].max(axis=0)
        tc_time = np.where(alive, tc_time, np.inf)
        x, lab = _closure_labels(tc_time, tc_hq, W)
        x = np.where(alive, x, np.inf)
        S_new = alive & (x > T)
        if np.array_equal(S_new, S) or _TEST_MUTATION == "no_fixed_point":
            break
        S = S_new
    else:
        return abort()
    if not np.all(np.isfinite(x[alive])):
        return abort()
    # no QC can form: count, per receiver, the votes that ever arrive (a replica votes when it is
    # ready, unless it timed out first; Byzantine votes only reach vote_targets)
    voters = alive & np.isfinite(vt)
    if pv.silent_voters:
        voters[[k for k in pv.silent_voters if byz[k]]] = False
    voters &= (vt <= T) if _TEST_MUTATION == "no_late_votes" else ((vt <= T) | ~S)
    reach = np.tile(voters[:, None], (1, n))
    if byz.any() and pv.vote_targets is not None:
        reach[np.ix_(byz, ~pv.vote_targets)] = False
    if cfg.protocol == "P1":
        reach[:, np.arange(n) != L2] = False         # P1: direct votes only reach the collector
    if cfg.timeout_votes:
        # votes carried by timeouts reach everybody: senders that voted before timing out
        tv = S & alive & np.isfinite(vt) & (vt <= T)
        if pv.silent_voters:
            tv[[k for k in pv.silent_voters if byz[k]]] = False
        if pv.tmo_vote_omit:
            tv &= ~byz
        reach |= tv[:, None]
        if reach.sum(axis=0)[alive].max(initial=0) >= q:
            return abort()
    if cfg.protocol == "P2":
        if reach.sum(axis=0)[alive].max(initial=0) >= q:
            return abort()
    else:
        if reach[:, L2].sum() >= q and st.alive[L2] and not (byz[L2] and pv.collector_withhold):
            return abort()

    # commit the view
    if sent:
        st.prop_parent[v], st.prop_time[v] = parent, entry[L]
    st.know[v] = x
    st.cert_type[v, alive] = TC
    st.cert_hq[v, alive] = lab[alive]
    st.tc_exists[v] = True
    st.qc_exists[v] = False
    # AT: a timeout sender reports NR=1 iff it had not received the proposal by its timeout
    # (a <= T means received: deliveries precede timeouts at equal times); Byzantine may lie
    got = np.maximum(a, st.payload_time[v]) if (cfg.nr_requires_data and sent) else a
    nr = S & ((got >= T) if _TEST_MUTATION == "nr_tie" else (got > T))
    if pv.nr_claim is not None and _TEST_MUTATION != "nr_no_lie":
        nr = np.where(S & byz, bool(pv.nr_claim), nr)
    st.nr_count[v] = int(nr.sum())
    # QC knowledge from TC highQCs. A replica holds highQC h at the earliest of: forming its own TC
    # with highQC h; learning its first certificate, if labelled h (the diagonal of Df is 0, so this
    # is included in the forward term); a forward of a certificate labelled h; the proposal of v+1
    # if the next leader's certificate is labelled h.
    Df = net.delays(v + 1, "fwd")
    for h in np.unique(np.concatenate([tc_hq[alive], lab[alive]])):
        t_h = np.where(tc_hq == h, tc_time, np.inf)
        t_h = np.minimum(t_h, np.where(lab == h, x, np.inf))
        senders = alive & (lab == h)
        if cfg.forward and senders.any():
            t_h = np.minimum(t_h, (x[senders][:, None] + Df[senders]).min(axis=0))
        if p2 is not None and lab[L2] == h:
            t_h = np.minimum(t_h, x[L2] + p2)
        st.hold_vec(v, int(h), alive_idx, t_h[alive_idx])
    if p2 is not None:
        just = held_qc(st.qc_know, L2, x[L2], v)
        rcv = np.flatnonzero(alive & np.isfinite(p2))
        st.hold_vec(v, just, rcv, x[L2] + p2[rcv])
    return True


def run(cfg: RunConfig, net) -> Result:
    check_sizes(cfg, net)
    if cfg.timeout_votes or cfg.track_signed or cfg.vote_weights is not None:
        # With vote-carrying timeouts, whether a replica times out in view v (and so contributes its
        # vote to a QC reconstructed from timeouts) can depend on later views, which breaks the
        # per-view decomposition used below. Use the reference engine, which is exact by definition.
        return engine_event.run(cfg, net)
    st = State(cfg)
    V = cfg.views
    alive = st.alive
    v = 1
    while v <= V:
        if not _kernel(cfg, net, st, v):
            if cfg_tc_kernel(cfg) and _tc_kernel(cfg, net, st, v):
                st.tc_kernel_views += 1
            else:
                st.fallback_views += 1
                engine_event.simulate(cfg, net, st, v, v)
        bad = alive & (st.know[v] < st.know[v - 1])
        if bad.any():
            s, e = max(1, v - WINDOW_BACK), min(V, v + WINDOW_AHEAD)
            while True:
                st.undo_from(s)
                engine_event.simulate(cfg, net, st, s, e)
                later = st.know[s:e + 1][:, alive].min(axis=0)
                if s == 1 or np.all(later >= st.know[s - 1, alive]):
                    break
                s = max(1, s - WINDOW_BACK)
            st.window_views += e - s + 1
            v = e + 1
            continue
        v += 1
    return Result.from_state(st)

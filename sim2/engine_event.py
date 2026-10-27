"""THE protocol rules: discrete-event simulation with per-replica state machines.

This file is the single definition of protocol behaviour. engine_fast.py only adds closed-form
shortcuts for views that need no timeout, and calls simulate() for every other view.

Protocols (both Jolteon-style two-chain HotStuff with a pacemaker satisfying PM):
  P2  votes are broadcast; every replica forms QC(v) itself.
  P1  votes are sent to the leader of v+1 only (the collector), which forms QC(v), enters v+1 and
      proposes; others learn QC(v) from that proposal or from certificate forwards.

Replica k keeps h_k, the highest view whose certificate (QC or TC) it knows; it is in view h_k+1.
* On learning a certificate c > h_k (own QC/TC, forwarded certificate, or a proposal of view c+1,
  which carries cert(c)): set h_k = c, forward cert(c) to all (type "fwd", delay key c+1), arm a
  timeout at now + tau for view c+1, and, if k leads c+1, send the proposal of c+1 (type "prop",
  key c+1) and vote for it.
* The proposal of v extends the highest QC its leader holds when it enters v (justify QC); it
  carries cert(v-1) (with its highQC if a TC) and the justify QC; receivers hold both QCs.
* On receiving the proposal of v: learn cert(v-1); vote for v (type "vote", key v) unless k already
  voted or timed out in v. Votes for views k has already left are allowed (harmless for safety, but
  they break accountable safety: a late vote after a later timeout with a lower hq is evidence E3);
  cfg.vote_monotone forbids voting in v once k signed anything for a view >= v (rule R3).
* 2f+1 distinct votes of v at a receiver form QC(v) there (P1: only at the collector).
* A timeout for v fires only if k is still in v; k then broadcasts a timeout (type "tmo", key v)
  carrying its highQC and the AT bit NR ("no proposal of v signed by its leader received yet";
  a leader that sent its proposal counts it as received), and never votes in v afterwards.
  2f+1 distinct timeouts form TC(v), whose highQC is the max of those timeouts' highQCs.
  With cfg.timeout_votes (direction A), a timeout also carries the sender's vote of v if it voted
  (Byzantine senders may omit it); such votes count like direct votes, so a QC withheld by a P1
  collector can be reconstructed from 2f+1 timeouts (st.qc_via_tmo[v] records this).
  st.nr_count[v] counts distinct timeout senders with NR=1; 2f+1 of them form an AT accusation.
  Direction A v0.2: st.tmo_votes[v] = number of distinct senders of a vote-carrying timeout of v
  (the third-party-verifiable rec_tau(v) := tmo_votes[v] >= tau); a carried vote is counted before
  the TC that the same timeout may complete; with cfg.tmo_after_leave, a replica that voted in v
  and leaves v (or votes after leaving it) without holding QC(v) still broadcasts its timeout of v.
* Ties at equal times: message deliveries before timeouts, then insertion order.
* Natural failures: with probability rho_nat (cfg.glitch(v)) the leader of v sends no proposal.
* Roles: crashed replicas send nothing; Byzantine replicas follow the protocol except where the
  adversary's ViewPlan says otherwise (proposal recipients and extra delays as leader, withheld
  votes, P1 collector ignoring votes).

simulate(cfg, net, st, start, end) solves views start..end in place on a common.State: rows
start..end are reset, every alive replica enters `start` at st.know[start-1], and writes to QC
knowledge of rows < start are logged in st.qc_log (tag = start) so callers can undo them.
Messages of views before `start` still in flight are not replayed.
"""
import heapq

import numpy as np

from .common import QC, TC, Result, RunConfig, State, check_sizes, held_qc, proposal_timing, weighted_hit

PRIO_MSG, PRIO_TIMEOUT = 0, 1


def simulate(cfg: RunConfig, net, st: State, start: int, end: int) -> None:
    n, q, tau = cfg.n, cfg.quorum, cfg.tau_ms
    p1 = cfg.protocol == "P1"
    V = cfg.views
    alive_idx = [int(k) for k in np.flatnonzero(st.alive)]
    alive = st.alive
    byz = st.byz
    st.reset_rows(start, end)
    know, ctype, chq = st.know, st.cert_type, st.cert_hq

    h = [start - 1] * n
    got_prop = [set() for _ in range(n)]  # views whose proposal k has received (or sent)
    voted = [set() for _ in range(n)]
    timed_out = [set() for _ in range(n)]
    vset = [dict() for _ in range(n)]     # vset[j][w] = senders whose vote j received
    tset = [dict() for _ in range(n)]     # tset[j][w] = list of (sender, hq) in arrival order
    tmo_senders = {}                      # w -> senders of a vote-carrying timeout of w
    leave_rule = cfg.timeout_votes and cfg.tmo_after_leave
    weighted = cfg.vote_weights is not None
    if weighted and cfg.timeout_votes:
        raise ValueError("weighted voting is not combined with vote-carrying timeouts")
    wcache = {}

    def share(v):
        a = wcache.get(v)
        if a is None:
            a = np.asarray(cfg.vote_weights(st, v), float)
            wcache[v] = a
        return a

    vw = [dict() for _ in range(n)]       # vw[k][w] = share of the votes of w that k holds
    tw = [dict() for _ in range(n)]       # tw[k][w] = share of the timeouts of w that k holds
    qc_done = [set() for _ in range(n)]
    tc_done = [set() for _ in range(n)]
    track = cfg.track_signed
    honest = st.honest
    heap = []
    counter = [0]

    def push(t, prio, ev):
        counter[0] += 1
        heapq.heappush(heap, (t, prio, counter[0], ev))

    def hold(k, u, t):
        st.hold(start, u, k, t)

    ready_at = {}                         # (w, k) -> time k is ready to vote in w, when later than its header
    ell = [-1] * n                        # highest view k has signed a vote or timeout for (cfg.vote_monotone)

    def cast_vote(k, w, t):
        voted[k].add(w)
        ell[k] = max(ell[k], w)
        if track:
            st.sig_votes.append((k, w, int(st.prop_parent[w])))
            st.sig_order.append(("vote", k, w))
        if byz[k] and h[k] == w - 1 and w not in timed_out[k] and k in st.plan(w).tmo_after_vote:
            send_tmo(k, w, t)                     # greedy liar: vote, then a timeout with its NR claim
        if leave_rule and h[k] >= w and w not in timed_out[k] and st.qc_know[w, k] > t:
            send_tmo(k, w, t)                     # voted after leaving w without QC(w): carry it anyway
            st.leave_tmo_sent += 1
        D = net.delays(w, "vote")
        tg = st.plan(w).vote_targets if byz[k] else None
        pad = st.plan(w).vote_pad_to if byz.any() else None
        if pad is not None:
            D = D.copy()
            D[:, pad] = np.maximum(D[:, pad], net.delta_max())
        if p1:
            c = st.leader(w + 1)
            if alive[c] and (tg is None or tg[c]):
                push(t + D[k, c], PRIO_MSG, ("vote", c, w, k, None))
        else:
            for j in alive_idx:
                if tg is None or tg[j]:
                    push(t + D[k, j], PRIO_MSG, ("vote", j, w, k, None))

    def count_vote(k, w, sender, t, via_tmo):
        """A vote of `sender` for view w reaches k, directly or carried by a timeout (direction A)."""
        if p1 and byz[k] and st.plan(w).collector_withhold:
            return
        if track and honest[k]:
            st.vote_seen[w, sender] = True        # an honest replica holds sender's signed vote of w
            if via_tmo:
                st.vote_carried[w, sender] = True
            elif t < know[w - 1, k] + tau:
                st.vote_timely[w, sender] = True  # receipt before k's own timer of w: counts for presence
        if byz[k] and sender in st.plan(w).qc_exclude:
            return                                # Byzantine assembler leaves this signer out of its QC
        s = vset[k].setdefault(w, set())
        if sender in s:
            return
        s.add(sender)
        if weighted:
            vw[k][w] = vw[k].get(w, 0.0) + share(w)[sender]
            hit = w not in qc_done[k] and weighted_hit(vw[k][w])
            if hit:
                qc_done[k].add(w)
        else:
            hit = len(s) == q
        if hit:
            if track and byz[k]:
                st.qc_pub[w, list(s)] = True      # the QC it forms is published with its next proposal
            st.qc_exists[w] = True
            if via_tmo:
                st.qc_via_tmo[w] = True
            learn(k, w, QC, w, t)

    def send_tmo(k, w, t):
        """k broadcasts its timeout of w (on its own timeout, or under the direction-A leave rule)."""
        timed_out[k].add(w)
        if cfg.nr_requires_data:
            nr = not (w in got_prop[k] and st.payload_time[w, k] <= t)
        else:
            nr = w not in got_prop[k]
        if w in voted[k]:
            nr = False                            # NR is derived from local state: a voter has a usable proposal
        pw = st.plan(w) if byz[k] else None
        if pw is not None and pw.nr_claim is not None:
            nr = bool(pw.nr_claim)
        if nr:
            st.nr_count[w] += 1
            if weighted:
                st.nr_w[w] += share(w)[k]
            if track:
                st.nr1[w, k] = True
        hq = held_qc(st.qc_know, k, t, w - 1)
        ell[k] = max(ell[k], w)
        if track:
            st.sig_tmos.append((k, w, int(hq)))
            st.sig_order.append(("tmo", k, w))
        carries = cfg.timeout_votes and w in voted[k] and not (pw is not None and pw.tmo_vote_omit)
        if carries:
            tmo_senders.setdefault(w, set()).add(k)
            st.tmo_votes[w] = len(tmo_senders[w])
        D = net.delays(w, "tmo")
        extra = pw.tmo_extra_ms if pw is not None else None
        for j in alive_idx:
            push(t + D[k, j] + (0.0 if extra is None else extra[j]), PRIO_MSG, ("tmo", j, w, k, (hq, carries)))

    def may_vote(k, w):
        if cfg.timeout_votes and cfg.tc_wait_ms and h[k] >= w:
            return False                          # v0.4 (as Jolteon): vote only while still in w
        if cfg.vote_monotone and w <= ell[k]:
            return False                          # R3: signed views are monotone (no late votes after a later timeout)
        return w <= end and w not in voted[k] and w not in timed_out[k] and not silent(k, w)

    def silent(k, w):
        return byz[k] and k in st.plan(w).silent_voters

    def propose(k, w, t):
        if cfg.glitch(w):
            return                                # natural failure: no proposal
        if byz[k]:
            p = st.plan(w)
            if p.prop_targets is not None and not p.prop_targets.any():
                return                            # silent leader: no proposal at all
        parent = held_qc(st.qc_know, k, t, w - 1)
        st.prop_parent[w] = parent
        st.prop_time[w] = t
        got_prop[k].add(w)
        extra = (ctype[w - 1, k], chq[w - 1, k], parent)
        a, vt = proposal_timing(cfg, net, st, w, k, t, parent)
        late = st.plan(w).prop_before_timeout_ms if byz[k] else None
        if late is not None and cfg.prop_forward:
            # the re-timing below would also move the copies forwarded by honest replicas (review v0.8
            # code C5); timed release under forwarding is adversary.TimedRelease (prop_extra_ms)
            raise NotImplementedError("prop_before_timeout_ms with prop_forward")
        for j in alive_idx:
            if j == k or not np.isfinite(a[j]):
                continue
            if late is not None:
                push(a[j], PRIO_MSG, ("prop_late", j, w, k, (extra, late, vt[j] - a[j], a[j])))
                continue
            push(a[j], PRIO_MSG, ("prop", j, w, k, extra))
            if vt[j] > a[j]:
                ready_at[(w, j)] = vt[j]
                push(vt[j], PRIO_MSG, ("ready", j, w, k, None))
        if vt[k] > t:
            ready_at[(w, k)] = vt[k]
            push(vt[k], PRIO_MSG, ("ready", k, w, k, None))
        elif w <= end and not silent(k, w) and w not in timed_out[k]:
            cast_vote(k, w, t)

    def enter(k, w, t):
        """k enters view w (just learned cert(w-1))."""
        if w > end + 1:
            return
        if w <= end:
            early = st.plan(w).tmo_early_ms if byz[k] else None
            push(t + (tau if early is None else min(tau, early)), PRIO_TIMEOUT, ("timeout", k, w, k, None))
        if st.leader(w) == k:
            if (cfg.timeout_votes and cfg.tc_wait_ms and not byz[k] and w - 1 >= start
                    and ctype[w - 1, k] == TC and st.qc_know[w - 1, k] > t):
                push(t + cfg.tc_wait_ms, PRIO_MSG, ("propose", k, w, k, None))   # wait for votes of w-1
            else:
                propose(k, w, t)

    def learn(k, c, typ, hq, t):
        if c > end or c < start - 1:
            return
        if know[c, k] == np.inf:
            know[c, k] = t
            ctype[c, k] = typ
            chq[c, k] = hq
        hold(k, c if typ == QC else hq, t)
        if c > h[k]:
            w0 = h[k] + 1                         # the view k is leaving
            h[k] = c
            if (leave_rule and start <= w0 <= end and w0 in voted[k] and w0 not in timed_out[k]
                    and st.qc_know[w0, k] > t):
                send_tmo(k, w0, t)                # left w0 without QC(w0): still broadcast the carried vote
                st.leave_tmo_sent += 1
            if cfg.forward:
                D = net.delays(c + 1, "fwd")
                for j in alive_idx:
                    if j != k:
                        push(t + D[k, j], PRIO_MSG, ("cert", j, c + 1, k, (typ, hq)))
            enter(k, c + 1, t)

    for k in alive_idx:
        enter(k, start, float(know[start - 1, k]))

    while heap:
        t, _, _, ev = heapq.heappop(heap)
        kind, k, w, sender, extra = ev
        if kind == "prop":
            got_prop[k].add(w)
            hold(k, extra[2], t)                  # justify QC carried by the proposal
            learn(k, w - 1, extra[0], extra[1], t)
            if (w, k) not in ready_at and may_vote(k, w):
                cast_vote(k, w, t)
        elif kind == "propose":                   # direction A v0.4: delayed proposal after a TC
            if h[k] == w - 1 and w not in timed_out[k]:
                propose(k, w, t)                  # a replica that timed out in w neither proposes nor votes
        elif kind == "prop_late":                 # late-proposal attack: hold until just before k's timer
            ex, x, dv, a0 = extra
            if h[k] < w - 1:
                if t < a0 + 4 * tau:
                    push(t + 5.0, PRIO_MSG, ev)              # k has not entered w yet: look again
            else:
                tt = max(t, float(know[w - 1, k]) + tau - x)
                push(tt, PRIO_MSG, ("prop", k, w, sender, ex))
                if dv > 0:
                    ready_at[(w, k)] = tt + dv
                    push(tt + dv, PRIO_MSG, ("ready", k, w, sender, None))
        elif kind == "ready":                     # block data (and parent data) now available
            if may_vote(k, w):
                cast_vote(k, w, t)
        elif kind == "vote":
            count_vote(k, w, sender, t, via_tmo=False)
        elif kind == "timeout":
            if h[k] == w - 1 and w not in timed_out[k]:
                send_tmo(k, w, t)                 # one timeout per view (a greedy liar may have sent it already)
        elif kind == "tmo":
            hq, carries = extra
            lst = tset[k].setdefault(w, [])
            if any(s == sender for s, _ in lst):
                continue
            lst.append((sender, hq))
            if carries:
                # count the carried vote BEFORE the TC: if the q-th timeout completes both, the replica
                # holds QC(w) when it enters w+1 (an honest collector then extends block w)
                count_vote(k, w, sender, t, via_tmo=True)
            if weighted:
                tw[k][w] = tw[k].get(w, 0.0) + share(w)[sender]
                hit = w not in tc_done[k] and weighted_hit(tw[k][w])
                if hit:
                    tc_done[k].add(w)
            else:
                hit = len(lst) == q
            if hit:
                st.tc_exists[w] = True
                learn(k, w, TC, max(h_ for _, h_ in lst), t)
        elif kind == "cert":
            # forward sent on entering view w carries cert(w-1)
            learn(k, w - 1, extra[0], extra[1], t)


def run(cfg: RunConfig, net) -> Result:
    """Global reference run over all views."""
    check_sizes(cfg, net)
    st = State(cfg)
    simulate(cfg, net, st, 1, cfg.views)
    return Result.from_state(st)

"""Bounded explicit-state model checker for the epoch handover of Trust 2.0 (two weight tables), built on the
single-table model of formal/mc_jolteon.py. Abstract model only; nothing contacts a real system.

What it is for (review S16): the single-table theorem compares two certificates counted under ONE weight table. At a
handover a block of the old epoch after the terminal block (a suffix block) is certified under the old table W1 and a
block of the new epoch under the new table W2, by honest nodes that are in different epochs. This model checks whether
the handover rules keep the ledger safe and every fork accountable, without and with the fix:

  H5   a certificate (QC or TC) of the old epoch for a view past the end of that epoch counts only if its signers hold
       more than 2/3 of BOTH tables, the old and the next one.
  V3   a block embeds a TC of its own epoch, or of its parent's epoch (the first block of an epoch).
  E3'  E3 with a timeout of the same epoch as the vote or of a later one.
  E4   a vote of a later epoch at a view not above a message (vote or timeout) the same signer signed in an earlier
       epoch.

Model (differences from mc_jolteon.py)
* Two epochs. The genesis block G (view 0) is the terminal block of epoch 1 and its QC is known, so every other block
  of epoch 1 is a suffix block and every view from 1 on is past the end of epoch 1. Epoch 2 does not end within the
  bound. Block = (v, parent, tc, epoch); tc = (m, qcb, tc_epoch). A block of epoch 1 has a parent of epoch 1 (H2 holds
  for every block of epoch 2: G is the only terminal block).
* Weights are integers, one tuple per table; a quorum of a table holds more than 2/3 of it.
* An honest node is in epoch 1 until it holds a commit proof of G: two blocks of epoch 1 at adjacent views, parent and
  child, both certified (H3). Entering is part of learning, before a signature: the node then knows the QC of the
  child. In epoch 1 it learns QCs of epoch 1 only; it signs only messages of its epoch.
* A node signs one timeout per view and epoch: one that timed out in a view and then enters epoch 2 in the same view
  may time out again there, as the prototype does (the old timeout does not count towards a TC of the new epoch).
* Signed views are monotone (R3): a vote is for a view above every view the node has signed, and not above the
  view the node is in. --votes current allows a vote in the node's current view only, as the prototype does (a
  subset of the behaviours; forks found with it need no late vote).
* A TC that moves a node into a view is one of its epoch, or one that a block of its epoch may embed.

Checks, on every reachable state
* no honest node holds evidence: E1, E3', E4 (--e4 vote, the definition above; --e4 s16, the first draft: any old
  message above a new one, or at the same view unless it is an old vote and a new timeout).
* for every two conflicting direct commits (ledger blocks or suffix blocks: lemma B of S16) and every choice of signer
  sets, the case analysis applies and its culprit set holds more than 1/3 of W2 and no honest node; a culprit set at
  or below 1/3 of W2 is the finding "light_culprit_set". Two conflicting committed blocks of epoch 2 are a fork of the
  ledger ("ledger_fork", reported when --stop-on names it; with Byzantine below 1/3 of both tables it is a safety
  violation).

Variants: --h5 none|suffix|full (suffix: the first draft, QCs of suffix blocks and TCs embedded in suffix blocks
only), --tc-epoch any|chain (any: a block may embed a TC of either epoch, as the prototype before the fix).

Run from the repository root:
  python formal/mc_handover.py --witness
  python formal/mc_handover.py --w1 37,33,30 --w2 33,37,30 --byz 2 --views 5 --h5 full --tc-epoch chain
"""
import argparse
import itertools
import resource
import sys
import time
from array import array
from collections import Counter, deque

G = (0, None, None, 1)                        # (view, parent, tc, epoch): terminal block of epoch 1


def view(b):
    return b[0]


def parent(b):
    return b[1]


def epoch(b):
    return b[3]


def is_ancestor(a, b):
    while b is not None:
        if b == a:
            return True
        b = parent(b)
    return False


def fmt_block(b):
    if b == G:
        return "G"
    tc = "" if b[2] is None else f",TC{b[2][2]}(m={b[2][0]})"
    name = "S" if epoch(b) == 1 else "N"
    return f"{name}{view(b)}<{fmt_block(parent(b))}{tc}>"


class Model:
    def __init__(self, w1, w2, byz, views, h5="full", tc_epoch="chain", e4="vote", late_votes=True,
                 symmetry=True):
        assert len(w1) == len(w2)
        self.w = {1: tuple(w1), 2: tuple(w2)}
        self.n = len(w1)
        self.byz = frozenset(byz)
        self.hon = tuple(i for i in range(self.n) if i not in self.byz)
        self.V, self.h5, self.tc_epoch, self.e4, self.late = views, h5, tc_epoch, e4, late_votes
        self.blk, self.bid = [G], {G: 0}
        a = self.hon
        self.sym = symmetry and len(a) == 2 and all(self.w[t][a[0]] == self.w[t][a[1]] for t in (1, 2))

    # ---- encoding ---------------------------------------------------------------------------
    def intern(self, b):
        i = self.bid.get(b)
        if i is None:
            i = self.bid[b] = len(self.blk)
            self.blk.append(b)
        return i

    def canon(self, st):
        if not self.sym:
            return st
        hs, votes, tmos = st
        a, b = self.hon
        sw = {a: b, b: a}
        st2 = ((hs[1], hs[0]), tuple(sorted((sw[k], x) for (k, x) in votes)),
               tuple(sorted((sw[t[0]],) + t[1:] for t in tmos)))
        return min(st, st2)

    # ---- weights and certificates -------------------------------------------------------------
    def weight(self, s, table):
        return sum(self.w[table][i] for i in s)

    def quorum(self, s, tables):
        return all(3 * self.weight(s, t) > 2 * sum(self.w[t]) for t in tables)

    def more_than_third(self, s, table):
        return 3 * self.weight(s, table) > sum(self.w[table])

    def qc_tables(self, b):
        """The tables a QC of block b is counted under. Every block of epoch 1 but G is a suffix block."""
        if epoch(b) == 1 and self.h5 != "none":
            return (1, 2)
        return (epoch(b),)

    def tc_tables(self, tce, ctx):
        """The tables a TC of epoch tce is counted under; ctx is the epoch of the block that embeds it (or of the
        node it moves). Every view of the model is past the end of epoch 1."""
        if tce == 1 and (self.h5 == "full" or (self.h5 == "suffix" and ctx == 1)):
            return (1, 2)
        return (tce,)

    def tc_epochs(self, block_epoch, parent_epoch):
        """V3: the epochs of a TC that a block may embed."""
        if self.tc_epoch == "any":
            return (1, 2)
        return tuple(range(parent_epoch, block_epoch + 1))

    def voters(self, st, i):
        return frozenset(k for (k, x) in st[1] if x == i)

    def qc_ok(self, st, i):
        return i == 0 or self.quorum(self.voters(st, i) | self.byz, self.qc_tables(self.blk[i]))

    def qc_ids(self, st):
        return [i for i in {x for (_, x) in st[1]} | {0} if self.qc_ok(st, i)]

    def low(self, st, v, tce, m):
        return frozenset(k for (k, vv, hk, te) in st[2] if vv == v and te == tce and hk <= m)

    def tc_ok(self, st, v, tce, m, ctx):
        """TC(v) of epoch tce whose largest reported hq is m."""
        if not 0 <= m < v:
            return False
        return self.quorum(self.low(st, v, tce, m) | self.byz, self.tc_tables(tce, ctx))

    def constructible(self, st, v, qcs):
        """Valid blocks of view v buildable from formable certificates (V1-V3), as interned ids."""
        out = []
        for p in qcs:
            pb = self.blk[p]
            j = view(pb)
            if j >= v:
                continue
            for eb in range(epoch(pb), 3):
                if j == v - 1:
                    out.append(self.intern((v, pb, None, eb)))
                    continue
                for tce in self.tc_epochs(eb, epoch(pb)):
                    for q in qcs:
                        qb = self.blk[q]
                        if view(qb) <= j and self.tc_ok(st, v - 1, tce, view(qb), eb):
                            out.append(self.intern((v, pb, (view(qb), qb, tce), eb)))
        return out

    # ---- transitions ------------------------------------------------------------------------
    def initial(self):
        return (tuple((0, 0, 0, 0, 1) for _ in self.hon), (), ())

    def learn(self, st, h, hq, ep, qcs):
        """What a node of epoch ep may know before it signs: (h1, hq1)."""
        opts = set()
        hqv = view(self.blk[hq])
        tces = (1, 2) if self.tc_epoch == "any" else tuple(range(1, ep + 1))
        for hq1 in [hq] + [q for q in qcs if view(self.blk[q]) > hqv and epoch(self.blk[q]) <= ep]:
            v1 = view(self.blk[hq1])
            base = max(h, v1)
            opts.add((base, hq1))
            for t in range(base + 1, self.V + 1):
                # a TC received on its own is not embedded in a suffix block: ctx 0 (matters for --h5 suffix only)
                if any(self.tc_ok(st, t, tce, view(self.blk[q]), 0) and view(self.blk[q]) <= v1
                       for q in qcs for tce in tces):
                    opts.add((t, hq1))
        return opts

    def proofs(self, qcs):
        """The children X+ of the commit proofs of G a node of epoch 1 can hold: both blocks of epoch 1."""
        ids = set(qcs)
        out = []
        for c in qcs:
            cb = self.blk[c]
            if c and epoch(cb) == 1 and self.bid[parent(cb)] in ids and view(cb) == view(parent(cb)) + 1:
                out.append(c)
        return out

    def learn_options(self, st, h, hq, ep, qcs, proofs):
        opts = {(h1, hq1, ep) for (h1, hq1) in self.learn(st, h, hq, ep, qcs)}
        if ep == 1:
            for c in proofs:                   # H3: enter epoch 2 on a commit proof of G, knowing the QC of X+
                cv = view(self.blk[c])
                hq0 = c if cv > view(self.blk[hq]) else hq
                opts |= {(h1, hq1, 2) for (h1, hq1) in self.learn(st, max(h, cv), hq0, 2, qcs)}
        return opts

    def successors(self, st):
        hs, votes, tmos = st
        qcs = self.qc_ids(st)
        proofs = self.proofs(qcs)
        cons = {}
        for idx, k in enumerate(self.hon):
            h, hq, ell, lt, ep = hs[idx]
            for (h1, hq1, ep1) in self.learn_options(st, h, hq, ep, qcs, proofs):
                v = h1 + 1
                if v <= self.V and lt != v * 3 + ep1:
                    hk = view(self.blk[hq1])
                    ns = (h1, hq1, max(ell, v), v * 3 + ep1, ep1)
                    yield ("timeout", k, v, hk, ep1), (hs[:idx] + (ns,) + hs[idx + 1:], votes,
                                                        tuple(sorted(tmos + ((k, v, hk, ep1),))))
                for bv in range(ell + 1 if self.late else max(ell, h1) + 1, min(h1 + 1, self.V) + 1):
                    if bv not in cons:
                        cons[bv] = self.constructible(st, bv, qcs)
                    for b in cons[bv]:
                        bb = self.blk[b]
                        if epoch(bb) != ep1:
                            continue
                        nhq = max(hq1, self.bid[parent(bb)], key=lambda i: view(self.blk[i]))
                        if bb[2] is not None:
                            nhq = max(nhq, self.bid[bb[2][1]], key=lambda i: view(self.blk[i]))
                        ns = (max(h1, bv - 1), nhq, bv, lt, ep1)
                        yield ("vote", k, b, ep1), (hs[:idx] + (ns,) + hs[idx + 1:],
                                                     tuple(sorted(votes + ((k, b),))), tmos)

    # ---- checks -------------------------------------------------------------------------------
    def honest_evidence(self, st):
        """Evidence an honest node holds against itself: (kind, node, detail)."""
        bad = []
        for k in self.hon:
            vs = [self.blk[x] for (kk, x) in st[1] if kk == k]
            ts = [t[1:] for t in st[2] if t[0] == k]
            for b1, b2 in itertools.combinations(vs, 2):
                if view(b1) == view(b2) and epoch(b1) == epoch(b2):
                    bad.append(("honest_e1", k, (fmt_block(b1), fmt_block(b2))))
            for b in vs:
                for (tv, hk, te) in ts:
                    if te >= epoch(b) and tv >= view(b) and hk < view(parent(b)):
                        bad.append(("honest_e3", k, (fmt_block(b), tv, hk, te)))
            old = [("vote", view(b)) for b in vs if epoch(b) == 1] + [("timeout", tv) for (tv, _, te) in ts if te == 1]
            new = [("vote", view(b)) for b in vs if epoch(b) == 2] + [("timeout", tv) for (tv, _, te) in ts if te == 2]
            for (ok, ov) in old:
                for (nk, nv) in new:
                    if self.e4 == "vote":
                        hit = nk == "vote" and ov >= nv
                    else:
                        hit = ov > nv or (ov == nv and not (ok == "vote" and nk == "timeout"))
                    if hit:
                        bad.append(("honest_e4", k, (ok, ov, nk, nv)))
        return bad

    def quorums(self, avail, tables):
        avail = sorted(avail)
        for r in range(1, len(avail) + 1):
            for s in itertools.combinations(avail, r):
                if self.quorum(s, tables):
                    yield frozenset(s)

    def qc_quorums(self, st, b):
        return list(self.quorums(self.voters(st, self.bid[b]) | self.byz, self.qc_tables(b)))

    def commits(self, st):
        qcs = set(self.qc_ids(st))
        out = []
        for c in qcs:
            cb = self.blk[c]
            if c != 0:
                p = self.bid[parent(cb)]
                if p in qcs and view(cb) == view(parent(cb)) + 1:
                    out.append((p, c))
        return out

    def judge(self, st, cpx, cpy):
        """Case analysis of lemma B for commit proofs cpx = (X, X+), cpy = (Y, Y+) (ids), view(X) <= view(Y).
        Yields (case, evidence kind, C) for every choice of signer sets; ("structure", why, None) if a claim of the
        proof about the shape of the branch does not hold."""
        X, Xp = self.blk[cpx[0]], self.blk[cpx[1]]
        Y = self.blk[cpy[0]]
        u = view(X)

        def votes_of(case, b1, b2):
            kind = "E1" if epoch(b1) == epoch(b2) else "E4"
            for q1 in self.qc_quorums(st, b1):
                for q2 in self.qc_quorums(st, b2):
                    yield case, kind, q1 & q2

        if view(Y) == u:
            yield from votes_of("A", X, Y)
            return
        if view(Y) == u + 1:
            yield from votes_of("B", Xp, Y)
            return
        z = Y                                  # the ancestor of Y with the smallest view above u+1
        while view(parent(z)) > u + 1:
            z = parent(z)
        p, j, w = parent(z), view(parent(z)), view(z)
        if j == u + 1:
            if p == Xp:
                yield "structure", "P = X+", None
                return
            yield from votes_of("C1", Xp, p)
        elif j == u:
            if p == X:
                yield "structure", "P = X", None
                return
            yield from votes_of("C2", X, p)
        else:
            if z[2] is None or z[2][0] > j:
                yield "structure", "Z embeds no TC that justifies it", None
                return
            m, _, tce = z[2]
            kind = "E3" if tce == epoch(Xp) else "E3'" if tce > epoch(Xp) else "E4"
            for q2 in self.qc_quorums(st, Xp):
                for t in self.quorums(self.low(st, w - 1, tce, m) | self.byz, self.tc_tables(tce, epoch(z))):
                    yield "C3", kind, q2 & t

    def check_forks(self, st, stats):
        bad, forks = [], 0
        cps = self.commits(st)
        for (cx, cy) in itertools.combinations(cps, 2):
            X, Y = self.blk[cx[0]], self.blk[cy[0]]
            if is_ancestor(X, Y) or is_ancestor(Y, X):
                continue
            forks += 1
            ledger = epoch(X) == 2 and epoch(Y) == 2
            if ledger:
                bad.append(("ledger_fork", None, cx, cy, ()))
            if view(X) > view(Y):
                cx, cy = cy, cx
            seen = set()
            for case, kind, c in self.judge(st, cx, cy):
                if case == "structure":
                    bad.append(("structure", kind, cx, cy, ()))
                    continue
                seen.add((case, kind))
                if not self.more_than_third(c, 2):
                    bad.append(("light_culprit_set", case, cx, cy, tuple(sorted(c))))
                if c - self.byz:
                    bad.append(("honest_blamed", case, cx, cy, tuple(sorted(c - self.byz))))
            for case, kind in seen:
                stats[f"forks_{case}_{kind}"] += 1
            if ledger:
                stats["ledger_fork_pairs"] += 1
        if forks:
            stats["fork_states"] += 1
        return bad


def explore(model, max_states, stop_on=(), mem_gb=None, report=()):
    s0 = model.canon(model.initial())
    seen = {s0: 0}
    order = [s0]
    par = array("l", [-1])
    depth = array("h", [0])
    q = deque([0])
    dcur = 0
    stats = Counter()
    found = {}
    t0 = time.time()
    while q:
        si = q.popleft()
        st = order[si]
        dcur = depth[si]
        for x in model.honest_evidence(st):
            found.setdefault(x[0], (si, x))
        for x in model.check_forks(st, stats):
            if x[0] != "ledger_fork" or "ledger_fork" in report:
                found.setdefault(x[0], (si, x))
        if any(k in found for k in stop_on):
            break
        for _, ns in model.successors(st):
            ns = model.canon(ns)
            if ns not in seen:
                seen[ns] = len(order)
                order.append(ns)
                par.append(si)
                depth.append(dcur + 1)
                q.append(len(order) - 1)
        if len(order) >= max_states:
            stats["truncated"] = "max_states"
            break
        if si and si % 100_000 == 0:
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            rss_gb = rss / (1e9 if sys.platform == "darwin" else 1e6)
            if si % 1_000_000 == 0:
                print(f"  ... {si} expanded, {len(order)} seen, depth {dcur}, {rss_gb:.1f} GB, "
                      f"{time.time() - t0:.0f}s", flush=True)
            if mem_gb and rss_gb > mem_gb:
                stats["truncated"] = f"memory > {mem_gb} GB"
                break
    stats["states"] = len(order)
    stats["max_depth_seen"] = max(depth)
    stats["checked_all_within_steps"] = "all" if not q and "truncated" not in stats else max(dcur - 1, 0)
    stats["seconds"] = round(time.time() - t0, 1)
    return stats, found, order, par


def fmt_act(model, act, before=None):
    k = act[1]
    entered = ""
    if before is not None and before[model.hon.index(k)][4] == 1 and act[-1] == 2:
        entered = " (enters epoch 2 first)"
    if act[0] == "vote":
        return f"r{k} votes {fmt_block(model.blk[act[2]])} in epoch {act[3]}{entered}"
    return f"r{k} times out in view {act[2]} of epoch {act[4]} with hq {act[3]}{entered}"


def trace(model, order, par, si):
    path = []
    while si != -1:
        path.append(order[si])
        si = par[si]
    path.reverse()
    out = []
    perm = {k: k for k in model.hon}           # canonical label -> label in the reported execution
    for a, b in zip(path, path[1:]):
        for act, ns in model.successors(a):
            if model.canon(ns) == b:
                shown = (act[0], perm[act[1]]) + act[2:]
                hs = a[0]
                if model.sym and perm[model.hon[0]] != model.hon[0]:
                    hs = (hs[1], hs[0])
                out.append(fmt_act(model, shown, hs))
                if ns != b:
                    x, y = model.hon
                    perm = {x: perm[y], y: perm[x]}
                break
    return out


def replay(model, script):
    """Replay a scripted execution with the model's own transitions. script: ("vote", k, block) or
    ("timeout", k, view, hq view, epoch); learning (and entering epoch 2) before a step is chosen as needed.
    Returns the final state, or the index of the first step that is not enabled."""
    st = model.initial()
    for n, step in enumerate(script):
        nxt = None
        for act, ns in model.successors(st):
            if step[0] == "vote" and act[0] == "vote" and act[1] == step[1] and model.blk[act[2]] == step[2]:
                nxt = ns
            if step[0] == "timeout" and act[0] == "timeout" and act[1:] == step[1:]:
                nxt = ns
            if nxt is not None:
                break
        if nxt is None:
            return None, n
        st = nxt
    return st, len(script)


# The execution of review S16, with r0 = A (still in epoch 1 when the views split), r1 = R (already in epoch 2) and
# r2 = Z (Byzantine, below 1/3 of both tables). W1 = (37, 33, 30): A and Z are a quorum of W1; W2 = (33, 37, 30): R and
# Z are a quorum of W2.
S1 = (1, G, None, 1)
S2 = (2, S1, None, 1)
N2 = (2, S1, None, 2)
N3 = (3, N2, None, 2)
M4 = (4, S2, (2, S2, 2), 2)
M5 = (5, M4, None, 2)
WITNESS_SUFFIX = [
    ("vote", 0, S1), ("vote", 1, S1),          # the child of G is certified: G has a commit proof
    ("vote", 1, N2),                           # R enters epoch 2; with Z, N2 is certified under W2
    ("vote", 0, S2),                           # A, still in epoch 1, votes for a suffix block of the same view;
    #                                            with Z it is certified under W1
    ("vote", 1, N3),                           # N2 is committed (R, Z)
    ("timeout", 1, 3, 2, 2),                   # R times out in view 3 reporting the QC of view 2: TC(3) with Z
    ("vote", 0, M4), ("vote", 1, M4),          # a block of epoch 2 on the suffix block S2: its QC, of view 2, is as
    #                                            high as every QC the TC reports, so R votes for it too
    ("vote", 0, M5), ("vote", 1, M5),          # M4 is committed: it conflicts with N2
]
# The same fork through a TC of the old epoch embedded in a block of the new one: no suffix block of view 2 is needed.
O4 = (4, S1, (1, S1, 1), 2)
O5 = (5, O4, None, 2)
WITNESS_OLD_TC = [
    ("vote", 0, S1), ("vote", 1, S1),
    ("vote", 1, N2), ("vote", 1, N3),          # N2 is committed (R, Z)
    ("timeout", 0, 2, 1, 1),                   # A, still in epoch 1, times out in views 2 and 3 reporting view 1:
    ("timeout", 0, 3, 1, 1),                   # with Z, a TC(3) of epoch 1 under W1
    ("vote", 0, O4), ("vote", 1, O4),          # a block of epoch 2 on S1 justified by that TC: R votes for it too
    ("vote", 0, O5), ("vote", 1, O5),          # O4 is committed: it conflicts with N2
]


def check_witnesses():
    w1, w2, byz = (37, 33, 30), (33, 37, 30), [2]
    for name, script in (("suffix block", WITNESS_SUFFIX), ("old TC", WITNESS_OLD_TC)):
        for h5, tce in (("none", "any"), ("suffix", "any"), ("suffix", "chain"), ("full", "any"), ("full", "chain")):
            m = Model(w1, w2, byz, 5, h5=h5, tc_epoch=tce, late_votes=False)
            st, n = replay(m, script)
            if st is None:
                print(f"witness {name:12s} h5={h5:6s} tc-epoch={tce:5s}: step {n + 1} of {len(script)} is not enabled "
                      f"({script[n][0]} of r{script[n][1]})")
                continue
            stats = Counter()
            kinds = sorted({b[0] for b in m.check_forks(st, stats)} | {b[0] for b in m.honest_evidence(st)})
            print(f"witness {name:12s} h5={h5:6s} tc-epoch={tce:5s}: replayed; findings {kinds}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--views", type=int, default=4)
    ap.add_argument("--w1", default="37,33,30", help="weights of the old table")
    ap.add_argument("--w2", default="33,37,30", help="weights of the new table")
    ap.add_argument("--byz", default="2")
    ap.add_argument("--h5", choices=("none", "suffix", "full"), default="full")
    ap.add_argument("--tc-epoch", choices=("any", "chain"), default="chain")
    ap.add_argument("--e4", choices=("vote", "s16"), default="vote")
    ap.add_argument("--votes", choices=("late", "current"), default="late")
    ap.add_argument("--no-symmetry", action="store_true",
                    help="count every state, also when the two honest nodes are interchangeable (as Handover.tla)")
    ap.add_argument("--max-states", type=int, default=20_000_000)
    ap.add_argument("--stop-on", default="", help="comma list of findings that end the search early")
    ap.add_argument("--safety", action="store_true", help="report a fork of the ledger as a finding")
    ap.add_argument("--mem-gb", type=float, default=None, help="stop (truncated) when the peak RSS exceeds this")
    ap.add_argument("--witness", action="store_true", help="replay the two scripted executions of S16 and exit")
    a = ap.parse_args(argv)
    if a.witness:
        check_witnesses()
        return 0
    w1 = [int(x) for x in a.w1.split(",")]
    w2 = [int(x) for x in a.w2.split(",")]
    byz = [int(x) for x in a.byz.split(",")]
    m = Model(w1, w2, byz, a.views, h5=a.h5, tc_epoch=a.tc_epoch, e4=a.e4, late_votes=a.votes == "late",
              symmetry=not a.no_symmetry)
    stop = tuple(x for x in a.stop_on.split(",") if x)
    report = ("ledger_fork",) if a.safety or "ledger_fork" in stop else ()
    stats, found, order, par = explore(m, a.max_states, stop, a.mem_gb, report)
    shares = {t: [round(sum(m.w[t][i] for i in m.byz) / sum(m.w[t]), 3)] for t in (1, 2)}
    print(f"w1={w1} w2={w2} byz={byz} (shares {shares[1][0]}, {shares[2][0]}) views={a.views} h5={a.h5} "
          f"tc-epoch={a.tc_epoch} e4={a.e4} votes={a.votes} symmetric={m.sym}")
    print("stats:", dict(sorted(stats.items(), key=lambda kv: str(kv[0]))))
    if not found:
        print("RESULT: no violation in the explored states")
    for kind, (si, x) in found.items():
        detail = x
        if kind in ("ledger_fork", "light_culprit_set", "honest_blamed", "structure"):
            detail = (x[0], x[1], tuple(fmt_block(m.blk[i]) for i in x[2]), tuple(fmt_block(m.blk[i]) for i in x[3]),
                      x[4])
        print(f"RESULT: {kind}: {detail}")
        for line in trace(m, order, par, si):
            print("   ", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

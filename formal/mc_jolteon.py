"""Bounded explicit-state model checker for accountable safety of Jolteon-style two-chain HotStuff
(理论_可问责安全与纪元交接 §3.1 定理 1, 命题 3). Abstract model only; nothing contacts a real system.

Model
* n replicas with weights w; Byzantine set B with share above 1/3, so that forks are possible; a quorum
  is a set with share strictly above 2/3. Views 1..V; genesis block G (view 0) has a QC everyone knows.
* Byzantine replicas are not processes: they sign anything at any time. So a certificate is formable as
  soon as the honest signatures it needs exist, and every leader is Byzantine: any valid block that can be
  built from formable certificates may be proposed at any time (honest proposals are a special case).
  Proposals are therefore not part of the state; a vote enumerates the blocks constructible at that
  moment. Each honest replica votes once per view, so at most |honest| blocks per view get votes.
* Block = (v, parent, tc). The justify QC is QC(parent), j = view(parent) < v (V1). If j < v-1 the block
  embeds TC(v-1) (V2): tc = (m, qcb), m <= j the largest reported hq, qcb a block with a QC at view m that
  the TC carries. Honest replicas vote only for valid blocks (R4); every block built here is valid.
* Honest replica k: h (highest certificate view it knows; it is in view h+1), hq (block of its highest
  QC), ell (highest view it has signed), voted views, timed-out views. Asynchronous network under
  adversarial scheduling: any formable certificate and any proposal can be delivered at any time.
  A step of replica k first learns certificates, then signs (macro step: learning only matters for the
  next signature and formability only grows, so postponing it loses no behaviour):
    learn:    hq' = hq or a formable QC of a higher view (R6); h' >= max(h, view(hq')); h' above
              view(hq') needs a formable TC(h') that, when adopting, carries a QC no higher than hq'.
    timeout:  v = h'+1 <= V, not timed out in v: sign (v, view(hq')) (R5); ell = max(ell, v).
    vote B:   v = view(B) <= h'+1, not voted or timed out in v, and v > ell when R3 is on.
              h = max(h', v-1); hq = max(hq', parent(B)) (R6), and the QC carried by B.tc if adopting;
              ell = max(ell, v).
* Commit (two-chain, R7): X is committed with X+ when view(X+) = view(X)+1, parent(X+) = X and both
  have formable QCs; (X, X+) is the commit proof.
Checks, on every reachable state
* soundness (lemma 1): no honest replica holds E3 (a vote at view a for a block with justify view j and
  a timeout at a view b >= a with hq < j). E1 cannot occur (one vote per view), E2 cannot (R4).
* theorem 1: for every fork (two conflicting committed blocks) and every choice of the signer sets of
  the certificates the proof uses, the case analysis (A, B, C1, C2, C3) applies (its structural claims,
  e.g. V1, V2 and the minimality of Z, hold) and outputs C that contains no honest replica.
  "weight(C) > 1/3" holds by quorum intersection for any two quorums (lemma 0), so it is checked but
  cannot fail; "no honest replica in C" amounts to "no honest replica holds E1 or E3".
Scope (review 信任2.0_写作前准备_审查 I-6): with V <= 4, C3 forks only have w = u+2, where R3 is not
needed; R3 matters from V = 5 on, shown by the scripted witness (--witness), not by exhaustive search.
Blocks of the same view with the same parent and TC are identical here (no payload bit), so case C2 is
unreachable for V <= 4.
Variants: --no-r3 (late votes allowed), --non-adopting (the TC carries only rounds, as DiemBFT v4).
States are tuples of small integers (blocks interned); with equal honest weights the two honest replicas
are symmetric and states are kept in canonical form.

Run from the repository root:  python formal/mc_jolteon.py [--views 4] [--no-r3] [--non-adopting]
"""
import argparse
import itertools
import resource
import sys
import time
from array import array
from collections import Counter, deque

G = (0, None, None)                           # genesis block (view, parent, tc)


def view(b):
    return b[0]


def parent(b):
    return b[1]


def is_ancestor(a, b):
    """a is an ancestor of b or a == b."""
    while b is not None:
        if b == a:
            return True
        b = parent(b)
    return False


def fmt_block(b):
    if b == G:
        return "G"
    tc = "" if b[2] is None else f",TC(m={b[2][0]})"
    return f"B{view(b)}<{fmt_block(parent(b))}{tc}>"


class Model:
    def __init__(self, weights, byz, views, r3=True, adopting=True):
        self.w = weights
        self.n = len(weights)
        self.byz = frozenset(byz)
        self.hon = tuple(i for i in range(self.n) if i not in self.byz)
        self.wb = sum(weights[i] for i in self.byz)
        self.V, self.r3, self.adopting = views, r3, adopting
        assert self.wb > 1 / 3, "forks need a Byzantine share above 1/3"
        self.blk, self.bid = [G], {G: 0}
        self.sym = len(self.hon) == 2 and weights[self.hon[0]] == weights[self.hon[1]]

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
               tuple(sorted((sw[k], v, hk) for (k, v, hk) in tmos)))
        return min(st, st2)

    # ---- weights and certificates -------------------------------------------------------------
    def weight(self, s):
        return sum(self.w[i] for i in s)

    def quorum(self, s):
        return self.weight(s) > 2 / 3 + 1e-12

    def voters(self, st, i):
        return frozenset(k for (k, x) in st[1] if x == i)

    def qc_ok(self, st, i):
        return i == 0 or self.quorum(self.voters(st, i) | self.byz)

    def qc_ids(self, st):
        return [i for i in {x for (_, x) in st[1]} | {0} if self.qc_ok(st, i)]

    def tc_ok(self, st, v, m):
        """TC(v) whose largest reported hq is m."""
        if not 0 <= m < v:
            return False
        low = frozenset(k for (k, vv, hk) in st[2] if vv == v and hk <= m)
        return self.quorum(low | self.byz)

    def constructible(self, st, v, qcs):
        """Valid blocks of view v buildable from formable certificates (V1, V2), as interned ids."""
        out = []
        for p in qcs:
            pb = self.blk[p]
            j = view(pb)
            if j >= v:
                continue
            if j == v - 1:
                out.append(self.intern((v, pb, None)))
            else:
                for q in qcs:
                    qb = self.blk[q]
                    if view(qb) <= j and self.tc_ok(st, v - 1, view(qb)):
                        out.append(self.intern((v, pb, (view(qb), qb))))
        return out

    # ---- transitions ------------------------------------------------------------------------
    def initial(self):
        return (tuple((0, 0, 0, 0, 0) for _ in self.hon), (), ())

    def learn_options(self, st, h, hq, qcs):
        opts = set()
        hqv = view(self.blk[hq])
        for hq1 in [hq] + [q for q in qcs if view(self.blk[q]) > hqv]:
            v1 = view(self.blk[hq1])
            base = max(h, v1)
            opts.add((base, hq1))
            for t in range(base + 1, self.V + 1):
                if any(self.tc_ok(st, t, view(self.blk[q])) and (not self.adopting or view(self.blk[q]) <= v1)
                       for q in qcs):
                    opts.add((t, hq1))
        return opts

    def successors(self, st):
        hs, votes, tmos = st
        qcs = self.qc_ids(st)
        cons = {}
        for idx, k in enumerate(self.hon):
            h, hq, ell, vm, tm = hs[idx]
            for (h1, hq1) in self.learn_options(st, h, hq, qcs):
                v = h1 + 1
                if v <= self.V and not tm >> v & 1:
                    hk = view(self.blk[hq1])
                    ns = (h1, hq1, max(ell, v), vm, tm | 1 << v)
                    yield ("timeout", k, v, hk), (hs[:idx] + (ns,) + hs[idx + 1:], votes,
                                                   tuple(sorted(tmos + ((k, v, hk),))))
                for bv in range(1, min(h1 + 1, self.V) + 1):
                    if vm >> bv & 1 or tm >> bv & 1 or (self.r3 and bv <= ell):
                        continue
                    if bv not in cons:
                        cons[bv] = self.constructible(st, bv, qcs)
                    for b in cons[bv]:
                        bb = self.blk[b]
                        nhq = max(hq1, self.intern(parent(bb)), key=lambda i: view(self.blk[i]))
                        if self.adopting and bb[2] is not None:
                            nhq = max(nhq, self.intern(bb[2][1]), key=lambda i: view(self.blk[i]))
                        ns = (max(h1, bv - 1), nhq, max(ell, bv), vm | 1 << bv, tm)
                        yield ("vote", k, b), (hs[:idx] + (ns,) + hs[idx + 1:],
                                               tuple(sorted(votes + ((k, b),))), tmos)

    # ---- checks -------------------------------------------------------------------------------
    def honest_e3(self, st):
        bad = []
        for (k, x) in st[1]:
            b = self.blk[x]
            a, j = view(b), view(parent(b))
            for (kk, tv, hk) in st[2]:
                if kk == k and tv >= a and hk < j:
                    bad.append((k, fmt_block(b), tv, hk))
        return bad

    def quorums(self, avail):
        avail = sorted(avail)
        for r in range(1, len(avail) + 1):
            for s in itertools.combinations(avail, r):
                if self.quorum(s):
                    yield frozenset(s)

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
        """Case analysis of theorem 1 for commit proofs cpx = (X, X+), cpy = (Y, Y+) (ids), view(X) <= view(Y).
        Yields (case, C) for every choice of signer sets."""
        X, Xp = cpx
        Y, _ = cpy
        Yb = self.blk[Y]
        u = view(self.blk[X])
        q1s = list(self.quorums(self.voters(st, X) | self.byz))
        q2s = list(self.quorums(self.voters(st, Xp) | self.byz))
        if view(Yb) == u:
            for q1 in q1s:
                for qy in self.quorums(self.voters(st, Y) | self.byz):
                    yield "A", q1 & qy
            return
        if view(Yb) == u + 1:
            for q2 in q2s:
                for qy in self.quorums(self.voters(st, Y) | self.byz):
                    yield "B", q2 & qy
            return
        z = Yb                                 # the ancestor of Y with the smallest view above u+1
        while view(parent(z)) > u + 1:
            z = parent(z)
        p, j, w = parent(z), view(parent(z)), view(z)
        assert j < w and not (u + 1 < j < w)
        qz = list(self.quorums(self.voters(st, self.bid[p]) | self.byz))
        if j == u + 1:
            for q2 in q2s:
                for q in qz:
                    yield "C1", q2 & q
        elif j == u:
            for q1 in q1s:
                for q in qz:
                    yield "C2", q1 & q
        else:
            assert z[2] is not None, "validity V2: a block with j < w-1 embeds TC(w-1)"
            m = z[2][0]
            assert m <= j
            low = frozenset(k for (k, tv, hk) in st[2] if tv == w - 1 and hk <= m)
            for q2 in q2s:
                for t in self.quorums(low | self.byz):
                    yield "C3", q2 & t

    def chain_e1(self, st, cx, cy):
        """Is there E1 evidence among the certified blocks of the two branches (two formable QCs of the same
        view for different blocks)? The branches are X, X+ and Y with all its ancestors."""
        blocks = {self.blk[cx[0]], self.blk[cx[1]]}
        b = self.blk[cy[1]]
        while b is not None:
            blocks.add(b)
            b = parent(b)
        by_view = {}
        for b in blocks:
            if b != G and self.qc_ok(st, self.bid[b]):
                by_view.setdefault(view(b), set()).add(b)
        return any(len(v) > 1 for v in by_view.values())

    def check_forks(self, st, stats):
        bad, forks = [], 0
        cps = self.commits(st)
        for (cx, cy) in itertools.combinations(cps, 2):
            X, Y = self.blk[cx[0]], self.blk[cy[0]]
            if is_ancestor(X, Y) or is_ancestor(Y, X):
                continue
            forks += 1
            if view(X) > view(Y):
                cx, cy = cy, cx
            cases = set()
            for case, c in self.judge(st, cx, cy):
                cases.add(case)
                if not self.weight(c) > 1 / 3 + 1e-12:
                    bad.append(("light_culprit_set", case, cx, cy, tuple(sorted(c))))
                if c - self.byz:
                    bad.append(("honest_blamed", case, cx, cy, tuple(sorted(c - self.byz))))
            for case in cases:
                stats["forks_" + case] += 1
            if "C3" in cases and not self.chain_e1(st, cx, cy):
                stats["forks_C3_tc_only"] += 1       # no same-view QC conflict on chain: only the TC convicts
        if forks:
            stats["fork_states"] += 1
        return bad


def explore(model, max_states, stop_on=(), mem_gb=None):
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
        if "honest_e3" not in found:
            e3 = model.honest_e3(st)
            if e3:
                found["honest_e3"] = (si, e3[0])
        for x in model.check_forks(st, stats):
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
    # every state within (dcur - 1) steps has been checked; when the search ran out of states, all of them
    stats["checked_all_within_steps"] = "all" if not q and "truncated" not in stats else max(dcur - 1, 0)
    stats["seconds"] = round(time.time() - t0, 1)
    return stats, found, order, par


def trace(model, order, par, si):
    path = []
    while si != -1:
        path.append(order[si])
        si = par[si]
    path.reverse()
    acts = []
    perm = {k: k for k in model.hon}           # canonical label -> label in the reported execution
    for a, b in zip(path, path[1:]):
        for act, ns in model.successors(a):
            if model.canon(ns) == b:
                acts.append((act[0], perm[act[1]]) + act[2:])
                if ns != b:                    # canon swapped the two honest replicas
                    x, y = model.hon
                    perm = {x: perm[y], y: perm[x]}
                break
    return acts


def replay(model, script):
    """Replay a scripted execution with the model's own transitions (no canonical form). script: list of
    ("vote", k, block) or ("timeout", k, v, hq); each step must match an enabled action of replica k
    (learning before it is chosen as needed). Returns the final state, or raises if a step is not enabled."""
    st = model.initial()
    for step in script:
        nxt = None
        for act, ns in model.successors(st):
            if step[0] == "vote" and act[0] == "vote" and act[1] == step[1] and model.blk[act[2]] == step[2]:
                nxt = ns
            if step[0] == "timeout" and act[0] == "timeout" and act[1:4] == step[1:4]:
                nxt = ns
            if nxt is not None:
                break
        if nxt is None:
            raise ValueError(f"step not enabled: {step}")
        st = nxt
    return st


B1 = (1, G, None)
WITNESS_NO_R3 = [                              # 命题 3(b): without R3 an honest replica is convicted (V = 5)
    ("vote", 1, B1),                           # r1 votes B1; QC(B1) with the Byzantine pair
    ("timeout", 0, 1, 0),                      # r0 times out in view 1 with hq 0 -> TC(1)
    ("timeout", 1, 2, 0),                      # r1 enters view 2 by TC(1), never learns QC(B1); TC(2), m = 0
    ("timeout", 0, 3, 0),                      # r0 enters view 3 by TC(2) (it never timed out in view 2)
    ("vote", 0, (2, B1, None)),                # late vote of r0 for X+ = B2<B1> (allowed without R3): X committed
    ("vote", 1, (4, G, (0, G))),               # Z = B4<G, TC(3) with m = 0>, conflicting with X
    ("vote", 1, (5, (4, G, (0, G)), None)),    # Z+ : Z committed
]


def check_witness(views=5, r3=False):
    m = Model([0.25] * 4, [2, 3], views, r3=r3)
    try:
        st = replay(m, WITNESS_NO_R3)
    except ValueError as e:
        print(f"witness (R3={r3}): {e}")
        return
    stats = Counter()
    bad = m.check_forks(st, stats)
    print(f"witness (R3={r3}): honest E3 {m.honest_e3(st)}; findings {sorted({b[0] for b in bad})}; "
          f"cases {dict(stats)}")
    for b in bad[:1]:
        print("   ", b)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--views", type=int, default=4)
    ap.add_argument("--weights", default="0.25,0.25,0.25,0.25")
    ap.add_argument("--byz", default="2,3")
    ap.add_argument("--no-r3", action="store_true")
    ap.add_argument("--non-adopting", action="store_true")
    ap.add_argument("--max-states", type=int, default=20_000_000)
    ap.add_argument("--stop-on", default="", help="comma list of findings that end the search early")
    ap.add_argument("--mem-gb", type=float, default=None, help="stop (truncated) when the peak RSS exceeds this")
    ap.add_argument("--witness", action="store_true", help="replay the scripted 命题 3(b) execution and exit")
    a = ap.parse_args(argv)
    if a.witness:
        check_witness(r3=False)
        check_witness(r3=True)
        return 0
    w = [float(x) for x in a.weights.split(",")]
    byz = [int(x) for x in a.byz.split(",")]
    m = Model(w, byz, a.views, r3=not a.no_r3, adopting=not a.non_adopting)
    stop = tuple(x for x in a.stop_on.split(",") if x)
    stats, found, order, par = explore(m, a.max_states, stop, a.mem_gb)
    print(f"weights={w} byz={byz} views={a.views} R3={m.r3} adopting={m.adopting} symmetric={m.sym}")
    print("stats:", dict(stats))
    if not found:
        print("RESULT: no violation (honest E3, honest blamed, light culprit set) in the explored states")
    for kind, (si, x) in found.items():
        print(f"RESULT: {kind}: {x}")
        for act in trace(m, order, par, si):
            if act[0] == "vote":
                print(f"   r{act[1]} votes {fmt_block(m.blk[act[2]])}")
            else:
                print(f"   r{act[1]} times out in view {act[2]} with hq {act[3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

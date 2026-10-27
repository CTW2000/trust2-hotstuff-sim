"""Transaction inclusion attestations (G2; 证据扩展_NR矛盾与包含证言_设计.md, part 2). Abstract models only.

Transactions do not change consensus in this model (block contents never affect voting), so the
transaction layer is computed lazily from facts the engines have already fixed: entry times
(know), proposal times and parents, certificates (qc_exists). It can therefore be read by a
leader rule with the usual lag (schedule.bad_fact(..., "omit")) without touching the engines.

Model
* Transactions: per view w, Poisson(rate) transactions are submitted at E[w-1] + U(0, 50 ms)
  (E = first honest entry time) to m random replicas; a share victim_frac belongs to a "victim"
  client. Gossip: every honest holder forwards to all replicas on receipt (delays
  net.delays(w, "tx"), so model P late messages, asynchrony and region outages apply); colluders
  forward too unless the adversary says otherwise. hold[x, k] = first time replica k holds x.
* Attestation for view u: honest k attests x iff hold[x, k] <= entry_k(u) - delta_g, i.e. it held
  x and had forwarded it delta_g before entering u (entry_k(u) = know[u-1, k]). Colluders attest
  as the adversary says (truthfully by default).
* Due: x is due in u iff at least `threshold` attestations (all replicas) contain it and x is not
  yet in a certified block of an earlier view ("pending").
* Block contents: the leader of u includes, at its proposal time, the pending transactions it
  holds, oldest first, at most `capacity` of them, and at most one transaction of each conflicting
  pair (the other becomes invalid once one is included); a censoring colluder leader drops the
  victim transactions. A block counts as including x once it is certified (qc_exists[u]).
* omit(u): block u is certified and some due, non-exempt transaction is not in it. Exempt: the
  block is full (capacity), or x is invalid (its conflicting partner is in this block or an
  earlier certified one) -- both checkable from the chain. exempt=False switches the exemptions
  off (control group).

Adversary (TxAdversary)
  censor   probability that a colluder leader censors the victim transactions in its view; while
           censoring is on, colluders neither forward nor attest victim transactions
  frame    probability, per honest-led view, of an INC-2 framing attempt: a fresh transaction is
           handed to just enough honest replicas (max(1, threshold - f0)) delta_g + 1 ms before
           their entry, never to the leader; colluders attest it and do not forward it
  conflict probability, per view, that colluders submit a conflicting pair to every replica
"""
from dataclasses import dataclass, field

import numpy as np


@dataclass
class TxAdversary:
    censor: float = 0.0
    frame: float = 0.0
    conflict: float = 0.0


@dataclass
class TxConfig:
    rate: float = 2.0                 # transactions per view
    m: int = None                     # replicas a client submits to; None = f+1 (at least one honest)
    victim_frac: float = 0.25
    delta_g: float = None             # attestation guard (ms); None = net.delta_fwd() + net.delta_max()
    threshold: str = "q"              # "q" (2f+1) or "f+1"; weighted voting (cfg.vote_weights): "w" = attesting
                                      # share strictly above 2/3, "w13" = above 1/3 (the f+1 analogue, control)
    capacity: int = None              # block capacity in transactions; None = unbounded
    exempt: bool = True               # master switch of the exemptions
    exempt_full: bool = True          # a full block is exempt
    exempt_invalid: bool = True       # an invalid transaction (conflicting partner included) is exempt
    adversary: TxAdversary = field(default_factory=TxAdversary)
    seed: int = 0


class TxLayer:
    """Lazily processed transaction layer bound to one run (state cached on the State)."""

    def __init__(self, tcfg: TxConfig, net):
        self.t, self.net = tcfg, net

    # ---- per-run state
    def _s(self, st):
        s = st.__dict__.get("_txlayer")
        if s is None:
            cfg = st.cfg
            dg = self.t.delta_g if self.t.delta_g is not None else self.net.delta_fwd() + self.net.delta_max()
            if self.t.threshold in ("w", "w13") and cfg.vote_weights is None:
                raise ValueError("weighted due thresholds need cfg.vote_weights")
            thr = {"q": cfg.quorum, "f+1": cfg.f + 1, "w": 2 / 3, "w13": 1 / 3}[self.t.threshold]
            s = dict(done=0, dg=dg, thr=thr, hold=[], meta=[], pending=[], included=[], invalid=[], first_due=[],
                     partner=[], omit=np.zeros(cfg.views + 2, bool), omit_tx=[[] for _ in range(cfg.views + 2)],
                     content={})
            st.__dict__["_txlayer"] = s
        return s

    def _relay(self, st, src_times, w, fwd_mask):
        """First holding times when replicas in fwd_mask relay on receipt (Dijkstra, n small)."""
        n = st.cfg.n
        D = self.net.delays(w, "tx")
        hold = src_times.copy()
        done = np.zeros(n, bool)
        alive = st.alive
        for _ in range(n):
            cand = np.where(done | ~alive, np.inf, hold)
            j = int(np.argmin(cand))
            if not np.isfinite(cand[j]):
                break
            done[j] = True
            if fwd_mask[j]:
                hold = np.minimum(hold, hold[j] + D[j])
        hold[~alive] = np.inf
        return hold

    def _add(self, st, s, src_times, w, victim, forwarders, attest_byz, frame=False, partner=-1):
        x = len(s["hold"])
        s["hold"].append(self._relay(st, src_times, w, forwarders))
        s["meta"].append(dict(view=w, victim=victim, frame=frame, attest_byz=attest_byz))
        s["included"].append(-1)
        s["first_due"].append(-1)
        s["invalid"].append(False)
        s["partner"].append(partner)
        s["pending"].append(x)
        return x

    def _submit(self, st, s, w):
        """Transactions of view w (submitted when the first honest replica enters w)."""
        cfg, t, adv = st.cfg, self.t, self.t.adversary
        H = st.honest
        E = np.min(np.where(H, st.know[w - 1], np.inf))
        if not np.isfinite(E):
            return
        rng = np.random.default_rng([t.seed, 71, w])
        n = cfg.n
        for _ in range(rng.poisson(t.rate)):
            victim = rng.random() < t.victim_frac
            src = np.full(n, np.inf)
            m = cfg.f + 1 if t.m is None else t.m
            src[rng.choice(n, size=m, replace=False)] = E + rng.random() * 50.0
            fwd = st.alive.copy()
            att = True
            if victim and adv.censor > 0:
                fwd = fwd & ~st.byz                 # colluders neither forward nor attest victim txs
                att = False
            self._add(st, s, src, w, victim, fwd, att)
        if adv.conflict > 0 and st.byz.any() and rng.random() < adv.conflict:
            src = np.where(st.alive, E + 1.0, np.inf)
            a = self._add(st, s, src, w, False, st.alive.copy(), True)
            b = self._add(st, s, src, w, False, st.alive.copy(), True, partner=a)
            s["partner"][a] = b

    def _frame(self, st, s, u):
        """INC-2 attempt in honest-led view u: hand a fresh transaction to just enough honest replicas
        delta_g + 1 ms before their entry, never to the leader; colluders attest it, do not forward."""
        cfg, adv = st.cfg, self.t.adversary
        L = st.leaders[u]
        if adv.frame <= 0 or not st.byz.any() or not st.honest[L]:
            return
        rng = np.random.default_rng([self.t.seed, 73, u])
        if rng.random() >= adv.frame:
            return
        hon = [int(k) for k in np.flatnonzero(st.honest) if k != L and np.isfinite(st.know[u - 1, k])]
        if self.t.threshold in ("w", "w13"):          # weighted: heaviest honest replicas first (fewest holders)
            sh = np.asarray(cfg.vote_weights(st, u), float)
            order = sorted(hon, key=lambda k: sh[k])  # pop() takes the heaviest
            acc, pick = float(sh[st.byz].sum()), []
            while order and acc <= s["thr"] + 1e-9:
                k = order.pop()
                pick.append(k)
                acc += sh[k]
            if acc <= s["thr"] + 1e-9:
                return
            pick = np.array(pick, int)
        else:
            need = max(1, s["thr"] - int(st.byz.sum()))
            if need > len(hon):
                return
            pick = rng.choice(hon, size=need, replace=False)
        src = np.full(cfg.n, np.inf)
        src[pick] = st.know[u - 1, pick] - s["dg"] - 1.0
        fwd = st.alive & ~st.byz
        self._add(st, s, src, u, False, fwd, True, frame=True)

    def _view(self, st, s, u):
        cfg, t, adv = st.cfg, self.t, self.t.adversary
        self._submit(st, s, u)
        self._frame(st, s, u)
        keep_invalid = not (t.exempt and t.exempt_invalid)     # control group: invalid transactions stay due
        pend = [x for x in s["pending"] if s["included"][x] < 0 and (keep_invalid or not s["invalid"][x])]
        s["pending"] = pend
        L = st.leaders[u]
        if L < 0 or st.prop_parent[u] < 0:
            return
        # attestations and due transactions of view u
        entry = st.know[u - 1]
        due = []
        if pend:
            hold = np.array([s["hold"][x] for x in pend])
            weighted = self.t.threshold in ("w", "w13")
            wv = np.asarray(cfg.vote_weights(st, u), float) if weighted else np.ones(cfg.n)
            att = hold <= (entry - s["dg"])[None, :]
            ok_h = (att[:, st.honest] * wv[st.honest][None, :]).sum(axis=1)
            nb = float(wv[st.byz & st.alive].sum())
            for i, x in enumerate(pend):
                meta = s["meta"][x]
                if meta["attest_byz"]:
                    if meta["frame"]:
                        byz_att = nb
                    else:
                        byz_att = float((att[i, st.byz] * wv[st.byz]).sum())
                else:
                    byz_att = 0.0
                tot = ok_h[i] + byz_att
                if (tot > s["thr"] + 1e-9) if weighted else (tot >= s["thr"]):
                    due.append(x)
                    if s["first_due"][x] < 0:
                        s["first_due"][x] = u
        # block contents
        tp = st.prop_time[u]
        held = [x for x in pend if s["hold"][x][L] <= tp]
        held.sort(key=lambda x: s["hold"][x][L])
        censor = (st.byz[L] and adv.censor > 0
                  and np.random.default_rng([t.seed, 79, u]).random() < adv.censor)
        content, taken = [], set()
        for x in held:
            if censor and s["meta"][x]["victim"]:
                continue
            p = s["partner"][x]
            if p >= 0 and (p in taken or s["included"][p] >= 0):
                continue
            if t.capacity is not None and len(content) >= t.capacity:
                break
            content.append(x)
            taken.add(x)
        full = t.capacity is not None and len(content) >= t.capacity
        certified = bool(st.qc_exists[u])
        if certified:
            for x in content:
                s["included"][x] = u
            for x in content:
                p = s["partner"][x]
                if p >= 0 and s["included"][p] < 0:
                    s["invalid"][p] = True
        s["content"][u] = (len(content), full, censor)
        if certified:
            missed = []
            for x in due:
                if x in taken:
                    continue
                if t.exempt and ((t.exempt_full and full) or (t.exempt_invalid and s["invalid"][x])):
                    continue
                missed.append(x)
            if missed:
                s["omit"][u] = True
                s["omit_tx"][u] = missed

    def advance(self, st, upto: int):
        s = self._s(st)
        for u in range(s["done"] + 1, upto + 1):
            if u >= 2:
                self._view(st, s, u)
        s["done"] = max(s["done"], upto)
        return s

    def omit(self, st, u: int) -> bool:
        return bool(self.advance(st, u)["omit"][u])

    # ---- post-hoc metrics
    def victim_delays(self, st, lo: int, hi: int, split: bool = False):
        """Inclusion delay (views) of victim and of other transactions submitted in [lo, hi).
        split=True: for victim transactions also return (views before first due, views after)."""
        s = self.advance(st, st.cfg.views - 3)
        vic, oth, parts = [], [], []
        for x, meta in enumerate(s["meta"]):
            if meta["frame"] or s["partner"][x] >= 0 or not (lo <= meta["view"] < hi):
                continue
            inc = s["included"][x]
            end = inc if inc >= 0 else st.cfg.views
            d = end - meta["view"]
            (vic if meta["victim"] else oth).append(d)
            if meta["victim"]:
                fd = s["first_due"][x]
                parts.append((d, 0) if fd < 0 or fd >= end else (fd - meta["view"], end - fd))
        return (vic, oth, parts) if split else (vic, oth)

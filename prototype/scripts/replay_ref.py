"""Reference replay of a committed ledger to the weight tables (prototype/SPEC.md), in plain integers.

A second implementation of the rules in SPEC.md, written in Python without numpy or the simulator, so that the
ledger replay vectors (consensus/src/tests/replay_vectors.json, gen_replay_vectors.py) do not come from the code
they check. Only the standard library is used; all arithmetic is on integers, as in the prototype.

Scope: the Trust 2.0 leader rule with AT accusations and G1 evidence (E1-E3 as safety, E-NR as liveness). Omission
proofs are not replayed (their validity needs the transactions of the blocks); on the ledger they are bad facts of
their round exactly like an accusation. Fork evictions and governance-confirmed malice are not exercised either.

Members are numbered in the order of their public keys; the leader draw sorts them the same way.
"""
import hashlib

ONE = 10 ** 18
PPM = 10 ** 6
STAKE_TOTAL = 10 ** 6
REFERENCE_LENGTH = 100


# ---------------------------------------------------------------- SPEC §1: CapNorm

def cap_normalize(v, cap, total):
    """Water filling: shares proportional to v summing to `total`, none above `cap`. None if the positive entries
    cannot hold `total` under the cap (the roster is rejected)."""
    if total == 0:
        return [0] * len(v)
    if sum(1 for x in v if x > 0) * cap < total:
        return None
    fixed = [False] * len(v)
    while True:
        rest = max(total - cap * sum(fixed), 0)
        free = sum(x for x, f in zip(v, fixed) if not f)
        out = [cap if f else (0 if free == 0 else x * rest // free) for x, f in zip(v, fixed)]
        changed = False
        for i, o in enumerate(out):
            if not fixed[i] and o > cap:
                fixed[i] = changed = True
        if not changed:
            return out


def base_weights(licensed, w, cap, u_max):
    """CapNorm of the entity weights w; licensed[k] is the class of entity k. Raises ValueError on rejection."""
    total = sum(w)
    lic = [x for x, c in zip(w, licensed) if c]
    unc = [x for x, c in zip(w, licensed) if not c]
    if total == 0:
        raise ValueError("Empty")
    if not any(x > 0 for x in lic):
        raise ValueError("NoLicensed")
    n_u = sum(1 for x in unc if x > 0)
    u = min(sum(unc) * ONE // total, u_max, n_u * cap)
    lic_w = cap_normalize(lic, cap, ONE - u)
    unc_w = cap_normalize(unc, cap, u)
    if lic_w is None or unc_w is None:
        raise ValueError("Cap")
    lic_w, unc_w = iter(lic_w), iter(unc_w)
    return [next(lic_w) if c else next(unc_w) for c in licensed]


# ---------------------------------------------------------------- SPEC §2: the table

def table(base, r_ppm, z, b_rep):
    """Integer entity stakes: cuts d = b(1-r) shrunk to the budget, T = (b-d)z, floor(T * 10^6 / sum T)."""
    cut = [b * (PPM - r) // PPM for b, r in zip(base, r_ppm)]
    total_cut = sum(cut)
    if total_cut > b_rep:
        cut = [c * b_rep // total_cut for c in cut]
    t = [b - c if on else 0 for b, c, on in zip(base, cut, z)]
    s = sum(t)
    return [0 if s == 0 else x * STAKE_TOTAL // s for x in t]


# ---------------------------------------------------------------- SPEC §3: the leader draw

def draw(epoch, round_):
    """The first 8 bytes, little endian, of SHA-512(epoch as 16 bytes LE || round as 8 bytes LE)."""
    digest = hashlib.sha512(epoch.to_bytes(16, "little") + round_.to_bytes(8, "little")).digest()
    return int.from_bytes(digest[:8], "little")


def leader(tab, round_):
    """The leader of `round_` by the table `tab` (dict: epoch, stake, leader, handover)."""
    if tab["handover"] is not None and tab["handover"][0] == round_:
        return tab["handover"][1]
    members = [(i, s) for i, (s, may) in enumerate(zip(tab["stake"], tab["leader"])) if s > 0 and may]
    if not members:  # everyone barred: every member with weight 1, so the round still has a leader
        members = [(i, 1) for i in range(len(tab["stake"]))]
    total = sum(s for _, s in members)
    point = (draw(tab["epoch"], round_) * total) >> 64
    for i, s in members:
        if point < s:
            return i
        point -= s
    raise AssertionError("the draw is below the total weight")


# ---------------------------------------------------------------- parameters at an epoch length

def scaled(n, length):
    """A duration of n reference epochs (100 views) in epochs of `length` views, rounded, at least 1."""
    if length == REFERENCE_LENGTH:
        return n
    return max((n * REFERENCE_LENGTH + length // 2) // length, 1)


class G2Params:
    def __init__(self, length):
        self.lag = 10
        self.up, self.down, self.threshold = 1_609_438, -587_787, 4_605_170
        self.exclusion = 500
        self.cap = ONE // 2
        self.r_min, self.step = 700_000, 100_000
        self.recover = 20_000 * length // REFERENCE_LENGTH
        self.b_rep = ONE // 10


class G1Params:
    def __init__(self, length, l_max):
        self.l_max = l_max
        self.lead_bar = scaled(1, length)
        self.sign_window = scaled(1, length)
        self.suspend_l2 = scaled(4, length)
        self.suspend_l3 = scaled(32, length)
        self.chain_window = scaled(32, length)
        self.lookback = scaled(64, length)
        self.governance_delay = scaled(2, length)


# ---------------------------------------------------------------- SPEC §5: G2

class Reputation:
    def __init__(self, base, p):
        n = len(base)
        self.p, self.base = p, base
        self.cusum, self.excluded, self.until = [0] * n, [False] * n, [0] * n
        self.done = 0
        self.r = [PPM] * n
        self.accused = {}  # round -> epoch of the first accusation of it
        self.log = []

    def record(self, round_, epoch):
        if round_ > self.done:
            self.accused.setdefault(round_, epoch)

    def advance(self, horizon, leader_of):
        self.log = []
        for u in range(max(self.done + 1, 1), horizon + 1):
            self.step(u, leader_of)
        self.done = max(self.done, horizon)
        self.accused = {u: e for u, e in self.accused.items() if u > self.done}
        convicted = {k for kind, k, _ in self.log if kind == "exclude"}
        for k in range(len(self.r)):
            if k in convicted:
                self.r[k] = max(self.r[k] - self.p.step, self.p.r_min)
            elif not self.excluded[k]:
                self.r[k] = min(self.r[k] + self.p.recover, PPM)

    def room(self, k):
        return sum(b for b, x in zip(self.base, self.excluded) if x) + self.base[k] <= self.p.cap

    def step(self, u, leader_of):
        for k in range(len(self.base)):
            if self.excluded[k] and self.until[k] <= u:
                self.excluded[k] = False
                self.log.append(("release", k, u))
        accusation = self.accused.get(u)
        k = leader_of(u, accusation)
        if k is None or self.excluded[k]:
            return
        self.cusum[k] = max(self.cusum[k] + (self.p.up if accusation is not None else self.p.down), 0)
        if self.cusum[k] >= self.p.threshold:
            self.convict(k, u)

    def convict(self, k, u):
        """Exclude if the cap leaves room, else discard the conviction: the statistic starts over."""
        if self.room(k):
            self.exclude(k, u)
        else:
            self.cusum[k] = 0
            self.log.append(("full", k, u))

    def exclude(self, k, u):
        self.excluded[k] = True
        self.until[k] = u + self.p.exclusion
        self.cusum[k] = 0
        self.log.append(("exclude", k, u))


# ---------------------------------------------------------------- SPEC §6: G1

class Item:
    def __init__(self, entity, safety, sign_epoch, chain_epoch):
        self.entity, self.safety = entity, safety
        self.sign_epoch, self.chain_epoch = sign_epoch, chain_epoch
        self.malicious = self.fork = False
        self.level = self.repeats = 0


class Punishment:
    def __init__(self, base, cap, p):
        n = len(base)
        largest = max(base)
        self.p = p
        self.p.l_max = max(p.l_max, largest)
        self.correlated_above = max(cap, largest)
        self.base0, self.base = list(base), list(base)
        self.pending, self.items, self.windows = [], [], {}
        self.bar_until = [0] * n
        self.sus_until, self.sus_length = [None] * n, [0] * n
        self.queue = []  # [entity, length, epoch queued]
        self.governance = []
        self.evicted = [False] * n
        self.log = []
        self.epoch = None

    def record(self, entity, safety, sign_epoch, chain_epoch):
        if max(chain_epoch - sign_epoch, 0) > self.p.lookback:
            return
        self.pending.append(Item(entity, safety, sign_epoch, chain_epoch))

    def add(self, item):
        key = (item.entity, item.safety, item.sign_epoch // self.p.sign_window)
        if key in self.windows:
            old = self.items[self.windows[key]]
            old.fork |= item.fork
            old.malicious |= item.malicious
        else:
            self.windows[key] = len(self.items)
            self.items.append(item)

    def repeats(self, entity, safety, chain_epoch):
        since = max(chain_epoch - self.p.lookback, 0)
        return sum(1 for x in self.items
                   if x.entity == entity and x.safety == safety and x.level > 0 and x.chain_epoch >= since)

    def correlated(self, item, k):
        def share(pick):
            return sum(self.base0[e] for e in {x.entity for x in self.items if x.safety and pick(x)})
        w, window = self.p.sign_window, self.p.chain_window
        c = share(lambda x: x.sign_epoch // w == item.sign_epoch // w)
        if item.chain_epoch + window > k:
            c = max(c, share(lambda x: x.chain_epoch + window > k and x.chain_epoch <= k))
        return c

    def level(self, item, k):
        if not item.safety:
            return min(1 + item.repeats, 3)
        c = self.correlated(item, k)
        start = 4 if item.fork or 3 * c > ONE else 3 if c > self.correlated_above else 2
        return min(start + item.repeats, 4)

    def suspend_request(self, i, length, k):
        if self.evicted[i]:
            return
        until = self.sus_until[i]
        if until is not None and until > k:
            start = until - self.sus_length[i]
            if start + length > until:
                self.sus_until[i], self.sus_length[i] = start + length, length
            return
        for entry in self.queue:
            if entry[0] == i:
                entry[1] = max(entry[1], length)
                return
        self.queue.append([i, length, k])
        self.log.append(("queue", i, k))

    def apply(self, index, level, k):
        i = self.items[index].entity
        self.log.append(("level", level, i, k))
        if level == 1:
            self.bar_until[i] = max(self.bar_until[i], k + self.p.lead_bar)
        elif level == 2:
            self.suspend_request(i, self.p.suspend_l2, k)
        elif level == 3:
            self.suspend_request(i, self.p.suspend_l3, k)
        elif not any(g[0] == i for g in self.governance):
            self.governance.append((i, k + self.p.governance_delay, index))

    def update(self, k):
        assert self.epoch is None or k == self.epoch + 1
        self.epoch = k
        self.log = []
        now = [x for x in self.pending if x.chain_epoch < k]
        self.pending = [x for x in self.pending if x.chain_epoch >= k]
        for item in sorted(now, key=lambda x: x.chain_epoch):  # stable: chain order within an epoch
            self.add(item)
        for index, item in enumerate(self.items):
            if self.evicted[item.entity]:
                continue
            if item.level == 0:
                item.repeats = self.repeats(item.entity, item.safety, item.chain_epoch)
            level = self.level(item, k)
            if level > item.level:
                item.level = level
                self.apply(index, level, k)
        due = [g for g in self.governance if g[1] <= k]
        self.governance = [g for g in self.governance if g[1] > k]
        for i, _, index in due:  # without a fork or confirmed malice (not replayed): downgraded
            self.log.append(("downgrade", i, k))
            item = self.items[index]
            self.suspend_request(i, self.p.suspend_l2 if item.repeats == 0 else self.p.suspend_l3, k)
        for i in range(len(self.base)):
            if self.sus_until[i] is not None and self.sus_until[i] <= k:
                self.sus_until[i] = None
                self.log.append(("release", i, k))
        keep, blocked = [], False
        for i, length, t in self.queue:
            if not blocked and self.suspended_share(k) + self.base[i] <= self.p.l_max:
                self.sus_until[i], self.sus_length[i] = k + length, length
                self.log.append(("suspend", i, k))
            else:
                blocked = True
                keep.append([i, length, t])
        self.queue = keep

    def suspended_share(self, k):
        return sum(self.base[i] for i in range(len(self.base))
                   if self.sus_until[i] is not None and self.sus_until[i] > k)

    def suspended(self, i):
        k = self.epoch or 0
        return self.evicted[i] or (self.sus_until[i] is not None and self.sus_until[i] > k)

    def z(self):
        return [not self.suspended(i) for i in range(len(self.base))]

    def bars(self):
        """L1, suspended or evicted; an entity queued for a suspension keeps leading until it starts."""
        k = self.epoch or 0
        return [self.bar_until[i] > k or self.suspended(i) for i in range(len(self.base))]


# ---------------------------------------------------------------- SPEC §3 and §7: epochs and the replay

class Replay:
    """The ledger of one node, block by block in chain order (`feed`), from the configured roster.

    roster: list of members in key order, each dict(stake, certified, entity) with entity an id or None.
    """

    def __init__(self, roster, length, cap_ppm, u_max_ppm, l_max_ppm, origin=0):
        self.length = length
        self.stake = [m["stake"] for m in roster]
        # entities in the order of their first members
        self.entity_of, count, known = [], 0, {}
        for m in roster:
            if m["entity"] is not None and m["entity"] in known:
                self.entity_of.append(known[m["entity"]])
                continue
            if m["entity"] is not None:
                known[m["entity"]] = count
            self.entity_of.append(count)
            count += 1
        licensed, w = [True] * count, [0] * count
        for m, e in zip(roster, self.entity_of):
            w[e] += m["stake"]
            if not m["certified"]:
                licensed[e] = False
        cap, u_max = cap_ppm * (ONE // PPM), u_max_ppm * (ONE // PPM)
        base = base_weights(licensed, w, cap, u_max)
        self.entity_weight = w
        self.reputation = Reputation(base, G2Params(length))
        self.punishment = Punishment(base, cap, G1Params(length, l_max_ppm * (ONE // PPM)))
        self.origin = self.current = self.ledger = origin
        self.start = self.ledger_start = 0
        self.tables, self.first_rounds, self.terminals = {}, {origin: 0}, {}
        for e in (origin, origin + 1):
            self.tables[e] = self.make_table(e)
        self.handovers = []  # what each terminal block did, for the vectors

    # -- the table

    def split(self, stakes):
        split, left = [], list(stakes)
        for i, e in enumerate(self.entity_of):
            s = stakes[e] * self.stake[i] // max(self.entity_weight[e], 1)
            left[e] -= s
            split.append(s)
        for i, e in enumerate(self.entity_of):
            split[i] += left[e]
            left[e] = 0
        return split

    def make_table(self, epoch):
        z = self.punishment.z()
        stakes = self.split(table(self.punishment.base, self.reputation.r, z, self.reputation.p.b_rep))
        excluded, bars = self.reputation.excluded, self.punishment.bars()
        return {
            "epoch": epoch,
            "stake": stakes,
            "leader": [not excluded[e] and not bars[e] for e in self.entity_of],
            "handover": None,
        }

    # -- leaders

    def epoch_of_round(self, round_):
        return max(e for e, first in self.first_rounds.items() if first <= round_)

    def leader_of(self, round_, accused_in=None):
        epoch = accused_in if accused_in is not None else self.epoch_of_round(round_)
        return leader(self.tables[epoch], round_)

    # -- the ledger

    def after_terminal(self, block):
        return block["epoch"] < self.ledger

    def is_terminal(self, block):
        return block["epoch"] == self.ledger and block["round"] >= self.ledger_start + self.length

    def feed(self, block):
        """The next committed block in chain order. Returns True if it was the terminal block of its epoch."""
        if self.after_terminal(block):
            return False  # H4: off the ledger
        for round_, epoch in block.get("accusations", []):
            self.reputation.record(round_, epoch)
        for member, kind, sign_epoch in block.get("evidence", []):
            self.punishment.record(self.entity_of[member], kind != "E-NR", sign_epoch, block["epoch"])
        if self.is_terminal(block):
            self.enter_next(block)
            return True
        return False

    def enter_next(self, terminal):
        rep = self.reputation
        horizon = max(terminal["round"] + 1 - rep.p.lag, 0)
        rep.advance(horizon, lambda u, accused_in: self.entity_of[self.leader_of(u, accused_in)])
        target = self.ledger + 2
        self.punishment.update(target)
        self.tables[target] = self.make_table(target)
        self.handovers.append({
            "epoch": self.ledger,
            "terminal": terminal["round"],
            "done": rep.done,
            "g2_events": [list(x) for x in rep.log],
            "cusum": list(rep.cusum),
            "r_ppm": list(rep.r),
            "excluded": list(rep.excluded),
            "g1_events": [list(x) for x in self.punishment.log],
            "z": self.punishment.z(),
            "bars": self.punishment.bars(),
            "g1_queue": [q[0] for q in self.punishment.queue],
            "table": target,
        })
        # H3: enter the next epoch; its first round keeps the leader of the old table.
        nxt, first = self.current + 1, terminal["round"] + 2
        self.terminals[self.current] = terminal["round"]
        self.tables[nxt]["handover"] = (first, leader(self.tables[self.current], first))
        self.first_rounds[nxt] = first
        self.current, self.start = nxt, terminal["round"]
        self.ledger += 1
        self.ledger_start = terminal["round"]

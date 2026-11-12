"""Do the ledger replay vectors tell wrong implementations apart?

Each mutant changes one rule of the reference replay (replay_ref.py) the way an implementation that misread
SPEC.md might, replays the ledgers of consensus/src/tests/replay_vectors.json with it and reports which expected
results no longer match. Every mutant must be detected. Run from the repository root:
    python3 prototype/scripts/replay_mutants.py
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay_ref as R  # noqa: E402
import gen_replay_vectors as G  # noqa: E402

VEC = G.OUT
cases = json.load(open(VEC))
specs = {c["name"]: c for c in G.CASES}


def run():
    bad = []
    for case in cases:
        spec = dict(specs[case["name"]])
        try:
            rep, exp = G.expected(spec, case["blocks"])
        except Exception as e:  # noqa: BLE001
            bad.append("%s: crash %s" % (case["name"], type(e).__name__))
            continue
        exp = json.loads(json.dumps(exp))
        for key in ("entities", "base", "handovers", "tables", "leaders"):
            if exp[key] != case[key]:
                bad.append("%s: %s" % (case["name"], key))
    return bad


orig = {name: getattr(R, name) for name in ("draw", "G2Params", "G1Params", "base_weights")}
orig_feed, orig_split, orig_enter = R.Replay.feed, R.Replay.split, R.Replay.enter_next


def reset():
    for k, v in orig.items():
        setattr(R, k, v)
    R.Replay.feed, R.Replay.split, R.Replay.enter_next = orig_feed, orig_split, orig_enter


def m_suffix(self, block):  # counts the contents of blocks after a terminal block
    saved = self.ledger
    if block["epoch"] < self.ledger:
        self.ledger = block["epoch"]
        for round_, epoch in block.get("accusations", []):
            self.reputation.record(round_, epoch)
        for m, kind, s in block.get("evidence", []):
            self.punishment.record(self.entity_of[m], kind != "E-NR", s, block["epoch"])
        self.ledger = saved
        return False
    return orig_feed(self, block)


def m_draw8(epoch, round_):
    d = hashlib.sha512(epoch.to_bytes(8, "little") + round_.to_bytes(8, "little")).digest()
    return int.from_bytes(d[:8], "little")


def g2(**kw):
    class P(orig["G2Params"]):
        def __init__(self, length):
            super().__init__(length)
            for k, v in kw.items():
                setattr(self, k, v(self) if callable(v) else v)
    return P


def g1(**kw):
    class P(orig["G1Params"]):
        def __init__(self, length, l_max):
            super().__init__(length, l_max)
            for k, v in kw.items():
                setattr(self, k, v)
    return P


def m_split_last(self, stakes):
    split, left = [], list(stakes)
    for i, e in enumerate(self.entity_of):
        s = stakes[e] * self.stake[i] // max(self.entity_weight[e], 1)
        left[e] -= s
        split.append(s)
    for i in reversed(range(len(self.entity_of))):
        e = self.entity_of[i]
        split[i] += left[e]
        left[e] = 0
    return split


def m_base_no_nu(licensed, w, cap, u_max):
    total = sum(w)
    lic = [x for x, c in zip(w, licensed) if c]
    unc = [x for x, c in zip(w, licensed) if not c]
    u = min(sum(unc) * R.ONE // total, u_max)
    lw, uw = R.cap_normalize(lic, cap, R.ONE - u), R.cap_normalize(unc, cap, u)
    if lw is None or uw is None:
        raise ValueError("Cap")
    lw, uw = iter(lw), iter(uw)
    return [next(lw) if c else next(uw) for c in licensed]


def m_no_handover(self, terminal):
    orig_enter(self, terminal)
    self.tables[self.current]["handover"] = None


def m_one_ahead(self, terminal):  # the old handover: W_{e+1} computed at G_e
    rep = self.reputation
    horizon = max(terminal["round"] + 1 - rep.p.lag, 0)
    rep.advance(horizon, lambda u, a: self.entity_of[self.leader_of(u, a)])
    target = self.ledger + 1
    self.punishment.update(target)
    self.tables[target] = self.make_table(target)
    self.tables[target + 1] = self.make_table(target + 1)
    self.handovers.append({"epoch": self.ledger})
    nxt, first = self.current + 1, terminal["round"] + 2
    self.tables[nxt]["handover"] = (first, R.leader(self.tables[self.current], first))
    self.first_rounds[nxt] = first
    self.current, self.start = nxt, terminal["round"]
    self.ledger += 1
    self.ledger_start = terminal["round"]


MUTANTS = [
    ("后缀块内容计入", lambda: setattr(R.Replay, "feed", m_suffix)),
    ("不留滞后（lag 0）", lambda: setattr(R, "G2Params", g2(lag=0))),
    ("滞后取 5", lambda: setattr(R, "G2Params", g2(lag=5))),
    ("纪元号按 8 字节编码", lambda: setattr(R, "draw", m_draw8)),
    ("恢复按每纪元 0.02（未折算）", lambda: setattr(R, "G2Params", g2(recover=20_000))),
    ("G1 签名窗口未折算（1 个纪元）", lambda: setattr(R, "G1Params", g1(sign_window=1))),
    ("L1 时长未折算（1 个纪元）", lambda: setattr(R, "G1Params", g1(lead_bar=1))),
    ("L2 时长未折算（4 个纪元）", lambda: setattr(R, "G1Params", g1(suspend_l2=4))),
    ("排除期 400 个视图", lambda: setattr(R, "G2Params", g2(exclusion=400))),
    ("排除上限 40%", lambda: setattr(R, "G2Params", g2(cap=R.ONE * 2 // 5))),
    ("成员余数归最后一个成员", lambda: setattr(R.Replay, "split", m_split_last)),
    ("U 不取 n_U·cap", lambda: setattr(R, "base_weights", m_base_no_nu)),
    ("新纪元首视图不保留旧领导者", lambda: setattr(R.Replay, "enter_next", m_no_handover)),
    ("下一张表在 G_e 才算（只提前一个纪元）", lambda: setattr(R.Replay, "enter_next", m_one_ahead)),
]


def main():
    base = run()
    print("unmutated:", "; ".join(base) if base else "matches")
    missed = 0
    for name, apply in MUTANTS:
        reset()
        apply()
        bad = run()
        missed += not bad
        print("%s\t%s" % (name, "; ".join(bad) if bad else "NOT DETECTED"))
    reset()
    print("%d of %d mutants detected" % (len(MUTANTS) - missed, len(MUTANTS)))
    sys.exit(1 if base or missed else 0)


if __name__ == "__main__":
    main()

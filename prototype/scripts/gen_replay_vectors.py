"""Ledger replay vectors: short committed ledgers and the weight tables every node must derive from them.

GPT review v9, Q2: the CapNorm, G1 and G2 vectors check one module each; these check the whole path from the
ledger to the tables, as SPEC.md states it. Each case is a scripted run: some members stay silent as leaders (no
block, an AT accusation of the round on the ledger), some rounds time out without an accusation, G1 evidence is
put on the ledger, and a few blocks carry what the rules must ignore (a late accusation, the contents of a block
after a terminal block). The ledger is built round by round with the reference replay (replay_ref.py), since who
leads depends on the tables, and then replayed from scratch to record what is expected:

- the terminal block of each epoch, and at each one the rounds processed, the G2 and G1 events, the CUSUM
  statistics, reputations, exclusions, suspensions, bars and the G1 queue;
- every weight table W_e (integer stakes, who may lead, the leader of the first round);
- the leader of every round.

The prototype replays the same blocks through `Epochs` (consensus/src/tests/replay_tests.rs) and must match all
of it exactly. Run from the repository root:  python3 prototype/scripts/gen_replay_vectors.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import replay_ref as R  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "consensus", "src", "tests", "replay_vectors.json")


def member(stake, certified=True, entity=None):
    return dict(stake=stake, certified=certified, entity=entity)


CASES = [
    dict(
        name="small-committee",
        description=(
            "Seven members in key order: an entity of two licensed members (30 + 10), licensed members of 25, 20 "
            "and 15, an uncertified member of 10 and a licensed member of weight 0; cap 25%, u_max 25%, L_max 25%. "
            "Members 3, 0 and 2 stay silent as leaders in turn, members 3 and 0 twice: convictions, the 50% "
            "exclusion cap (convictions without room discarded, then a later one excluded), releases, recovery "
            "and the budget. Member 4 has "
            "an NR self-contradiction twice in one sign window, then again (L1, then L2 by repeat); member 5 a "
            "double vote (L2), so that L_max queues member 4 until member 5 is released. Round 25 times out "
            "without an accusation, so the first terminal block is later."
        ),
        roster=[member(30, entity=1), member(10, entity=1), member(25), member(20), member(15),
                member(10, certified=False), member(0)],
        length=25, cap_ppm=250_000, u_max_ppm=250_000, l_max_ppm=250_000,
        rounds=1400,
        silent=[(3, 5, 120, 1), (0, 200, 300, 1), (2, 330, 560, 1), (3, 600, 760, 1), (0, 800, 1100, 1),
                (2, 1030, 1300, 1)],
        quiet=[25, 140, 141],
        evidence=[(30, 4, "E-NR", 0), (55, 4, "E-NR", 0), (130, 4, "E-NR", 0), (105, 5, "E1", 0)],
        late=[160, 470],
        suffix_junk=[(3, 2), (8, 4)],
    ),
    dict(
        name="default-caps",
        description=(
            "Twenty-three members in key order with the default caps (cap 5%, u_max 25%, L_max 10%): eighteen "
            "licensed members of their own, one licensed entity of two members, two uncertified members whose "
            "share is held to n_U * cap = 10%, and an uncertified member of weight 0. Member 0 stays silent and "
            "is convicted; member 5 fails one lead in three and is not. Members 3, 4 and 6 double-vote in one "
            "epoch: their correlated share is above the cap, so L3, and L_max queues the third. Member 10 has an "
            "NR self-contradiction (L1)."
        ),
        roster=[member(w) for w in [120, 80, 60, 50, 50, 45, 40, 40, 35, 30, 30, 30, 25, 25, 20, 20, 15]]
        + [member(15, entity=7), member(10, entity=7), member(60, certified=False), member(40, certified=False),
           member(0, certified=False), member(10)],
        length=25, cap_ppm=50_000, u_max_ppm=250_000, l_max_ppm=100_000,
        rounds=340,
        silent=[(0, 10, 150, 1), (5, 1, 340, 3)],
        quiet=[50, 51],
        evidence=[(40, 10, "E-NR", 0), (60, 3, "E1", 0), (61, 4, "E1", 0), (62, 6, "E1", 0)],
        late=[200],
        suffix_junk=[(2, 1)],
    ),
]


def generate(case):
    """Build the ledger round by round, deciding each round from its leader."""
    rep = R.Replay(case["roster"], case["length"], case["cap_ppm"], case["u_max_ppm"], case["l_max_ppm"])
    blocks, pending, evidence = [], [], sorted(case["evidence"])
    leads = {}  # member -> leads in its silent window so far
    junk = dict(case["suffix_junk"])  # epoch -> member framed by a double vote in that epoch's suffix block
    late = list(case["late"])
    checks = {"late_dropped": 0, "lag_kept": 0, "suffix_ignored": 0}
    for u in range(1, case["rounds"] + 1):
        epoch = rep.epoch_of_round(u)
        lead = rep.leader_of(u)
        suffix = rep.current > rep.origin and u == rep.start + 1
        if suffix:
            # H4: the child of the terminal block, of the old epoch: it carries the commit proof and is not on
            # the ledger. Honest leaders propose it empty; here some carry what must be ignored.
            block = {"round": u, "epoch": rep.current - 1}
            e = rep.current - 1
            if e in junk:
                block["accusations"] = [[u - 1, e]]
                block["evidence"] = [[junk[e], "E1", e]]
                checks["suffix_ignored"] += 1
            assert rep.after_terminal(block)
            blocks.append(block)
            rep.feed(block)
            continue
        silent = False
        for m, a, b, every in case["silent"]:
            if m == lead and a <= u <= b:
                leads[(m, a)] = leads.get((m, a), 0) + 1
                silent = leads[(m, a)] % every == 0
        if silent:
            pending.append([u, epoch])  # an AT accusation of the round, on the next block
            continue
        if u in case["quiet"]:
            continue  # a timeout without an accusation: no block, no fact
        block = {"round": u, "epoch": epoch}
        accusations = [a for a in pending]
        pending = []
        while late and late[0] <= u:
            late.pop(0)
            # A late fact: an accusation of the last round already processed (dropped), and one of the next round
            # (just in time). Both rounds had a block: the accusations frame their leaders.
            done = rep.reputation.done
            accusations += [[done, rep.epoch_of_round(done)], [done + 1, rep.epoch_of_round(done + 1)]]
            checks["late_dropped"] += 1
        if accusations:
            block["accusations"] = accusations
        carried = []
        while evidence and evidence[0][0] <= u:
            _, m, kind, back = evidence.pop(0)
            carried.append([m, kind, epoch - back])
        if carried:
            block["evidence"] = carried
        blocks.append(block)
        before = rep.reputation.done
        terminal = rep.feed(block)
        if terminal:
            # The lag: facts of the last rounds before the terminal block wait for the next one.
            checks["lag_kept"] += sum(1 for r in rep.reputation.accused if r > before)
    assert not late and not evidence, "scripted events left over"
    return blocks, checks


def expected(case, blocks):
    rep = R.Replay(case["roster"], case["length"], case["cap_ppm"], case["u_max_ppm"], case["l_max_ppm"])
    for block in blocks:
        rep.feed(block)
    last = blocks[-1]["round"]
    tables = [dict(rep.tables[e], handover=list(rep.tables[e]["handover"]) if rep.tables[e]["handover"] else None)
              for e in sorted(rep.tables)]
    return rep, {
        "entities": rep.entity_of,
        "base": [str(b) for b in rep.reputation.base],
        "handovers": rep.handovers,
        "tables": tables,
        "leaders": [rep.leader_of(u) for u in range(1, last + 1)],
    }


def summary(case, rep, checks):
    events = [(h["epoch"], x) for h in rep.handovers for x in h["g2_events"] + h["g1_events"]]
    kinds = {}
    for _, x in events:
        kinds[x[0]] = kinds.get(x[0], 0) + 1
    budget = 0
    for h in rep.handovers:
        cut = sum(b * (R.PPM - r) // R.PPM for b, r in zip(rep.reputation.base, h["r_ppm"]))
        budget += cut > rep.reputation.p.b_rep
    print("%s: %d blocks, %d terminal blocks, events %s, budget binding at %d handovers, checks %s, r_min reached %s"
          % (case["name"], len(case["blocks"]), len(rep.handovers), kinds, budget, checks,
             any(min(h["r_ppm"]) == rep.reputation.p.r_min for h in rep.handovers)))


def dump(cases):
    """One line per block, handover and table, so that a change shows in a diff."""
    def line(x):
        return json.dumps(x, separators=(",", ":"))

    out = ["["]
    for ci, case in enumerate(cases):
        out.append(" {")
        keys = list(case)
        for ki, key in enumerate(keys):
            end = "," if ki + 1 < len(keys) else ""
            value = case[key]
            if key in ("blocks", "handovers", "tables", "roster"):
                out.append("  %s: [" % json.dumps(key))
                for i, x in enumerate(value):
                    out.append("   " + line(x) + ("," if i + 1 < len(value) else ""))
                out.append("  ]" + end)
            else:
                out.append("  %s: %s%s" % (json.dumps(key), line(value), end))
        out.append(" }" + ("," if ci + 1 < len(cases) else ""))
    out.append("]")
    return "\n".join(out) + "\n"


def main():
    cases = []
    for spec in CASES:
        blocks, checks = generate(spec)
        rep, exp = expected(spec, blocks)
        case = {k: spec[k] for k in ("name", "description", "roster", "length", "cap_ppm", "u_max_ppm", "l_max_ppm")}
        case.update(reference_length=R.REFERENCE_LENGTH, origin=0, blocks=blocks)
        case.update(exp)
        summary(case, rep, checks)
        cases.append(case)
    with open(OUT, "w") as f:
        f.write(dump(cases))
    print("wrote", os.path.normpath(OUT))


if __name__ == "__main__":
    main()

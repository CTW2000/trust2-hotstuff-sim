"""Direction A checks: vote-carrying timeouts (QC reconstruction from timeouts).
Run from the repository root:  python -m sim2.tests.test_dirA"""
import sys
import time

import numpy as np

from sim2 import adversary as A
from sim2 import engine_event, engine_fast
from sim2 import schedule as S
from sim2.common import RunConfig, State
from sim2.net import NetConfig, Network
from sim2.tests.test_m2 import compare


def main():
    failures = 0
    t0 = time.time()
    stats = {"ok": 0, "bad": 0}
    advs = [A.CollectorFraming(omit_tmo_votes=True), A.CollectorFraming(omit_tmo_votes=False),
            A.Compose([A.CollectorFraming(), A.LieNR()]), A.WithholdVotesOnHonest(), A.PartialSend(1)]
    nets = {"3reg": dict(regions=3, jitter_max_ms=2.0), "P05": dict(regions=3, jitter_max_ms=2.0, eps_late=0.05),
            "P15": dict(regions=3, jitter_max_ms=2.0, eps_late=0.15, late_extra_ms=400.0)}
    via = 0
    for proto in ("P1", "P2"):
        for adv in advs:
            for nname, p in nets.items():
                for seed in range(2):
                    for rule in (None, S.CusumExclusion(evidence="failed", rho_bar=0.05, D=100)):
                        tau = 250.0 if nname == "P15" else 2000.0
                        cfg = RunConfig(n=10, views=200, seed=seed, protocol=proto, leader_rule=rule,
                                        leader_mode="random", byzantine=[7, 8, 9], adversary=adv,
                                        timeout_votes=True, tau_ms=tau)
                        d, rf = compare(cfg, Network(NetConfig(n=10, seed=seed, **p)))
                        via += int(rf.qc_via_tmo.sum())
                        stats["ok" if not d else "bad"] += 1
                        if d:
                            failures += 1
                            if stats["bad"] <= 8:
                                print(f"[MISMATCH] {proto} {adv.name} {nname} seed={seed} "
                                      f"{rule.name if rule else 'static'}: {d}")
    print(f"timeout-votes runs (fast engine delegates to the reference engine): {stats}, "
          f"QCs reconstructed from timeouts: {via} ({time.time() - t0:.0f}s)")
    if via == 0:
        failures += 1
    # semantics checks on the reference engine
    n, byz = 31, list(range(21, 31))
    net = Network(NetConfig(n=n, seed=3, regions=3, jitter_max_ms=2.0))
    for omit, expect in ((True, "framing defeated (colluders omit their votes)"), (False, "framing defeated")):
        r = engine_fast.run(RunConfig(n=n, views=1500, seed=3, protocol="P1", leader_rule=S.Uniform(), byzantine=byz,
                                      adversary=A.CollectorFraming(omit_tmo_votes=omit), timeout_votes=True), net)
        hv = [u for u in range(1, 1490) if r.honest[r.leaders[u]]]
        framed = [u for u in hv if r.byz[r.leaders[u + 1]]] if hasattr(r, "byz") else \
            [u for u in hv if r.roles[r.leaders[u + 1]] == 2]
        fail = np.mean([not S.succeeded(r.prop_parent, u, 1500) for u in framed])
        rec = np.mean([r.qc_via_tmo[u] for u in framed])
        print(f"P1 collector framing, model S, timeout votes, omit={omit}: honest leaders with a colluding collector: "
              f"orphaned {fail:.3f} (the Jolteon TC rule still lets the collector orphan the block), "
              f"QC reconstructed from timeouts {rec:.3f} -> leader exonerated, collector blamed")
        if rec < 1:
            failures += 1
    failures += v02_checks()
    if failures:
        print(f"FAILED: {failures}")
        sys.exit(1)
    print("ALL DIRECTION-A CHECKS PASSED")


def _charges(r, views, tau):
    """(honest leader charged | colluding collector, honest collector blamed | colluding leader,
    colluding leader charged | honest collector) under rec_tau evidence."""
    hl, hc, bl = [], [], []
    for u in range(1, views - 10):
        L, C = r.leaders[u], r.leaders[u + 1]
        failed = not S.succeeded(r.prop_parent, u, views)
        rc = r.tmo_votes[u] >= tau
        if r.honest[L] and r.roles[C] == 2:
            hl.append(failed and not rc)
        if r.roles[L] == 2 and r.honest[C]:
            hc.append(failed and rc)
            bl.append(failed and not rc)
    return np.mean(hl), np.mean(hc), np.mean(bl)


def v02_checks():
    """方向A v0.2: counterexample A2' at tau = q, the identifiability threshold tau = q + floor(f/2)
    (theorem A4: both sides correct iff f0 <= floor(f/2), model S), and the leave rule."""
    bad = 0
    n, views = 31, 600
    q, t = 21, 5
    net = Network(NetConfig(n=n, seed=5, regions=3, jitter_max_ms=2.0))
    for f0 in (5, 6):
        adv = A.Compose([A.CollectorFraming(omit_tmo_votes=True), A.PartialFrameCollector()])
        r = engine_fast.run(RunConfig(n=n, views=views, seed=5, protocol="P1", leader_rule=S.Uniform(),
                                      byzantine=list(range(n - f0, n)), adversary=adv, timeout_votes=True), net)
        lo = _charges(r, views, q)
        hi = _charges(r, views, q + t)
        print(f"v0.2 f0={f0}: tau=q   (honest leader charged, honest collector blamed, colluding leader charged) "
              f"= {tuple(round(x, 3) for x in lo)}; tau=q+f/2: {tuple(round(x, 3) for x in hi)}")
        if lo != (0.0, 1.0, 0.0):
            bad += 1                                  # A2': the honest collector is framed at tau = q
        expect = (0.0, 0.0, 1.0) if f0 <= t else (1.0, 1.0, 0.0)
        if hi != expect:
            bad += 1                                  # A4: identifiable iff f0 <= floor(f/2)
    # v0.4: the late-proposal framing of an honest collector (review v0.3 S1) defeats every tau without
    # the collector's TC-wait rule; with it the block is rescued. A4 (A2') still holds with the rule.
    for f0 in (1, 5):
        byzl = list(range(n - f0, n))
        for wait in (False, True):
            netl = Network(NetConfig(n=n, seed=5, regions=3, jitter_max_ms=2.0))
            W = netl.delta_fwd() + netl.delta_max() if wait else None
            r = engine_fast.run(RunConfig(n=n, views=views, seed=5, protocol="P1", leader_rule=S.Uniform(),
                                          byzantine=byzl, adversary=A.LateProposalFramer(), timeout_votes=True,
                                          tc_wait_ms=W), netl)
            att = [u for u in range(1, views - 10) if r.roles[r.leaders[u]] == 2 and r.honest[r.leaders[u + 1]]]
            orph = np.mean([not S.succeeded(r.prop_parent, u, views) for u in att])
            blamed = np.mean([(not S.succeeded(r.prop_parent, u, views)) and r.tmo_votes[u] >= q + t for u in att])
            print(f"v0.4 late proposal f0={f0} wait={wait}: attacked views {len(att)}, orphaned {orph:.3f}, "
                  f"honest collector blamed at tau=q+f/2 {blamed:.3f}")
            if (wait and orph != 0.0) or (not wait and blamed != 1.0):
                bad += 1
    for f0 in (5, 6):
        netw = Network(NetConfig(n=n, seed=5, regions=3, jitter_max_ms=2.0))
        adv = A.Compose([A.CollectorFraming(omit_tmo_votes=True), A.PartialFrameCollector()])
        r = engine_fast.run(RunConfig(n=n, views=views, seed=5, protocol="P1", leader_rule=S.Uniform(),
                                      byzantine=list(range(n - f0, n)), adversary=adv, timeout_votes=True,
                                      tc_wait_ms=netw.delta_fwd() + netw.delta_max()), netw)
        hi = _charges(r, views, q + t)
        print(f"v0.4 wait rule, f0={f0}, tau=q+f/2: {tuple(round(x, 3) for x in hi)}")
        if hi != ((0.0, 0.0, 1.0) if f0 <= t else (1.0, 1.0, 0.0)):
            bad += 1
    # leave rule (review A-3). With certificate forwarding, honest entries into a view are synchronised
    # within the honest delays, so in the stock network an honest voter is never overtaken by a
    # forwarded TC before its own timeout fires. Force it: in one view w with an honest leader and a
    # colluding collector, the proposal and the entry certificate reach honest replica k 1000 ms late,
    # so k votes late and then learns TC(w) before its own timer (tau after its late entry) fires.
    n, byz = 10, [7, 8, 9]
    base = Network(NetConfig(n=n, seed=2, regions=3, jitter_max_ms=2.0))
    cfg0 = RunConfig(n=n, views=60, seed=2, protocol="P1", leader_rule=S.Uniform(), byzantine=byz,
                     adversary=A.CollectorFraming(), timeout_votes=True)
    r0 = engine_fast.run(cfg0, base)
    w = next(u for u in range(20, 50) if r0.honest[r0.leaders[u]] and r0.roles[r0.leaders[u + 1]] == 2)
    k = next(j for j in range(n) if r0.honest[j] and j != r0.leaders[w])

    class LateEntry:
        def __init__(self, net):
            self.net, self.cfg = net, net.cfg

        def delays(self, v, mtype):
            d = self.net.delays(v, mtype)
            if v == w and mtype in ("prop", "fwd"):
                d = d.copy()
                d[:, k] += 1000.0
            return d

    got = {}
    for leave in (False, True):
        cfg = RunConfig(n=n, views=60, seed=2, protocol="P1", leader_rule=S.Uniform(), byzantine=byz,
                        adversary=A.CollectorFraming(), timeout_votes=True, tmo_after_leave=leave)
        st = State(cfg)
        engine_event.simulate(cfg, LateEntry(base), st, 1, cfg.views)
        got[leave] = (int(st.tmo_votes[w]), st.leave_tmo_sent)
    print(f"v0.2 leave rule (view {w}, late replica {k}): carried votes / leave-rule sends without the rule "
          f"{got[False]}, with it {got[True]}")
    if not (got[True][0] == got[False][0] + 1 and got[True][1] >= 1 and got[False][1] == 0):
        bad += 1
    return bad


if __name__ == "__main__":
    main()

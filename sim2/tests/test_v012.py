"""Checks for the v0.12 scheme (信任2.0_方案重构说明 v0.12 §3.3): formula A base weights, graded G1
punishment (punish.GradedPunishment) and the AT exclusion doubling of CusumExclusion.
- formula A: base_weights(..., K=0) respects the entity cap and the class cap u_max;
- an isolated safety item gives L2 (4-epoch suspension), a repeat L3, a second repeat L4; with malicious
  evidence the entity is evicted after the governance delay and only zeroed (no CapNorm recomputation);
  without it governance downgrades to L3 and the entity is suspended for 32 epochs, not evicted;
- items of one sign epoch above the cap give L3 to every entity of the group (late evidence upgrades);
- a client fault above 1/3 (malicious = False, no fork) is downgraded to L2 by governance and suspended
  through the FIFO queue without the suspended base share ever exceeding l_max; queued entities are barred
  from leading;
- a fork with culprits above 1/3 evicts them all; an infeasible CapNorm relaxes the entity cap to the
  smallest feasible value, so the class cap still holds;
- protocol run with greedy NR liars: liars climb L1 -> L2 -> L3, no honest replica is punished, the
  suspended share stays <= l_max and the colluder share stays below beta0 / (1 - B_rep);
- AT doubling: the m-th hard exclusion of a silent leader within the lookback lasts D * min(2**m, 8).
Run from the repository root:  python -m sim2.tests.test_v012   (or pytest: test_v012)"""
import numpy as np

from sim2 import adversary as A
from sim2 import engine_event
from sim2 import schedule as S
from sim2 import ttru
from sim2.common import RunConfig, State
from sim2.net import NetConfig, Network
from sim2.punish import GradedPunishment

CAP, UMAX = 0.10, 0.25


def pop(seed=0):
    return ttru.population(10, 12, 9, seed)


def drive(p, epochs):
    zs, bases = [], []
    for k in range(1, epochs + 1):
        z, b = p.update(None, k, 0)
        zs.append(z)
        bases.append(b)
    return zs, bases


def events(p, i):
    return [(ev, k) for ev, j, k in p.log if j == i]


def check_formula_a():
    for seed in range(20):
        cls, s = pop(seed)
        b = ttru.base_weights(cls, s, 0.0, 0.0, CAP, UMAX)
        assert abs(b.sum() - 1) < 1e-9 and b.max() <= CAP + 1e-9
        assert b[cls != "L"].sum() <= UMAX + 1e-9
    print("formula A: entity cap and class cap hold (20 populations)")


def check_isolated_repeat_evict():
    cls, s = pop()
    p0 = GradedPunishment(cls, s, CAP, UMAX, liveness=False)
    i = int(np.argmin(p0.base))
    inj = [(i, 1, 1, True), (i, 10, 10, True), (i, 50, 50, True)]
    p = GradedPunishment(cls, s, CAP, UMAX, liveness=False, injected=inj, win_chain=4)
    zs, bases = drive(p, 60)
    ev = events(p, i)
    assert ("L2", 2) in ev and ("suspend", 2) in ev and ("release", 6) in ev, ev
    assert all(zs[k - 1][i] == 0 for k in range(2, 6)) and zs[6 - 1][i] == 1
    assert ("L3", 11) in ev and ("release", 43) in ev, ev           # repeat: L3, 32 epochs
    assert ("L4", 51) in ev and ("evict", 53) in ev, ev             # second repeat: L4, evicted after 2 epochs
    assert bases[-1][i] == 0 and abs(bases[-1].sum() - (1 - p0.base[i])) < 1e-9 and not p.infeasible
    assert all(abs(bases[-1][j] - p0.base[j]) < 1e-12 for j in range(len(cls)) if j != i)
    print("isolated -> L2 (4 epochs), repeat -> L3 (32), second repeat -> L4 and eviction; the evicted weight is "
          "zeroed, not redistributed by CapNorm")


def check_repeat_downgrade():
    cls, s = pop()
    p0 = GradedPunishment(cls, s, CAP, UMAX, liveness=False)
    i = int(np.argmin(p0.base))
    inj = [(i, 1, 1, False), (i, 10, 10, False), (i, 50, 50, False)]
    p = GradedPunishment(cls, s, CAP, UMAX, liveness=False, injected=inj, win_chain=4)
    zs, bases = drive(p, 90)
    ev = events(p, i)
    assert ("L4", 51) in ev and ("downgrade", 53) in ev and ("suspend", 53) in ev and ("release", 85) in ev, ev
    assert not p.evicted.any() and abs(bases[-1].sum() - 1) < 1e-9 and zs[-1][i] == 1
    old = GradedPunishment(cls, s, CAP, UMAX, liveness=False, injected=inj, win_chain=4, repeat_evict=True)
    drive(old, 60)
    assert ("evict", 53) in events(old, i)
    print("non-malicious second repeat: L4, governance downgrades to L3 (32 epochs), not evicted "
          "(repeat_evict=True restores the eviction)")


def check_correlated_upgrade():
    cls, s = pop()
    p0 = GradedPunishment(cls, s, CAP, UMAX, liveness=False)
    order = np.argsort(p0.base)[::-1]
    a, b = int(order[0]), int(order[1])                     # two capped entities: 0.2 > cap
    p = GradedPunishment(cls, s, CAP, UMAX, liveness=False, injected=[(a, 3, 3, True), (b, 3, 6, True)])
    drive(p, 10)
    assert ("L2", 4) in events(p, a) and ("L3", 7) in events(p, a), events(p, a)   # late evidence upgrades a
    assert ("L3", 7) in events(p, b), events(p, b)
    print("same sign epoch above the cap: both L3, the earlier one upgraded by late evidence")


def check_bug_queue():
    cls, s = pop()
    p0 = GradedPunishment(cls, s, CAP, UMAX, liveness=False)
    order = np.argsort(p0.base)[::-1]
    group, acc = [], 0.0
    for i in order:
        if acc > 0.40:
            break
        group.append(int(i))
        acc += p0.base[i]
    p = GradedPunishment(cls, s, CAP, UMAX, liveness=False, injected=[(i, 5, 5, False) for i in group])
    seen_queue = False
    for k in range(1, 81):
        p.update(None, k, 0)
        for q in p.queue:
            assert p.bars(k)[q[0]], (k, q)
            seen_queue = True
    assert seen_queue
    assert all(("L4", 6) in events(p, i) and ("downgrade", 8) in events(p, i) for i in group)
    assert not p.evicted.any()
    assert max(h[0] for h in p.history) <= p.l_max + 1e-9
    assert all(any(e == "suspend" for e, _ in events(p, i)) for i in group)
    print(f"client fault on {acc:.2f} of the weight: governance downgrades to L2; suspended share max "
          f"{max(h[0] for h in p.history):.3f} <= {p.l_max}; all {len(group)} served by the queue "
          f"(longest wait {p.max_wait} epochs), barred from leading while queued")


def check_fork_infeasible():
    cls, s = pop()
    p0 = GradedPunishment(cls, s, CAP, UMAX, liveness=False)
    lic = [int(i) for i in np.flatnonzero(cls == "L")][:4]   # 4 x 0.075..0.1 > 1/3 of base
    assert p0.base[lic].sum() > 1 / 3
    p = GradedPunishment(cls, s, CAP, UMAX, liveness=False, forks=[(lic, 4)])
    zs, bases = drive(p, 10)
    assert all(("evict", 7) in events(p, i) for i in lic)
    b = bases[-1]
    assert p.infeasible and all(b[i] == 0 for i in lic)           # 6 licensed x 0.10 < 0.75
    assert abs(b.sum() - 1) < 1e-9 and b[cls != "L"].sum() <= UMAX + 1e-9 and p.cap_used > CAP
    assert abs(b[cls == "L"].max() - p.cap_used) < 1e-9
    print(f"fork with 4 licensed culprits (> 1/3): all evicted after the governance delay; CapNorm infeasible "
          f"(6 x 0.10 < 0.75): entity cap relaxed to {p.cap_used:.3f}, uncertified share {b[cls != 'L'].sum():.3f}")


def check_protocol_liars():
    seed, views = 3, 1500
    cls, s = pop(seed)
    p = GradedPunishment(cls, s, CAP, UMAX)
    base = p.base.copy()
    byz = np.zeros(len(cls), bool)
    for i in np.argsort(s / base):
        if base[byz].sum() >= 0.2:
            break
        byz[i] = True
    rule = S.CusumExclusion(q=0.5, evidence="at", rho_bar=0.1, D=500, cap=0.5, Wq=500, cap_weights=base)
    vw = ttru.TtruWeights(base, epoch=100, rule=rule, punish=p)
    rule.bars = vw.bars
    cfg = RunConfig(n=len(cls), views=views, seed=seed, protocol="P2", leader_rule=rule,
                    byzantine=list(np.flatnonzero(byz)), adversary=A.LieNRVote(greedy=1.0), vote_weights=vw,
                    at_share=2 / 3, track_signed=True, nr_requires_data=True, vote_monotone=True)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=len(cls), seed=seed, regions=3, jitter_max_ms=2.0)), st, 1, views)
    vw(st, views)
    p = vw.punisher(st)
    punished = {j for ev, j, _ in p.log if ev.startswith("L")}
    assert punished and all(byz[j] for j in punished), punished
    levels = {lvl for ev, j, _ in p.log for lvl in [ev] if ev.startswith("L")}
    assert {"L1", "L2", "L3"} <= levels, levels
    assert max(h[0] for h in p.history) <= p.l_max + 1e-9
    tables = st.__dict__["_ttru_cache"][id(vw)]["tables"]
    b0 = base[byz].sum()
    assert max(t[byz].sum() for t in tables) <= b0 / (1 - 0.10) + 1e-9
    for v in range(1, views - 5):
        L = st.leaders[v]
        assert L < 0 or not vw.bars(st, v)[L], v
    assert S.verify_leaders(st, cfg) == 0
    print(f"protocol run, greedy NR liars: {len(punished)} colluders punished (L1..L3), 0 honest; suspended "
          f"share max {max(h[0] for h in p.history):.3f}; colluder share {b0:.3f} -> {tables[-1][byz].sum():.3f}; "
          f"no barred leader drawn; leaders recomputed from final facts")


def check_at_doubling():
    seed, views = 5, 9000
    cls, s = pop(seed)
    base = ttru.base_weights(cls, s, 0.0, 0.0, CAP, UMAX)
    byz = np.zeros(len(cls), bool)
    byz[int(np.argmax(base))] = True
    rule = S.CusumExclusion(q=0.5, evidence="at", rho_bar=0.1, D=500, cap=0.5, Wq=500, cap_weights=base, double=True)
    vw = ttru.TtruWeights(base, epoch=100, rule=rule)
    cfg = RunConfig(n=len(cls), views=views, seed=seed, protocol="P2", leader_rule=rule,
                    byzantine=list(np.flatnonzero(byz)), adversary=A.SilentLeader(1.0), vote_weights=vw,
                    at_share=2 / 3, nr_requires_data=True, vote_monotone=True)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=len(cls), seed=seed, regions=3, jitter_max_ms=2.0)), st, 1, views)
    k = int(np.flatnonzero(byz)[0])
    ex = [u for ev, j, u in st.rule_log if ev == "exclude" and j == k]
    rel = [u for ev, j, u in st.rule_log if ev == "release" and j == k]
    durs = [r - e for e, r in zip(ex, rel)]
    assert len(durs) >= 3, (ex, rel)
    for m, d in enumerate(durs):
        prior = sum(1 for x in ex[:m] if x >= ex[m] - 6400)
        assert d == 500 * min(2 ** prior, 8), (m, d, ex, rel)
    print(f"AT doubling: exclusion lengths of a silent leader {durs}")


def main():
    check_formula_a()
    check_isolated_repeat_evict()
    check_repeat_downgrade()
    check_correlated_upgrade()
    check_bug_queue()
    check_fork_infeasible()
    check_protocol_liars()
    check_at_doubling()
    print("ALL v0.12 CHECKS PASSED")


def test_v012():
    main()


if __name__ == "__main__":
    main()

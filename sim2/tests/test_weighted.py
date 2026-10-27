"""Weighted voting (T_tru) checks:
- equal shares reproduce counting exactly (event engine, several protocols, adversaries, networks;
  n = 10, not a multiple of 3, so "share > 2/3" and "q votes" coincide);
- liveness flips at a crashed share of 1/3 (quorum = share strictly above 2/3), tested at +-1e-4;
- reputation budget in the closed loop with the scaling branch exercised (b_rep small): the removed
  weight never exceeds b_rep and the colluder share stays below base / (1 - b_rep);
- leaders come from final facts (schedule.verify_leaders == 0) in weighted runs;
- targeted partial send (known property, 信任2.0_协议级验证 §3): with the AT threshold at 2/3 one
  heavy honest recipient evades AT when its share exceeds 1/3 - beta; with the threshold at 1/2 the
  same leader is accused.
Run from the repository root:  python -m sim2.tests.test_weighted   (or pytest: test_weighted)"""
import sys
import time

import numpy as np

from sim2 import adversary as A
from sim2 import engine_event
from sim2 import schedule as S
from sim2 import ttru
from sim2.common import RunConfig
from sim2.net import NetConfig, Network


def same(a, b):
    return (np.array_equal(a.know, b.know) and np.array_equal(a.qc_exists, b.qc_exists)
            and np.array_equal(a.leaders, b.leaders) and np.array_equal(a.prop_parent, b.prop_parent)
            and np.array_equal(a.nr_count, b.nr_count))


def main():
    bad = 0
    t0 = time.time()
    runs = 0
    nets = {"S": dict(regions=3, jitter_max_ms=2.0), "P05": dict(regions=3, jitter_max_ms=2.0, eps_late=0.05),
            "async": dict(regions=3, jitter_max_ms=2.0, async_views=60, async_p=0.5, async_extra_ms=3000.0)}
    for proto in ("P2", "P1"):
        for nname, p in nets.items():
            for adv in (None, A.WithholdVotesOnHonest(), A.PartialSend(2), A.CollectorFraming(), A.LieNR(),
                        A.SilentLeader(0.5)):
                for rule in (S.Uniform(), S.CusumExclusion(evidence="at", rho_bar=0.05, D=100, cap=0.5)):
                    n = 10
                    kw = dict(n=n, views=250, seed=runs % 3, protocol=proto, leader_rule=rule, byzantine=[7, 8, 9],
                              adversary=adv)
                    net = Network(NetConfig(n=n, seed=runs % 3, **p))
                    a = engine_event.run(RunConfig(**kw), net)
                    rule2 = S.Uniform() if isinstance(rule, S.Uniform) else S.CusumExclusion(
                        evidence="at", rho_bar=0.05, D=100, cap=0.5)
                    kw["leader_rule"] = rule2
                    b = engine_event.run(RunConfig(vote_weights=lambda st, v: np.full(n, 1.0 / n), **kw), net)
                    runs += 1
                    if not same(a, b):
                        bad += 1
                        if bad <= 5:
                            print(f"[MISMATCH] {proto} {nname} {getattr(adv, 'name', None)} {rule.name}")
    print(f"equal shares reproduce counting: {runs - bad}/{runs} runs identical ({time.time() - t0:.0f}s)")
    # liveness flips at a crashed share of 1/3: 3 crashed replicas share x, the other 28 share 1 - x
    n = 31
    for x, expect_live in ((1 / 3 - 1e-4, True), (1 / 3 + 1e-4, False)):
        w = np.r_[np.full(3, x / 3), np.full(n - 3, (1 - x) / (n - 3))]
        cfg = RunConfig(n=n, views=60, seed=1, protocol="P2", leader_rule=S.Uniform(), crashed=[0, 1, 2],
                        vote_weights=lambda st, v, w=w: w)
        r = engine_event.run(cfg, Network(NetConfig(n=n, seed=1, regions=3, jitter_max_ms=2.0)))
        live = bool(r.qc_exists[1:50].any())
        print(f"crashed share {x:.5f} (threshold 1/3): progress {live}")
        if live != expect_live:
            bad += 1
    # reputation budget in the closed loop: framable evidence ("failed", P1 collector framing) lowers
    # honest reputation; b_rep = 0.02 so that the scaling branch runs; the removed weight must stay
    # <= b_rep and the colluder voting share below base / (1 - b_rep)
    from sim2.common import State
    cls, s_ = ttru.population(10, 12, 9, seed=1)
    base = ttru.base_weights(cls, s_, K=0.05, pi=1.0, cap=0.10, u_max=0.25)
    order = np.argsort(-base)
    byz = np.zeros(n, bool)
    acc = 0.0
    for i in order:                               # heaviest first, up to a share of about 0.2
        if acc >= 0.2:
            break
        byz[i] = True
        acc += base[i]
    b_rep = 0.02
    rule = S.CusumExclusion(evidence="failed", rho_bar=0.01, D=200, cap=0.5, cap_weights=base)
    tw = ttru.TtruWeights(base, epoch=50, r_min=0.5, b_rep=b_rep, rule=rule)
    cfg = RunConfig(n=n, views=1500, seed=2, protocol="P1", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    adversary=A.CollectorFraming(), vote_weights=tw)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=n, seed=2, regions=3, jitter_max_ms=2.0)), st, 1, cfg.views)
    cache = st.__dict__["_ttru_cache"][id(tw)]
    shares = [float(t[byz].sum()) for t in cache["tables"]]
    cuts = cache["cuts"]
    scaled = sum(float((base * (1 - rr)).sum()) > b_rep + 1e-12 for rr in cache["rs"])
    removed = max(float(c.sum()) for c in cuts)
    honest_removed = max(float(c[~byz].sum()) for c in cuts)
    bound = acc / (1 - b_rep)
    print(f"budget: colluder base share {acc:.3f}, voting share max {max(shares):.4f} <= bound {bound:.4f}; "
          f"removed max {removed:.4f} <= b_rep {b_rep} (honest {honest_removed:.4f}); scaled epochs {scaled}")
    if max(shares) > bound + 1e-9 or removed > b_rep + 1e-12 or scaled == 0 or honest_removed <= 0:
        bad += 1
    # leaders come from final facts in weighted runs
    stale = 0
    for ev in ("at", "failed"):
        rule = S.CusumExclusion(evidence=ev, rho_bar=0.01, D=200, cap=0.5, cap_weights=base)
        tw = ttru.TtruWeights(base, epoch=50, rule=rule)
        cfg = RunConfig(n=n, views=800, seed=3, protocol="P1", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                        adversary=A.Compose([A.CollectorFraming(), A.SilentLeader(0.5)]), vote_weights=tw)
        r = engine_event.run(cfg, Network(NetConfig(n=n, seed=3, regions=3, jitter_max_ms=2.0)))
        rule2 = S.CusumExclusion(evidence=ev, rho_bar=0.01, D=200, cap=0.5, cap_weights=base)
        cfg2 = RunConfig(n=n, views=800, seed=3, protocol="P1", leader_rule=rule2, byzantine=list(np.flatnonzero(byz)),
                         vote_weights=ttru.TtruWeights(base, epoch=50, rule=rule2))
        stale += S.verify_leaders(r, cfg2)
    print(f"weighted runs: leaders from stale facts {stale}")
    if stale:
        bad += 1
    # targeted partial send: the k heaviest honest recipients, k the smallest with a share above
    # 1/3 - beta (evades AT at threshold 2/3) and still below 1/2 - beta (accused at threshold 1/2)
    beta = float(base[byz].sum())
    hs = np.cumsum(np.sort(base[~byz])[::-1])
    k = int(np.argmax(hs > 1 / 3 - beta + 0.01)) + 1
    assert hs[k - 1] < 1 / 2 - beta - 0.01
    for at_share, expect in ((2 / 3, False), (1 / 2, True)):
        cfg = RunConfig(n=n, views=400, seed=4, protocol="P2", leader_rule=S.Uniform(),
                        byzantine=list(np.flatnonzero(byz)), adversary=A.PartialSend(k, targeted=True),
                        vote_weights=lambda st, v: base, at_share=at_share)
        st = State(cfg)
        engine_event.simulate(cfg, Network(NetConfig(n=n, seed=4, regions=3, jitter_max_ms=2.0)), st, 1, cfg.views)
        acc_rate = float(np.mean([S.bad_fact(st, u, u + 20, "at") for u in range(1, 390) if st.byz[st.leaders[u]]]))
        hon = float(np.mean([S.bad_fact(st, u, u + 20, "at") for u in range(1, 390) if st.honest[st.leaders[u]]]))
        print(f"targeted partial send to {k} (share {hs[k - 1]:.3f}; beta {beta:.3f}), AT threshold {at_share:.3f}: "
              f"colluder views accused {acc_rate:.2f}, honest {hon:.2f}")
        if (acc_rate > 0.9) != expect or (not expect and acc_rate > 0.1) or hon > 0:
            bad += 1
    if bad:
        print(f"FAILED: {bad}")
        sys.exit(1)
    print("ALL WEIGHTED CHECKS PASSED")


def test_weighted():
    main()


if __name__ == "__main__":
    main()

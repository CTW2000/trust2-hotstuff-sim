"""Inclusion attestations (G2) checks: no honest leader is flagged in model S with the attestation
guard (2f+1 and f+1 thresholds) against framing, conflicting pairs near capacity and censorship;
the control groups (no guard, no exemptions) do flag honest leaders; every flagged colluder view
misses a due victim transaction; the closed loop with "omit" evidence computes leaders from final
facts. Run from the repository root:  python -m sim2.tests.test_inc"""
import sys
import time

import numpy as np

from sim2 import engine_event, engine_fast
from sim2 import schedule as S
from sim2.common import RunConfig, State
from sim2.net import NetConfig, Network
from sim2.txlayer import TxAdversary, TxConfig, TxLayer

N, VIEWS = 31, 800


def run(f0, tcfg, proto="P2", eps=0.0, seed=1):
    net = Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=eps))
    tl = TxLayer(tcfg, net)
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol=proto, leader_rule=S.Uniform(),
                    byzantine=list(range(N - f0, N)), txlayer=tl, timeout_votes=(proto == "P1"))
    st = State(cfg)
    engine_event.simulate(cfg, net, st, 1, VIEWS)
    s = tl.advance(st, VIEWS - 3)
    hl = [u for u in range(20, VIEWS - 10) if st.honest[st.leaders[u]] and st.qc_exists[u]]
    return st, s, float(np.mean([s["omit"][u] for u in hl]))


def main():
    bad = 0
    t0 = time.time()
    adv = {"frame": TxAdversary(frame=1.0), "censor": TxAdversary(censor=1.0), "conflict": TxAdversary(conflict=0.5)}
    for proto in ("P2", "P1"):
        for f0 in (3, 10):
            for thr in ("q", "f+1"):
                for name, a in adv.items():
                    kw = dict(rate=3.6, capacity=4) if name == "conflict" else {}
                    st, s, hon = run(f0, TxConfig(threshold=thr, adversary=a, **kw), proto)
                    if hon != 0.0:
                        bad += 1
                        print(f"[HONEST FLAGGED] {proto} f0={f0} thr={thr} {name}: {hon:.3f}")
                    if name == "censor":
                        for u in np.flatnonzero(s["omit"]):
                            if st.honest[st.leaders[u]] or not all(s["meta"][x]["victim"] and s["first_due"][x] >= 0
                                                                    for x in s["omit_tx"][u]):
                                bad += 1
                                print(f"[CENSOR FLAG] view {u} misses non-victim or non-due transactions")
                                break
    print(f"model S with the guard: honest leaders flagged 0 in all {2 * 2 * 2 * 3} settings ({time.time() - t0:.0f}s)"
          if bad == 0 else f"model S with the guard: {bad} failures")
    controls = [("no guard, framing", 10, TxConfig(delta_g=0.0, adversary=TxAdversary(frame=1.0))),
                ("no invalid exemption, conflicting pairs", 6,
                 TxConfig(exempt_invalid=False, adversary=TxAdversary(conflict=0.5))),
                ("no full-block exemption, overload", 6, TxConfig(rate=8, capacity=4, exempt_full=False))]
    for name, f0, tc in controls:
        _, _, hon = run(f0, tc)
        print(f"control ({name}): honest-led views flagged {hon:.3f}")
        if hon < 0.05:
            bad += 1
    # closed loop with "omit" evidence: leaders from final facts
    net = Network(NetConfig(n=N, seed=2, regions=3, jitter_max_ms=2.0))
    rule = S.PerfTilt(L=1 / 200, K=50, exclusion=S.CusumExclusion(evidence=("at", "omit"), q=0.2, rho_bar=0.005,
                                                                    D=500, cap=0.5, Wq=500))
    cfg = RunConfig(n=N, views=1500, seed=2, protocol="P2", leader_rule=rule, byzantine=list(range(21, 31)),
                    txlayer=TxLayer(TxConfig(adversary=TxAdversary(censor=1.0)), net))
    r = engine_fast.run(cfg, net)
    stale = S.verify_leaders(r, cfg)
    print(f"closed loop with omit evidence: stale leaders {stale}")
    if stale:
        bad += 1
    if bad:
        print(f"FAILED: {bad}")
        sys.exit(1)
    print("ALL INCLUSION CHECKS PASSED")


if __name__ == "__main__":
    main()

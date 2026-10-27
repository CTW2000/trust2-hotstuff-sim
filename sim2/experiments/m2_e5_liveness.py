"""M2 / E5: exclusion cap and expiry clock vs liveness after pre-GST accusations (abstract models).

Setting: P2, n = 31, f0 = 9 colluders, tau = 1000 ms. Before GST (views < GST) the adversary controls
the network and delays only honest senders; colluders propose normally and keep a clean record.
After GST, colluding leaders send their proposal to just enough honest replicas to stay unaccused
(partial send, not attributable) and colluders frame/shield through AT bits.
Pre-GST settings (how honest leaders come to be accused before GST):
  lie_partial       messages late w.p. 0.9 (0-3 s); colluders lie NR=1 from the start, so an honest
                    leader is accused once q - f0 = 12 honest replicas miss its proposal
  truthful_partial  same network, colluders report NR truthfully before GST (control): accusation
                    needs 21 of the 22 honest replicas to miss the proposal
  truthful_full     full pre-GST asynchrony (every honest message delayed by 1-3 s, i.e. beyond tau),
                    colluders truthful: every honest proposal is missed by everybody
  lie_mild          late w.p. 0.7, colluders lie from the start, shorter commit-count period
Variants of the Phase-1 module (CUSUM on AT evidence, constant share among non-excluded):
  nocap/commit  no cap, exclusion ends after D further successful views  -> DQ扩展 Lemma D: halt
  nocap/view    no cap, exclusion ends D views after it started           -> stall, then recovery
  cap/view      cap x_L = 0.5 (< 1 - beta0), view-number expiry           -> Theorem L: no stall
  cap/commit    cap x_L = 0.5, success-count expiry
  static        uniform leaders, no reputation (reference)
Measured: success fraction of views (block reached the chain) in windows after GST, the first
successful view after GST, and how many honest replicas were excluded at GST.
Run from the repository root:  python -m sim2.experiments.m2_e5_liveness
"""
import csv
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

from sim2 import adversary as A
from sim2 import engine_fast
from sim2 import schedule as S
from sim2.common import RunConfig
from sim2.experiments.m2_e3_at import partial_k
from sim2.net import NetConfig, Network

OUT = os.path.join(os.path.dirname(__file__), "..", "results")
N, F0, GST, VIEWS, TAU = 31, 9, 600, 5000, 1000.0
SETTINGS = {
    "lie_partial": dict(async_p=0.9, async_min_ms=0.0, lie_from=0, D_commit=1000),
    "truthful_partial": dict(async_p=0.9, async_min_ms=0.0, lie_from=GST, D_commit=1000),
    "truthful_full": dict(async_p=1.0, async_min_ms=TAU, lie_from=GST, D_commit=1000),
    "lie_mild": dict(async_p=0.7, async_min_ms=0.0, lie_from=0, D_commit=300),
}
SETTING = "lie_partial"


def variants():
    Dc = SETTINGS[SETTING]["D_commit"]
    return {"nocap/commit": S.CusumExclusion(evidence="at", D=Dc, expiry="commit"),
            "nocap/view": S.CusumExclusion(evidence="at", D=1500, expiry="view"),
            "cap/view": S.CusumExclusion(evidence="at", D=1500, expiry="view", cap=0.5, Wq=500),
            "cap/commit": S.CusumExclusion(evidence="at", D=Dc, expiry="commit", cap=0.5, Wq=500),
            "static": S.Uniform()}


def job(args):
    name, seed = args
    honest = list(range(N - F0))
    byz = list(range(N - F0, N))
    st_ = SETTINGS[SETTING]
    net = Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, async_views=GST,
                            async_p=st_["async_p"], async_min_ms=st_["async_min_ms"], async_extra_ms=3000.0,
                            async_senders=honest))
    adv = A.Compose([A.LieNR(start_view=st_["lie_from"]), A.PartialSend(partial_k(N, F0), start_view=GST)])
    cfg = RunConfig(n=N, views=VIEWS, seed=seed, protocol="P2", tau_ms=TAU, leader_rule=variants()[name],
                    byzantine=byz, adversary=adv)
    t0 = time.time()
    r = engine_fast.run(cfg, net)
    assert S.verify_leaders(r, cfg) == 0, "a leader was computed from facts that later changed"
    ok = np.array([S.succeeded(r.prop_parent, u, VIEWS) for u in range(1, VIEWS - 10)])
    views = np.arange(1, VIEWS - 10)
    post = views >= GST
    first = views[post & ok]
    excluded = set()
    for ev, k, u in r.rule_log:
        if u >= GST:
            break
        if ev == "exclude":
            excluded.add(k)
        elif ev == "release":
            excluded.discard(k)
    win = lambda a, b: float(ok[(views >= a) & (views < b)].mean())
    return dict(variant=name, seed=seed, honest_excluded_at_gst=sum(1 for k in excluded if k < N - F0),
                halted=bool(not ok[post].any()),
                first_success_after_gst=int(first[0] - GST) if first.size else -1,
                succ_gst_0_500=win(GST, GST + 500), succ_gst_500_2000=win(GST + 500, GST + 2000),
                succ_last_1000=win(VIEWS - 1010, VIEWS - 10), succ_pre_gst=win(1, GST),
                secs=time.time() - t0)


def _init(setting):
    global SETTING
    SETTING = setting


def main():
    global SETTING
    SETTING = sys.argv[1] if len(sys.argv) > 1 else "lie_partial"
    jobs = [(v, s) for v in variants() for s in range(10)]
    with Pool(8, initializer=_init, initargs=(SETTING,)) as pool:
        rows = pool.map(job, jobs)
    os.makedirs(OUT, exist_ok=True)
    print(f"setting {SETTING}: {SETTINGS[SETTING]}")
    with open(os.path.join(OUT, f"m2_e5_liveness_{SETTING}.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("| 变体 | GST 时被排除的诚实节点（共 22） | 永久停机（GST 后再无成功） | GST 后首次成功（视图数） | 成功率：GST 后 0–500 | 500–2000 | 最后 1000 |")
    print("|---|---|---|---|---|---|---|")
    for v in variants():
        g = [r for r in rows if r["variant"] == v]
        fs = [r["first_success_after_gst"] for r in g]
        done = sorted(x for x in fs if x >= 0)
        fs_txt = "从未" if not done else f"中位数 {np.median(done):.0f}，最大 {done[-1]}" + \
            (f"（{sum(x < 0 for x in fs)} 个种子从未）" if any(x < 0 for x in fs) else "")
        m = lambda c: np.mean([r[c] for r in g])
        print(f"| {v} | {m('honest_excluded_at_gst'):.1f} | {sum(r['halted'] for r in g)}/{len(g)} | {fs_txt} | {m('succ_gst_0_500'):.3f} | "
              f"{m('succ_gst_500_2000'):.3f} | {m('succ_last_1000'):.3f} |")
    print(f"compute {sum(r['secs'] for r in rows):.0f}s")


if __name__ == "__main__":
    main()

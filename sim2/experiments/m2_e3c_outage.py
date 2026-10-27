"""M2 / E3c: AT and the exclusion module under correlated delays (region outages); abstract models only.

Region outages: while a region is out, every message from or to its replicas is 5 s late (beyond the
2 s timeout). Replicas are assigned to regions round-robin (k mod R), colluders are replicas 22..30.
Part A (soundness): P1 with collector framing and P2 with vote withholding, colluders lie in NR bits
(framing NR=1 / shielding NR=0), uniform leaders. Honest-leader views are split into
  no outage | leader inside the out region | leader outside it,
and the "outside" case further by whether the out region holds at least q - f0 honest replicas
(then those replicas' NR=1 plus the f0 lies reach q: the honest leader is accused although it is
not at fault). Theory: inside -> accused (indistinguishable from a silent leader, TR'); outside ->
accused iff honest replicas in the out region >= q - f0.
Part B (module): CUSUM on AT evidence (rho_bar 0.01, gamma 1e4, exclusion 500 views) with and
without the cap 0.5, under recurring outages; colluders frame/shield and stay unaccused otherwise.
Measured: share of honest replicas excluded, colluder leader share, success rate.
Run from the repository root:  python -m sim2.experiments.m2_e3c_outage [A|B]
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
from sim2.net import NetConfig, Network

OUT = os.path.join(os.path.dirname(__file__), "..", "results")
N = 31
Q = (N + (N - 1) // 3) // 2 + 1


def net_for(regions, seed, p=0.01, length=20):
    return Network(NetConfig(n=N, seed=seed, regions=regions, jitter_max_ms=2.0, outage_p=p,
                             outage_len=length, outage_extra_ms=5000.0))


def job_a(args):
    proto, regions, f0, seed = args
    views = 6000
    byz = list(range(N - f0, N))
    frame = A.CollectorFraming() if proto == "P1" else A.WithholdVotesOnHonest()
    adv = A.Compose([frame, A.LieNR()]) if f0 else None
    net = net_for(regions, seed)
    cfg = RunConfig(n=N, views=views, seed=seed, protocol=proto, leader_rule=S.Uniform(), byzantine=byz, adversary=adv)
    r = engine_fast.run(cfg, net)
    rows = {"none": [], "inside": [], "outside_big": [], "outside_small": []}
    for u in range(1, views - 10):
        L = r.leaders[u]
        if not r.honest[L]:
            continue
        mask = net.outage_mask(u)
        acc = r.nr_count[u] >= Q
        if not mask.any():
            rows["none"].append(acc)
        elif mask[L]:
            rows["inside"].append(acc)
        else:
            h_out = int((mask & r.honest).sum())
            rows["outside_big" if h_out >= Q - f0 else "outside_small"].append(acc)
    out = dict(protocol=proto, regions=regions, f0=f0, seed=seed)
    for k, v in rows.items():
        out[f"n_{k}"] = len(v)
        out[f"acc_{k}"] = float(np.mean(v)) if v else float("nan")
    return out


def job_b(args):
    regions, cap, f0, seed = args
    views = 8000
    byz = list(range(N - f0, N))
    adv = A.Compose([A.WithholdVotesOnHonest(), A.LieNR(), A.PartialSend(1 + max(0, (N - f0) - Q))]) if f0 else None
    rule = S.Uniform() if cap == "static" else S.CusumExclusion(evidence="at", D=500, cap=cap, Wq=500)
    net = net_for(regions, seed, p=0.01, length=20)
    cfg = RunConfig(n=N, views=views, seed=seed, protocol="P2", leader_rule=rule, byzantine=byz, adversary=adv)
    r = engine_fast.run(cfg, net)
    assert S.verify_leaders(r, cfg) == 0
    excl = np.zeros(N, bool)
    honest_excl_frac = []
    ev = sorted(r.rule_log, key=lambda e: e[2])
    i = 0
    for u in range(1, views + 1):
        while i < len(ev) and ev[i][2] <= u:
            kind, k, _ = ev[i]
            if kind == "exclude":
                excl[k] = True
            elif kind == "release":
                excl[k] = False
            i += 1
        honest_excl_frac.append((excl & r.honest).sum() / r.honest.sum())
    ok = np.array([S.succeeded(r.prop_parent, u, views) for u in range(1, views - 10)])
    lead = r.leaders[1:views - 10]
    return dict(regions=regions, cap=cap if cap else "none", f0=f0, seed=seed,
                honest_excluded_mean=float(np.mean(honest_excl_frac)),
                honest_excluded_max=float(np.max(honest_excl_frac)),
                colluder_leader_share=float(np.mean(r.roles[lead] == 2)) if f0 else 0.0,
                success_rate=float(ok.mean()), min_success_500=float(min(
                    ok[i:i + 500].mean() for i in range(0, len(ok) - 500, 100))))


def main():
    part = sys.argv[1] if len(sys.argv) > 1 else "A"
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    if part == "A":
        jobs = [(p, R, f0, s) for p in ("P1", "P2") for R in (2, 3, 6) for f0 in (0, 9) for s in range(3)]
        with Pool(8) as pool:
            rows = pool.map(job_a, jobs)
        path = os.path.join(OUT, "m2_e3c_outage_A.csv")
        print("| 协议 | 区域数（每区诚实约） | 同伙 f0 | 无中断 | 领导者在中断区域内 | 在区域外，区域内诚实 ≥ q−f0 | 在区域外，区域内诚实 < q−f0 |")
        print("|---|---|---|---|---|---|---|")
        for k in sorted({(r["protocol"], r["regions"], r["f0"]) for r in rows}):
            g = [r for r in rows if (r["protocol"], r["regions"], r["f0"]) == k]

            def cell(c):
                n = sum(r[f"n_{c}"] for r in g)
                if n == 0:
                    return "—"
                return f"{np.nansum([r[f'acc_{c}'] * r[f'n_{c}'] for r in g]) / n:.3f}（{n}）"
            print(f"| {k[0]} | {k[1]}（{(N - k[2]) // k[1]}） | {k[2]} | {cell('none')} | {cell('inside')} | "
                  f"{cell('outside_big')} | {cell('outside_small')} |")
    else:
        jobs = [(R, cap, f0, s) for R in (2, 3, 6) for cap in (None, 0.5, "static") for f0 in (0, 9) for s in range(3)]
        with Pool(8) as pool:
            rows = pool.map(job_b, jobs)
        path = os.path.join(OUT, "m2_e3c_outage_B.csv")
        print("| 区域数 | 同伙 f0 | 排除上限 | 被排除的诚实节点比例（平均 / 最大） | 同伙领导份额 | 成功率 | 最差 500 视图窗口的成功率 |")
        print("|---|---|---|---|---|---|---|")
        label = {"none": "无上限", 0.5: "上限 0.5", "static": "静态轮换（无信誉）"}
        for k in sorted({(r["regions"], r["f0"], str(r["cap"])) for r in rows}):
            g = [r for r in rows if (r["regions"], r["f0"], str(r["cap"])) == k]
            m = lambda c: np.mean([r[c] for r in g])
            print(f"| {k[0]} | {k[1]} | {label[g[0]['cap']]} |{m('honest_excluded_mean'):.3f} / {max(r['honest_excluded_max'] for r in g):.3f} | "
                  f"{m('colluder_leader_share'):.3f} | {m('success_rate'):.3f} | {min(r['min_success_500'] for r in g):.3f} |")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wall {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

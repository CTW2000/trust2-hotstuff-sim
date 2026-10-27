"""M0 baseline: honest replicas only, P2, synthetic networks. Run from the repository root:
    python -m sim2.experiments.m0_honest
Writes sim2/results/m0_honest.csv.
"""
import csv
import os
import time

import numpy as np

from sim2 import engine_event, engine_fast
from sim2.common import RunConfig, commit_times
from sim2.net import NetConfig, Network

NETS = {
    "LAN_1region": dict(regions=1, region_c0_ms=0.5, access_lo_ms=0.1, access_hi_ms=0.5, jitter_max_ms=0.2),
    "3regions": dict(regions=3, jitter_max_ms=2.0),
    "6regions_global": dict(regions=6, region_c0_ms=8.0, region_c1_ms=120.0, jitter_max_ms=10.0),
}
PAYLOAD = {"250KB": 250_000.0, "1MB": 1_000_000.0}


def summarize(r, net):
    """slot time S_v = E(v+1) - E(v) (first honest entries); commit latency = time from the
    proposal of block v (entry of its leader) to the mean time alive replicas learn it is committed."""
    k = r.know[:, r.alive]
    E = k.min(1)
    S = np.diff(E)
    c = commit_times(r)[:, r.alive]
    V = r.know.shape[0] - 1
    prop_time = np.array([r.know[v - 1, r.leaders[v]] for v in range(1, V + 1)])
    blocks = np.arange(1, V - 1)                 # last two blocks cannot commit within the run
    committed = ~np.isnan(c[blocks]).all(axis=1)
    lat = np.nanmean(c[blocks][committed], axis=1) - prop_time[blocks - 1][committed]
    Df = net.delta_fwd()
    return dict(slot_mean_ms=S.mean(), slot_p99_ms=np.percentile(S, 99), commit_lat_ms=lat.mean(),
                committed_frac=committed.mean(), delta_fwd_ms=Df,
                skew_over_delta_fwd=(k.max(1) - k.min(1)).max() / Df,
                triangle_slack_ms=net.triangle_slack())


def main():
    out = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(out, exist_ok=True)
    rows = []
    for nname, p in NETS.items():
        for pl_name, pl in PAYLOAD.items():
            for n in (16, 31, 64, 100):
                sizes = {"prop": pl, "vote": 200.0, "tmo": 300.0, "fwd": 4_000.0}
                net = Network(NetConfig(n=n, seed=1, sizes_bytes=sizes, **p))
                cfg = RunConfig(n=n, views=2000, seed=1, leader_mode="random")
                t0 = time.time()
                r = engine_fast.run(cfg, net)
                dt = time.time() - t0
                row = dict(net=nname, payload=pl_name, n=n, views_per_s=cfg.views / dt,
                           fallback_views=r.fallback_views, jitter_max_ms=net.cfg.jitter_max_ms,
                           **summarize(r, net))
                rows.append(row)
                print("  ".join(f"{k}={v:.3g}" if isinstance(v, float) else f"{k}={v}" for k, v in row.items()))
    with open(os.path.join(out, "m0_honest.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # engine speed comparison at n = 16 and n = 31
    for n in (16, 31):
        net = Network(NetConfig(n=n, seed=2, **NETS["3regions"]))
        cfg = RunConfig(n=n, views=300, seed=2)
        t0 = time.time(); engine_fast.run(cfg, net); tf = time.time() - t0
        t0 = time.time(); engine_event.run(cfg, net); te = time.time() - t0
        print(f"speed n={n}: fast {cfg.views / tf:.0f} views/s, event {cfg.views / te:.0f} views/s ({te / tf:.0f}x)")


if __name__ == "__main__":
    main()

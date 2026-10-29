"""Link-delay tables for the prototype's delay injection (prototype/DESIGN.md §14.1) from the simulator's network
model (sim2/net.py `Network`, same seeds): base[i][j] = region latency + access delays of both ends, plus the
jitter bound and the bandwidth. Node i of a run is replica i of the simulator.
Run from the repository root:  PYTHONPATH=. python prototype/scripts/gen_nets.py
"""
import json
import os

from sim2.net import NetConfig, Network

OUT = os.path.join(os.path.dirname(__file__), "..", "benchmark", "nets")
NETS = {  # as in sim2/experiments/dirTtruReview.py
    "base": dict(regions=3, jitter_max_ms=2.0),
    "wide": dict(regions=8, region_c1_ms=120.0, jitter_max_ms=20.0),
}


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, kw in NETS.items():
        for n in (4, 10, 31):
            net = Network(NetConfig(n=n, seed=0, **kw))
            out = dict(net=name, n=n, seed=0, base_ms=[[round(float(x), 3) for x in row] for row in net.base],
                       jitter_ms=net.cfg.jitter_max_ms, bandwidth_mbps=net.cfg.bw_mbps,
                       delta_max_ms=round(net.delta_max(), 3), delta_fwd_ms=round(net.delta_fwd(), 3))
            path = os.path.join(OUT, f"{name}-n{n}-s0.json")
            with open(path, "w") as fh:
                json.dump(out, fh)
            off = [x for i, row in enumerate(net.base) for j, x in enumerate(row) if i != j]
            print(f"{path}: one-way {min(off):.0f}-{max(off):.0f} ms, delta_max {net.delta_max():.0f} ms")


if __name__ == "__main__":
    main()

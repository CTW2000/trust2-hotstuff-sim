"""Synthetic network model: per-link latency, bounded jitter, bandwidth.

All parameters are synthetic. Nothing here measures or contacts any real network.

Link delay of a message of type `mtype` sent from i to j in view `v`:

    delay = base[i, j] + jitter_v[i, j] + size[mtype] / bw[i]        (i != j)
    delay = 0                                                         (i == j)

* base[i, j] = region_lat[r_i, r_j] + access[i] + access[j]. Region latencies are
  c0 + c1 * distance between region positions on a plane, so base is a metric plus
  slack: base[i, k] + 2 * access[j] + c0 <= base[i, j] + base[j, k].
* jitter is in [0, jitter_max], drawn from a seeded generator keyed by (seed, view, mtype).
  Every message "sent in view v" uses key v: proposal v, votes v, timeouts v, and
  certificate forwards made on entering v.
* Model S bound: delta_max() is an upper bound on every delay.
* Model P (eps_late > 0): every message between distinct replicas is independently late with
  probability eps_late, and a late message gets an extra late_extra_ms on top of its delay. The
  late mask is keyed by (seed, view, mtype), like the jitter, so both engines see the same draws.
  delta_max()/delta_fwd() bound only the messages that are not late.
* Before GST (views < async_views, keyed by the view of the message): each message gets an extra
  delay uniform in [0, async_extra_ms] with probability async_p. This is an abstraction of an
  asynchronous period; GST is the first view >= async_views.
* Correlated delays (region outages): in each view an outage starts with probability outage_p in a
  uniformly chosen region and lasts outage_len views; while a region is out, every message keyed
  to such a view that is sent from or to a replica of that region gets outage_extra_ms more delay.
  Draws are keyed by (seed, 37, start view), so both engines see the same outages.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

MTYPES = ("prop", "vote", "tmo", "fwd")
_MTYPE_ID = {m: k for k, m in enumerate(MTYPES)}
_MTYPE_ID["tx"] = len(MTYPES)          # transaction gossip (txlayer); not part of the consensus bounds
TX_BYTES = 500.0                       # default size of a gossiped transaction batch entry


@dataclass
class NetConfig:
    n: int = 16
    regions: int = 3
    region_c0_ms: float = 5.0          # constant term of region latency (also intra-region latency)
    region_c1_ms: float = 60.0         # ms per unit distance; region positions in the unit square
    access_lo_ms: float = 1.0
    access_hi_ms: float = 5.0
    jitter_max_ms: float = 2.0
    bw_mbps: float = 1000.0            # sender uplink bandwidth (per message, no contention)
    sizes_bytes: Dict[str, float] = field(default_factory=lambda: {
        "prop": 250_000.0, "vote": 200.0, "tmo": 300.0, "fwd": 4_000.0})
    eps_late: float = 0.0              # model P: probability that a message is late
    late_extra_ms: float = 5_000.0     # extra delay of a late message
    async_views: int = 0               # views < async_views are before GST (chaotic delivery)
    async_p: float = 0.5               # before GST: probability a message gets an extra delay
    async_extra_ms: float = 3_000.0    # before GST: the extra delay is uniform in [async_min_ms, async_extra_ms]
    async_min_ms: float = 0.0
    outage_p: float = 0.0              # correlated delays: probability that a region outage starts in a view
    outage_len: int = 20               # an outage lasts this many views
    outage_extra_ms: float = 5_000.0   # extra delay of every message sent from or to the affected region
    async_senders: Optional[List[int]] = None  # before GST only these senders are delayed (None = all);
                                               # the adversary controls the network before GST
    seed: int = 0


class Network:
    def __init__(self, cfg: NetConfig):
        self.cfg = cfg
        n = cfg.n
        rng = np.random.default_rng([cfg.seed, 7])
        pos = rng.random((cfg.regions, 2))
        dist = np.sqrt(((pos[:, None, :] - pos[None, :, :]) ** 2).sum(-1))
        region_lat = cfg.region_c0_ms + cfg.region_c1_ms * dist
        self.region_of = np.arange(n) % cfg.regions
        access = rng.uniform(cfg.access_lo_ms, cfg.access_hi_ms, n)
        base = region_lat[self.region_of][:, self.region_of] + access[:, None] + access[None, :]
        np.fill_diagonal(base, 0.0)
        self.base = base
        self.access = access
        # transmission time in ms: bytes * 8 / (Mbit/s * 1e6) * 1e3
        self.tx = {m: cfg.sizes_bytes[m] * 8.0 / (cfg.bw_mbps * 1e3) for m in MTYPES}
        self.tx["tx"] = cfg.sizes_bytes.get("tx", TX_BYTES) * 8.0 / (cfg.bw_mbps * 1e3)
        self._cache: Dict[tuple, np.ndarray] = {}

    def delays(self, view: int, mtype: str) -> np.ndarray:
        key = (view, mtype)
        d = self._cache.get(key)
        if d is None:
            cfg = self.cfg
            if cfg.jitter_max_ms > 0:
                rng = np.random.default_rng([cfg.seed, 11, view, _MTYPE_ID[mtype]])
                jit = rng.random((cfg.n, cfg.n)) * cfg.jitter_max_ms
            else:
                jit = 0.0
            d = self.base + jit + self.tx[mtype]
            if cfg.eps_late > 0:
                rng = np.random.default_rng([cfg.seed, 13, view, _MTYPE_ID[mtype]])
                d = d + (rng.random((cfg.n, cfg.n)) < cfg.eps_late) * cfg.late_extra_ms
            if view < cfg.async_views:
                rng = np.random.default_rng([cfg.seed, 19, view, _MTYPE_ID[mtype]])
                hit = rng.random((cfg.n, cfg.n)) < cfg.async_p
                span = cfg.async_extra_ms - cfg.async_min_ms
                extra = hit * (cfg.async_min_ms + rng.random((cfg.n, cfg.n)) * span)
                if cfg.async_senders is not None:
                    rows = np.zeros(cfg.n, bool)
                    rows[list(cfg.async_senders)] = True
                    extra[~rows, :] = 0.0
                d = d + extra
            out = self.outage_mask(view)
            if out.any():
                hit = out[:, None] | out[None, :]
                d = d + hit * cfg.outage_extra_ms
            np.fill_diagonal(d, 0.0)
            if len(self._cache) > 64:
                self._cache.clear()
            self._cache[key] = d
        return d

    def outage_regions(self, view: int) -> set:
        """Regions that are out in this view."""
        cfg = self.cfg
        if cfg.outage_p <= 0 or view < 0:
            return set()
        starts = self.__dict__.setdefault("_outage_starts", {})
        out = set()
        for s in range(max(0, view - cfg.outage_len + 1), view + 1):
            if s not in starts:
                rng = np.random.default_rng([cfg.seed, 37, s])
                starts[s] = int(rng.integers(cfg.regions)) if rng.random() < cfg.outage_p else -1
            if starts[s] >= 0:
                out.add(starts[s])
        return out

    def outage_mask(self, view: int) -> np.ndarray:
        regs = self.outage_regions(view)
        if not regs:
            return np.zeros(self.cfg.n, bool)
        return np.isin(self.region_of, list(regs))

    def delta_max(self) -> float:
        """Upper bound on any single message delay (model S Delta)."""
        return float(self.base.max() + self.cfg.jitter_max_ms + max(self.tx[m] for m in MTYPES))

    def delta_fwd(self) -> float:
        """Upper bound on a certificate-forward delay; PM bounds honest entry skew by this."""
        return float(self.base.max() + self.cfg.jitter_max_ms + self.tx["fwd"])

    def triangle_slack(self) -> float:
        """min over i,j,k (j distinct) of base[i,j] + base[j,k] - base[i,k]; positive slack larger
        than the jitter bound rules out causality races between relayed and direct messages."""
        b = self.base
        n = b.shape[0]
        s = np.inf
        for j in range(n):
            m = b[:, j][:, None] + b[j, :][None, :] - b
            m[j, :] = np.inf
            m[:, j] = np.inf
            s = min(s, float(m.min()))
        return s


def uniform_network(n: int, d_ms: float, seed: int = 0) -> "Network":
    """All links have the same delay d (no jitter, no transmission time): for analytic checks."""
    cfg = NetConfig(n=n, regions=1, region_c0_ms=0.0, region_c1_ms=0.0, access_lo_ms=d_ms / 2,
                    access_hi_ms=d_ms / 2, jitter_max_ms=0.0, bw_mbps=1e12,
                    sizes_bytes={m: 0.0 for m in MTYPES}, seed=seed)
    return Network(cfg)

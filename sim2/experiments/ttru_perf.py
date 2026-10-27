"""Shared helpers for the T_tru experiments (review 信任2.0_v05_审查_实验与文档 #2, #4, #11). Abstract only.

perf(): throughput metrics instead of the per-view "QC rate" (qc_exists counts views whose QC formed at
any time, including after every honest replica left the view; failed views also last a full timeout):
  commit  share of views in [lo, hi) whose block some honest replica commits (two-chain, commit_times)
  bps     committed blocks per simulated second (median honest clock over [lo, hi))
  view_ms mean simulated view length
PreGSTNet: stronger pre-GST networks than i.i.d. extra delays: "outage" (correlated region outages,
NetConfig.outage_p, only before GST) and "adv" (before GST the network delays every honest leader's
proposal by 6 s to the heaviest honest replicas holding just over 2/3 - beta of the base weight, so they
time out with a truthful NR=1).
"""
import numpy as np

from sim2.common import Result, commit_times
from sim2.net import Network


def perf(st, lo, hi):
    ct = commit_times(Result.from_state(st))
    hon = st.honest
    committed = ~np.all(np.isnan(ct[lo:hi][:, hon]), axis=1)
    sec = float(np.median(st.know[hi, hon] - st.know[lo, hon])) / 1000.0
    return dict(commit=float(committed.mean()), bps=float(committed.sum()) / sec if sec > 0 else float("nan"),
                view_ms=1000.0 * sec / (hi - lo))


def adv_targets(base, byz):
    """Heaviest honest replicas holding just over 2/3 - beta of the base weight."""
    beta = float(base[byz].sum())
    hon = np.flatnonzero(~byz)
    order = hon[np.argsort(-base[hon])]
    return order[: int(np.argmax(np.cumsum(base[order]) > 2 / 3 - beta + 0.02)) + 1]


class PreGSTNet(Network):
    def __init__(self, cfg, mode, gst, st=None, targets=None):
        super().__init__(cfg)
        self.mode, self.gst, self.st, self.targets = mode, gst, st, targets

    def outage_mask(self, view):
        if self.mode == "outage" and view < self.gst:
            return super().outage_mask(view)
        return np.zeros(self.cfg.n, bool)

    def delays(self, view, mtype):
        d = super().delays(view, mtype)
        if self.mode == "adv" and view < self.gst and mtype == "prop":
            L = int(self.st.leaders[view])
            if L >= 0 and self.st.honest[L]:
                d = d.copy()
                d[L, self.targets] += 6000.0
                d[L, L] = 0.0
        return d

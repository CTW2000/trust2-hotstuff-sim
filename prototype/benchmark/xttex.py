"""The throughput-latency figure of the paper (figures/xt.tex, pgfplots) from a run of p5.py xt / r7xt.

One panel per committee size; per build the medians over the runs of each input rate, joined in input-rate order (the
line turns back where the server overloads). A run that committed nothing has no latency and is left out of its
cell. Hollow markers: some run of the cell had a timeout. Run from prototype/benchmark/:
    python3 xttex.py results-p5/r7_xt.csv > xt.tex
"""
import csv
import sys
from collections import defaultdict
from statistics import median

PANELS = (
    (4, r"\nextgroupplot[title={$n=4$},xmax=400,xtick distance=100,ylabel={端到端时延（ms）},legend to name=xtlegend]"),
    (10, r"\nextgroupplot[title={$n=10$},xmax=200,xtick distance=50,xlabel={端到端吞吐（千 tx/s）}]"),
    (31, r"\nextgroupplot[title={$n=31$},xmax=80,xtick distance=20]"),
)
SERIES = (("baseline", "cbase", "*", "基线"), ("trust2", "ctrust", "square*", "信任 2.0"))
HEAD = r"""\begin{tikzpicture}
\begin{groupplot}[paper, group style={group size=3 by 1,horizontal sep=5mm,yticklabels at=edge left},
  scale only axis,width=4.85cm,height=3.0cm,ymode=log,ymin=250,ymax=8000,
  ytick={300,500,1000,2000,5000},yticklabels={300,500,1000,2000,5000},
  xmajorgrids,ymajorgrids,xmin=0,
  legend style={font=\small,legend columns=3,column sep=8pt}]"""
TAIL = r"""\end{groupplot}
\node[anchor=south] at ([yshift=7mm]group c2r1.north) {\pgfplotslegendfromname{xtlegend}};
\end{tikzpicture}"""


def cells(path):
    out = defaultdict(lambda: defaultdict(list))
    with open(path) as fh:
        for row in csv.DictReader(fh):
            out[int(row["nodes"]), row["build"]][int(row["rate"])].append(row)
    return out


def points(runs_by_rate):
    pts, hollow, dropped = [], [], []
    for rate in sorted(runs_by_rate):
        runs = runs_by_rate[rate]
        kept = [r for r in runs if int(r["e2e_tps"]) > 0]
        if len(kept) < len(runs):
            dropped.append((rate, len(runs) - len(kept)))
        if not kept:
            continue
        p = "(%.1f,%d)" % (median(int(r["e2e_tps"]) for r in kept) / 1000,
                           round(median(int(r["e2e_latency_ms"]) for r in kept)))
        pts.append(p)
        if any(int(r["timeouts"]) > 0 for r in runs):
            hollow.append(p)
    return pts, hollow, dropped


def main():
    data = cells(sys.argv[1])
    lines = [HEAD]
    for nodes, panel in PANELS:
        lines.append(panel)
        for build, color, mark, name in SERIES:
            pts, hollow, dropped = points(data[nodes, build])
            for rate, k in dropped:
                print("n=%d %s %d tx/s: %d run(s) committed nothing" % (nodes, build, rate, k), file=sys.stderr)
            lines.append(r"\addplot[series={%s}{%s}] coordinates {%s};" % (color, mark, " ".join(pts)))
            if nodes == 4:
                lines.append(r"\addlegendentry{%s}" % name)
            if hollow:
                lines.append(r"\addplot[forget plot,only marks,mark=%s,mark size=2pt,mark options={fill=white,"
                             r"draw=%s,line width=0.8pt}] coordinates {%s};" % (mark, color, " ".join(hollow)))
        if nodes == 4:
            lines.append(r"\addlegendimage{only marks,mark=*,mark size=2pt,mark options={fill=white,draw=cmuted,"
                         r"line width=0.8pt}}")
            lines.append(r"\addlegendentry{出现超时的档位}")
    lines.append(TAIL)
    print("\n".join(lines))


if __name__ == "__main__":
    main()

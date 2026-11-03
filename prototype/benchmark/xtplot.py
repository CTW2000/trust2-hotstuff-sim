"""Throughput against latency: results-p5/xt.csv -> results-p5/xt.svg, one panel per committee size. The line joins the
medians in input-rate order and turns back where the server overloads; the small dots are the single runs.
Run from prototype/benchmark/:  python3 xtplot.py
"""
import csv
from collections import defaultdict
from math import log10
from statistics import median

IN, OUT = "results-p5/xt.csv", "results-p5/xt.svg"
SERIES = (("baseline", "基线", "#2a78d6"), ("trust2", "信任 2.0", "#eb6834"))
PANELS = ((4, 400_000, 100_000), (10, 200_000, 50_000), (31, 80_000, 20_000))
Y_TICKS, Y_LOW, Y_HIGH = (300, 500, 1000, 2000, 5000), 250, 8000
W, H, LEFT, TOP, PLOT_W, PLOT_H, GAP = 1000, 372, 62, 58, 278, 248, 28
SURFACE, INK, MUTED, GRID, AXIS = "#fcfcfb", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
FONT = 'system-ui, -apple-system, "Segoe UI", "PingFang SC", "Noto Sans CJK SC", sans-serif'


def cells():
    """(nodes, build) -> runs per input rate. A run that committed nothing has no latency, so it gives no dot."""
    out = defaultdict(lambda: defaultdict(list))
    with open(IN) as fh:
        for row in csv.DictReader(fh):
            out[int(row["nodes"]), row["build"]][int(row["rate"])].append(
                (int(row["e2e_tps"]), int(row["e2e_latency_ms"])))
    return out


def text(x, y, body, size=12, fill=INK, anchor="start"):
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}">{body}</text>'


def marker(x, y, color, shape, tip):
    """A circle for the baseline and a square for Trust 2.0, so the print does not depend on the colour."""
    if shape == 0:
        mark = f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{color}" stroke="{SURFACE}" stroke-width="2"/>'
    else:
        mark = (f'<rect x="{x - 4.5:.1f}" y="{y - 4.5:.1f}" width="9" height="9" rx="1.5" fill="{color}" '
                f'stroke="{SURFACE}" stroke-width="2"/>')
    return f'<g>{mark}<title>{tip}</title></g>'


def panel(data, index, nodes, x_max, x_step):
    left = LEFT + index * (PLOT_W + GAP)
    to_x = lambda tps: left + PLOT_W * tps / x_max
    to_y = lambda ms: TOP + PLOT_H * (log10(Y_HIGH) - log10(ms)) / (log10(Y_HIGH) - log10(Y_LOW))
    out = [text(left, TOP - 14, f"n = {nodes}", 14, "#0b0b0b")]
    for ms in Y_TICKS:
        y = to_y(ms)
        out.append(f'<line x1="{left}" x2="{left + PLOT_W}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>')
        if index == 0:
            out.append(text(left - 8, y + 4, f"{ms:,}", 11, MUTED, "end"))
    bottom = TOP + PLOT_H
    out.append(f'<line x1="{left}" x2="{left + PLOT_W}" y1="{bottom}" y2="{bottom}" stroke="{AXIS}"/>')
    for tps in range(0, x_max + 1, x_step):
        out.append(text(to_x(tps), bottom + 18, f"{tps // 1000}k" if tps else "0", 11, MUTED, "middle"))
    for shape, (build, _, color) in enumerate(SERIES):
        runs = data[nodes, build]
        line = []
        for rate in sorted(runs):
            done = [(tps, ms) for tps, ms in runs[rate] if ms > 0]
            for tps, ms in done:
                out.append(f'<circle cx="{to_x(tps):.1f}" cy="{to_y(ms):.1f}" r="2.5" fill="{color}" opacity="0.4"/>')
            line.append((rate, median(tps for tps, _ in done), median(ms for _, ms in done), len(done)))
        points = " ".join(f"{to_x(tps):.1f},{to_y(ms):.1f}" for _, tps, ms, _ in line)
        out.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2" '
                   'stroke-linejoin="round" stroke-linecap="round"/>')
        for rate, tps, ms, count in line:
            tip = f"n = {nodes}，{SERIES[shape][1]}，输入 {rate:,} tx/s：{tps:,.0f} tx/s，{ms:,.0f} ms（{count} 次）"
            out.append(marker(to_x(tps), to_y(ms), color, shape, tip))
    return out


def main():
    data = cells()
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
           f'font-family=\'{FONT}\' style="font-variant-numeric: tabular-nums">',
           f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>']
    x = LEFT
    for shape, (_, name, color) in enumerate(SERIES):
        out.append(marker(x + 5, 20, color, shape, name))
        out.append(text(x + 16, 24, name, 13))
        x += 92
    out.append(text(x + 8, 24, "粗线是 3 次的中位数，小点是单次运行；线回折处是单台服务器过载", 12, MUTED))
    for index, (nodes, x_max, x_step) in enumerate(PANELS):
        out += panel(data, index, nodes, x_max, x_step)
    out.append(text(LEFT + (3 * PLOT_W + 2 * GAP) / 2, H - 8, "端到端吞吐（tx/s）", 12, INK, "middle"))
    out.append(f'<text transform="translate(16 {TOP + PLOT_H / 2}) rotate(-90)" font-size="12" fill="{INK}" '
               'text-anchor="middle">端到端时延（ms，对数轴）</text>')
    out.append("</svg>\n")
    with open(OUT, "w") as fh:
        fh.write("\n".join(out))


if __name__ == "__main__":
    main()

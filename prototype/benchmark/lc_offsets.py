"""DESIGN.md §15.14: node timeouts by their offset from the nearest handover (terminal block; multiples of 25 without epochs), per arm,
from the archived logs of p5.py lc: python3 lc_offsets.py <logs dir>..."""
import re, sys, tarfile, os, tempfile, shutil
from collections import Counter, defaultdict
from glob import glob
TIMEOUT = re.compile(rb"Timeout reached for round (\d+)")
NEAR = "near(-1..+4)"
ENTER = re.compile(rb"Entered epoch \d+ at round \d+ \(terminal block B(\d+)\)")
def main():
    arms = defaultdict(lambda: [Counter(), 0, 0])
    for d in sys.argv[1:]:
        for tgz in sorted(glob(os.path.join(d, "*.tgz"))):
            arm = re.sub(r"-\d+\.tgz$", "", os.path.basename(tgz))
            tmp = tempfile.mkdtemp(dir="/tmp")
            with tarfile.open(tgz) as t:
                t.extractall(tmp, members=[m for m in t.getmembers() if re.search(r"node-\d+\.log$", m.name)])
            terms, rounds = set(), []
            for path in glob(os.path.join(tmp, "logs", "node-*.log")):
                data = open(path, "rb").read()
                if path.endswith("node-0.log"):
                    terms = {int(x) for x in ENTER.findall(data)}
                rounds += [int(x) for x in TIMEOUT.findall(data)]
            shutil.rmtree(tmp)
            top = max(rounds, default=0)
            anchors = sorted(terms) or list(range(25, top + 50, 25))
            c, a = arms[arm][0], arms[arm]
            for r in rounds:
                nearest = min(anchors, key=lambda x: abs(r - x))
                off = r - nearest
                c[NEAR if -1 <= off <= 4 else "far"] += 1
            a[1] += 1; a[2] += len(rounds)
    for arm, (c, runs, total) in sorted(arms.items()):
        print(f"{arm}: {runs} runs, node timeouts per run {total / runs:.0f}; near a handover {c[NEAR] / runs:.0f}, far {c['far'] / runs:.0f}")
if __name__ == "__main__":
    main()

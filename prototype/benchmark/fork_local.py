"""Protocol-level fork with split-brain members, then offline forensics (DESIGN.md §15.15), within the lab limits.

Every Byzantine member runs as two processes with one key, one per side. Side s's committee file maps the member to
its side-s process and the honest members of the other side to closed ports, so the two honest groups never hear of
each other (a partition for the whole run). Every process runs the unmodified protocol; the scenarios only add
experiment switches to the Byzantine halves:
  s1  nothing: wherever a Byzantine member leads, each side gets its own block and both halves vote (E1);
  s2  disjoint vote windows: side 1's halves vote only in rounds <= K, side 2's only in rounds > K, so the fork
      goes through TCs whose Byzantine signers report the genesis on side 2 (E3 only);
  s3  s2 with tc_outside_block on every process: the TC travels with the proposal but is not part of the block.
After the run, `node forensics` reads the stores of one honest node of each side. A single epoch (epoch_length 0).

Populations (n = 19, equal stakes):
  equal     7 Byzantine, 6 + 6 honest, all licensed;
  weighted  10 licensed, 9 uncertified (class cap 25%, entity cap 10%): Byzantine 3 licensed + 5 uncertified
            (36.4%), side 1 4 + 1 (32.8%), side 2 3 + 3 (30.8%).
Processes: 26 (equal) or 27 (weighted), plus 4 clients. The script holds the bench lock of run_local.py and runs in a
systemd scope with a CPU quota and a memory cap.

Run from prototype/benchmark/ (after `cargo build --release --features benchmark` in prototype/node):
    python3 fork_local.py --scenario s2 --population equal --duration 60
Prints the forensics of two pairs of honest nodes as one JSON line and appends it to results-p5/fork.jsonl.
"""
import argparse
import fcntl
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from glob import glob
from os.path import join

from benchmark.config import Committee, Key, NodeParameters

MAX_PROCESSES = 31
BASE_PORT = 9000
CLOSED_PORT = 29000                                           # nobody listens here: the other side's honest nodes
LOCK = f"/tmp/{os.environ.get('USER', 'user')}_ttru_bench.lock"
LOGS, OUT = "logs", "results-p5"
NODE, CLIENT = (os.path.abspath(join("..", "target", "release", x)) for x in ("node", "client"))

# Roles of the n = 19 identities: (group, licensed). Groups: "H1", "H2" honest, "B" split brain.
POPULATIONS = {
    "equal": [("H1", True)] * 6 + [("H2", True)] * 6 + [("B", True)] * 7,
    "weighted": [("H1", True)] * 4 + [("H1", False)] + [("H2", True)] * 3 + [("H2", False)] * 3
                + [("B", True)] * 3 + [("B", False)] * 5,
    "tiny": [("H1", True), ("H2", True), ("B", True), ("B", True)],      # development smoke test, 6 processes
}
CAPS = {"equal": (100_000, 1_000_000), "weighted": (100_000, 250_000), "tiny": (100_000, 1_000_000)}


def in_scope(args):
    if os.environ.get("TTRU_SCOPE") == "1" or not shutil.which("systemd-run"):
        return None
    cmd = ["systemd-run", "--user", "--scope", "--quiet", "-p", f"CPUQuota={args.cpu_quota}%",
           "-p", f"MemoryMax={args.mem_max}", sys.executable, *sys.argv]
    return subprocess.run(cmd, env=dict(os.environ, TTRU_SCOPE="1")).returncode


def parameters(args, side=None):
    """Node parameters; side = 1 or 2 for a Byzantine half."""
    entity_cap, class_cap = CAPS[args.population]
    consensus = {"timeout_delay": args.timeout_delay, "sync_retry_delay": 10_000, "epoch_length": 0,
                 "entity_cap_ppm": entity_cap, "class_cap_ppm": class_cap, "attest_guard": 500,
                 "l_max_ppm": 100_000, "governance_malicious": False}
    if args.scenario in ("s2", "s3") and side == 1:
        consensus["fork_vote_until"] = args.k
    if args.scenario in ("s2", "s3") and side == 2:
        consensus["fork_vote_from"] = args.k + 1
    if args.scenario == "s3":
        consensus["tc_outside_block"] = True
    return NodeParameters({"consensus": consensus,
                           "mempool": {"gc_depth": 50, "sync_retry_delay": 5_000, "sync_retry_nodes": 3,
                                       "batch_size": 15_000, "max_batch_delay": 10}})


def launch(cmd, log_file):
    return subprocess.Popen(shlex.split(cmd), stdout=subprocess.DEVNULL, stderr=open(log_file, "w"),
                            start_new_session=True)


def stop(procs):
    for p in procs:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGTERM)
    deadline = time.time() + 5
    for p in procs:
        try:
            p.wait(max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)


def run(args):
    for path in (NODE, CLIENT):
        if not os.path.exists(path):
            sys.exit(f"missing {path}: run `cargo build --release --features benchmark` in prototype/node first")
    for f in glob(".db-fork-*") + glob(".fork-*.json"):
        shutil.rmtree(f, ignore_errors=True) if os.path.isdir(f) else os.remove(f)
    shutil.rmtree(LOGS, ignore_errors=True)
    os.makedirs(LOGS)
    os.makedirs(OUT, exist_ok=True)

    roles = POPULATIONS[args.population]
    n = len(roles)
    key_files = [os.path.abspath(f".fork-key-{i}.json") for i in range(n)]
    for f in key_files:
        subprocess.run([NODE, "keys", "--filename", f], check=True)
    names = [Key.from_file(f).name for f in key_files]

    # Processes: (identity, side). Honest identities run on their side, Byzantine ones on both.
    procs = [(i, int(g[1])) for i, (g, _) in enumerate(roles) if g != "B"]
    procs += [(i, s) for s in (1, 2) for i, (g, _) in enumerate(roles) if g == "B"]
    if len(procs) > MAX_PROCESSES:
        sys.exit(f"{len(procs)} processes: above the lab limit of {MAX_PROCESSES}")
    port = {p: BASE_PORT + 3 * k for k, p in enumerate(procs)}

    def addresses(i, side):
        base = port.get((i, side), CLOSED_PORT + 3 * i)
        return tuple(f"127.0.0.1:{base + j}" for j in range(3))

    committees = {}
    for side in (1, 2):
        cons, front, mem = zip(*(addresses(i, side) for i in range(n)))
        committee = Committee(names, list(cons), list(front), list(mem), [1000] * n, [lic for _, lic in roles],
                              None)
        committees[side] = os.path.abspath(f".fork-committee-{side}.json")
        committee.print(committees[side])
    params = {}
    for tag, side in (("honest", None), ("b1", 1), ("b2", 2)):
        params[tag] = os.path.abspath(f".fork-parameters-{tag}.json")
        parameters(args, side).print(params[tag])

    running = []
    for k, (i, side) in enumerate(procs):
        tag = "honest" if roles[i][0] != "B" else f"b{side}"
        cmd = (f"{NODE} -vv run --keys {key_files[i]} --committee {committees[side]} "
               f"--store {os.path.abspath(f'.db-fork-{k}')} --parameters {params[tag]}")
        running.append(launch(cmd, join(LOGS, f"node-{i}-side{side}.log")))
    for side in (1, 2):                                       # up to two clients per side, on its first honest nodes
        honest = [p for p in procs if p[1] == side and roles[p[0]][0] != "B"][:2]
        for c, p in enumerate(honest):
            front = addresses(*p)[1]
            cmd = f"{CLIENT} {front} --size 512 --rate {args.rate} --timeout {args.timeout_delay}"
            running.append(launch(cmd, join(LOGS, f"client-side{side}-{c}.log")))
    try:
        time.sleep(args.duration)
    finally:
        stop(running)

    byz = {names[i] for i, (g, _) in enumerate(roles) if g == "B"}
    found = sum(len(re.findall(r"G1: found", open(f).read())) for f in glob(join(LOGS, "node-*.log")))
    row = dict(scenario=args.scenario, population=args.population, k=args.k, duration=args.duration,
               rep=args.rep, n=n, processes=len(procs), byzantine=len(byz), online_g1=found, pairs=[])
    sides = {s: [k for k, (i, side) in enumerate(procs) if side == s and roles[i][0] != "B"] for s in (1, 2)}
    for a, b in zip(sides[1][:2], sides[2][:2]):
        out = subprocess.run([NODE, "forensics", "--committee", committees[1], "--parameters", params["honest"],
                              "--store-a", f".db-fork-{a}", "--store-b", f".db-fork-{b}"],
                             capture_output=True, text=True)
        try:
            report = json.loads(out.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            report = {"error": (out.stderr or out.stdout)[-500:]}
        culprits = set(report.get("culprits", []))
        report.update(culprits=len(culprits), culprits_byzantine=len(culprits & byz),
                      honest_blamed=len(culprits - byz), a=procs[a][0], b=procs[b][0])
        row["pairs"].append(report)
    line = json.dumps(row)
    print(line, flush=True)
    with open(join(OUT, "fork.jsonl"), "a") as fh:
        fh.write(line + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenario", choices=["s1", "s2", "s3"], default="s1")
    ap.add_argument("--population", choices=sorted(POPULATIONS), default="equal")
    ap.add_argument("--k", type=int, default=20, help="s2/s3: last round side 1's Byzantine halves vote in")
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--rate", type=int, default=500, help="transactions per second of each of the four clients")
    ap.add_argument("--timeout-delay", type=int, default=1_000)
    ap.add_argument("--cpu-quota", type=int, default=1200, help="percent of one core (1200 = 12 cores)")
    ap.add_argument("--mem-max", default="12G")
    args = ap.parse_args()
    rc = in_scope(args)
    if rc is not None:
        sys.exit(rc)
    with open(LOCK, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit("another benchmark is running (one experiment at a time)")
        run(args)


if __name__ == "__main__":
    main()

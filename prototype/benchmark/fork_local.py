"""Protocol-level fork with split-brain members, then offline forensics (DESIGN.md §15.15), within the lab limits.

Every Byzantine member runs as two processes with one key, one per side. Side s's committee file maps the member to
its side-s process and the honest members of the other side to closed ports, so the two honest groups never hear of
each other (a partition for the whole run). Every process runs the unmodified protocol; the scenarios only add
experiment switches to the Byzantine halves:
  s1  nothing: wherever a Byzantine member leads, each side gets its own block and both halves vote (E1);
  s2  disjoint vote windows: side 1's halves vote only in rounds <= K, side 2's only in rounds > K, so the fork
      goes through TCs whose Byzantine signers report the genesis on side 2 (E3 only);
  s3  s2 with tc_outside_block on every process: the TC travels with the proposal but is not part of the block.
After the run, `node forensics` reads the stores of one honest node of each side. A single epoch (epoch_length 0),
or (DESIGN.md §15.24) epochs with --prephase: the forensics then judges the fork in the first epoch both sides committed
off the other's chain, replays each side's tables, and sweeps the other side's blocks for E2 by the judge's own tables
and by the tables the blocks name; the row also counts the blocks refused by H2 and left off the ledger by H4.

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
    # DESIGN.md §15.19 (mock review A2): quorums with slack and a Byzantine share well above 1/3, so the signers of a
    # QC are not forced and the forensics is not handed every Byzantine member by construction.
    "margin9": [("H1", True)] * 5 + [("H2", True)] * 5 + [("B", True)] * 9,     # B 47%, each side 14 votes (13 needed)
    "margin8": [("H1", True)] * 6 + [("H2", True)] * 5 + [("B", True)] * 8,     # B 42%, sides 14 and 13
}
CAPS = {"equal": (100_000, 1_000_000), "weighted": (100_000, 250_000), "tiny": (100_000, 1_000_000),
        "margin9": (100_000, 1_000_000), "margin8": (100_000, 1_000_000)}


def in_scope(args):
    if os.environ.get("TTRU_SCOPE") == "1" or not shutil.which("systemd-run"):
        return None
    cmd = ["systemd-run", "--user", "--scope", "--quiet", "-p", f"CPUQuota={args.cpu_quota}%",
           "-p", f"MemoryMax={args.mem_max}", sys.executable, *sys.argv]
    return subprocess.run(cmd, env=dict(os.environ, TTRU_SCOPE="1")).returncode


def parameters(args, side=None):
    """Node parameters; side = 1 or 2 for a Byzantine half."""
    entity_cap, class_cap = CAPS[args.population]
    consensus = {"timeout_delay": args.timeout_delay, "sync_retry_delay": 10_000, "epoch_length": args.epoch_length,
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
    store = {p: os.path.abspath(f".db-fork-{k}") for k, p in enumerate(procs)}

    if args.prephase > 0:
        # DESIGN.md §15.19: first everyone runs together (the Byzantine members as their side-1 process, one committee
        # file with every real address) for prephase seconds, through several epochs; then all stop, each Byzantine
        # store is copied to its side-2 process, and the split-brain run starts from the shared prefix.
        whole = os.path.abspath(".fork-committee-whole.json")
        cons, front, mem = zip(*(addresses(i, 1 if roles[i][0] in ("H1", "B") else 2) for i in range(n)))
        Committee(names, list(cons), list(front), list(mem), [1000] * n, [lic for _, lic in roles], None).print(whole)
        first = [(i, 1 if roles[i][0] in ("H1", "B") else 2) for i in range(n)]
        running = []
        for i, side in first:
            cmd = (f"{NODE} -vv run --keys {key_files[i]} --committee {whole} --store {store[(i, side)]} "
                   f"--parameters {params['honest']}")
            running.append(launch(cmd, join(LOGS, f"node-{i}-prephase.log")))
        for c, (i, side) in enumerate([p for p in first if roles[p[0]][0] != "B"][:4]):
            cmd = f"{CLIENT} {addresses(i, side)[1]} --size 512 --rate {args.rate} --timeout {args.timeout_delay}"
            running.append(launch(cmd, join(LOGS, f"client-prephase-{c}.log")))
        try:
            time.sleep(args.prephase)
        finally:
            stop(running)
        for i, (g, _) in enumerate(roles):
            if g == "B":
                shutil.copytree(store[(i, 1)], store[(i, 2)])
        if args.scenario in ("s2", "s3"):
            # DESIGN.md §15.24: with a prephase, --k counts from the highest round reached before the split.
            top = max((int(m) for f in glob(join(LOGS, "node-*-prephase.log"))
                       for m in re.findall(r"Committed B(\d+)", open(f).read())), default=0)
            args.k += top
            for tag, side in (("b1", 1), ("b2", 2)):
                parameters(args, side).print(params[tag])

    running = []
    for k, (i, side) in enumerate(procs):
        tag = "honest" if roles[i][0] != "B" else f"b{side}"
        cmd = (f"{NODE} -vv run --keys {key_files[i]} --committee {committees[side]} "
               f"--store {store[(i, side)]} --parameters {params[tag]}")
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
    logs = [open(f).read() for f in glob(join(LOGS, "node-*.log"))]
    found = sum(len(re.findall(r"G1: found", text)) for text in logs)
    h2_refused = sum(len(re.findall(r"\(H2\)", text)) for text in logs)
    h4_off_ledger = sum(len(re.findall(r"not on the ledger \(H4\)", text)) for text in logs)
    row = dict(scenario=args.scenario, population=args.population, k=args.k, duration=args.duration,
               prephase=args.prephase, epoch_length=args.epoch_length,
               rep=args.rep, n=n, processes=len(procs), byzantine=len(byz), online_g1=found,
               h2_refused=h2_refused, h4_off_ledger=h4_off_ledger, pairs=[])
    sides = {s: [k for k, (i, side) in enumerate(procs) if side == s and roles[i][0] != "B"] for s in (1, 2)}
    for a, b in zip(sides[1][:2], sides[2][:2]):
        out = subprocess.run([NODE, "forensics", "--committee", committees[1], "--parameters", params["honest"],
                              "--store-a", store[procs[a]], "--store-b", store[procs[b]]],
                             capture_output=True, text=True)
        try:
            report = json.loads(out.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            report = {"error": (out.stderr or out.stdout)[-500:]}
        culprits = set(report.get("culprits", []))
        report.update(culprits=len(culprits), culprits_byzantine=len(culprits & byz),
                      honest_blamed=len(culprits - byz), a=procs[a][0], b=procs[b][0])
        epochs = report.get("epochs") or {}
        ta, tb = epochs.pop("terminals_a", []), epochs.pop("terminals_b", [])
        shared = next((k for k, (x, y) in enumerate(zip(ta, tb)) if x != y), min(len(ta), len(tb)))
        epochs.update(terminals_a=len(ta), terminals_b=len(tb), terminals_shared=shared,
                      first_terminals_apart=[ta[shared] if shared < len(ta) else None,
                                             tb[shared] if shared < len(tb) else None])
        for sweep in epochs.values():
            if isinstance(sweep, dict) and "own_voters" in sweep:
                for kind in ("own", "named"):
                    voters = set(sweep.pop(f"{kind}_voters"))
                    sweep[f"{kind}_voters_honest"] = len(voters - byz)
                    sweep[f"{kind}_voters_byzantine"] = len(voters & byz)
        row["pairs"].append(report)
    line = json.dumps(row)
    print(line, flush=True)
    with open(join(OUT, args.out), "a") as fh:
        fh.write(line + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenario", choices=["s1", "s2", "s3"], default="s1")
    ap.add_argument("--population", choices=sorted(POPULATIONS), default="equal")
    ap.add_argument("--k", type=int, default=20,
                    help="s2/s3: last round side 1's Byzantine halves vote in (after --prephase: rounds after the split)")
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--prephase", type=int, default=0,
                    help="seconds of normal operation, everyone together, before the partition (0: split from genesis)")
    ap.add_argument("--epoch-length", type=int, default=0,
                    help="rounds per epoch (0: a single epoch; the evidence needs both sides in one epoch)")
    ap.add_argument("--rate", type=int, default=500, help="transactions per second of each of the four clients")
    ap.add_argument("--timeout-delay", type=int, default=1_000)
    ap.add_argument("--out", default="fork.jsonl", help="results file in results-p5/")
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

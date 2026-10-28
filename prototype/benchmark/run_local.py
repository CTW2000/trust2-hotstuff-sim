"""Local benchmark of the prototype on one machine, within the limits of the shared lab server.

Replaces upstream `fab local` (tmux sessions, one client per node, no resource limits):
- at most 31 nodes; clients run only on the first --clients nodes (default 4), each sending
  rate / clients transactions per second;
- the whole testbed (this script, the nodes and the clients) runs in one systemd user scope with a
  CPU quota and a memory cap, so a runaway run cannot take the server down;
- one experiment at a time: a lock file refuses a second concurrent run.
Results are parsed with the upstream LogParser and appended to results/.

Run from prototype/benchmark/ (after `cargo build --release --features benchmark` in prototype/node):
    python3 run_local.py --nodes 4 --rate 50000 --duration 30
"""
import argparse
import fcntl
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from glob import glob
from math import ceil
from os.path import join

from benchmark.config import Key, LocalCommittee, NodeParameters
from benchmark.logs import LogParser
from benchmark.utils import PathMaker

MAX_NODES = 31
BASE_PORT = 9000
LOCK = f"/tmp/{os.environ.get('USER', 'user')}_ttru_bench.lock"


def node_parameters(timeout_delay):
    return {
        "consensus": {"timeout_delay": timeout_delay, "sync_retry_delay": 10_000},
        "mempool": {"gc_depth": 50, "sync_retry_delay": 5_000, "sync_retry_nodes": 3,
                    "batch_size": 15_000, "max_batch_delay": 10},
    }


def in_scope(args):
    """Re-run this script inside a systemd user scope with CPU and memory limits (Linux only)."""
    if os.environ.get("TTRU_SCOPE") == "1" or not shutil.which("systemd-run"):
        return None
    cmd = ["systemd-run", "--user", "--scope", "--quiet", "-p", f"CPUQuota={args.cpu_quota}%",
           "-p", f"MemoryMax={args.mem_max}", sys.executable, *sys.argv]
    return subprocess.run(cmd, env=dict(os.environ, TTRU_SCOPE="1")).returncode


def binary(name):
    path = join(PathMaker.binary_path(), name)
    if not os.path.exists(path):
        sys.exit(f"missing {path}: run `cargo build --release --features benchmark` in prototype/node first")
    return os.path.abspath(path)


def run(args):
    node, client = binary("node"), binary("client")
    for f in glob(".db-*"):
        shutil.rmtree(f, ignore_errors=True)
    for f in glob(".*.json"):
        os.remove(f)
    shutil.rmtree(PathMaker.logs_path(), ignore_errors=True)
    os.makedirs(PathMaker.logs_path())
    os.makedirs(PathMaker.results_path(), exist_ok=True)

    key_files = [PathMaker.key_file(i) for i in range(args.nodes)]
    for f in key_files:
        subprocess.run([node, "keys", "--filename", f], check=True)
    names = [Key.from_file(f).name for f in key_files]
    committee = LocalCommittee(names, BASE_PORT)
    committee.print(PathMaker.committee_file())
    params = NodeParameters(node_parameters(args.timeout_delay))
    params.print(PathMaker.parameters_file())

    procs = []
    up = args.nodes - args.faults                            # faulty nodes are not booted
    clients = min(args.clients, up)
    rate_share = ceil(args.rate / clients)
    for i, addr in enumerate(committee.front[:clients]):
        cmd = f"{client} {addr} --size {args.tx_size} --rate {rate_share} --timeout {args.timeout_delay}"
        procs.append(launch(cmd, PathMaker.client_log_file(i)))
    for i in range(up):
        cmd = (f"{node} {'-vvv' if args.debug else '-vv'} run --keys {key_files[i]} "
               f"--committee {PathMaker.committee_file()} --store {PathMaker.db_path(i)} "
               f"--parameters {PathMaker.parameters_file()}")
        procs.append(launch(cmd, PathMaker.node_log_file(i)))

    try:
        time.sleep(2 * args.timeout_delay / 1000)            # let the nodes synchronize
        time.sleep(args.duration)
    finally:
        stop(procs)
    parser = LogParser.process(PathMaker.logs_path(), faults=args.faults)
    summary = parser.result()
    print(summary)
    with open(PathMaker.result_file(args.faults, args.nodes, args.rate, args.tx_size), "a") as fh:
        fh.write(summary)


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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--nodes", type=int, default=4)
    ap.add_argument("--faults", type=int, default=0)
    ap.add_argument("--clients", type=int, default=4)
    ap.add_argument("--rate", type=int, default=50_000)
    ap.add_argument("--tx-size", type=int, default=512)
    ap.add_argument("--duration", type=int, default=30)
    ap.add_argument("--timeout-delay", type=int, default=1_000)
    ap.add_argument("--cpu-quota", type=int, default=1200, help="percent of one core (1200 = 12 cores)")
    ap.add_argument("--mem-max", default="12G")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    if not 1 <= args.nodes <= MAX_NODES:
        sys.exit(f"--nodes must be between 1 and {MAX_NODES} (lab server limit)")
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

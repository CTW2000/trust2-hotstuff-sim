"""Local benchmark of the prototype on one machine, within the limits of the shared lab server.

Replaces upstream `fab local` (tmux sessions, one client per node, no resource limits):
- at most 31 nodes; clients run only on the first --clients nodes (default 4), each sending
  rate / clients transactions per second;
- the whole testbed (this script, the nodes and the clients) runs in one systemd user scope with a
  CPU quota and a memory cap, so a runaway run cannot take the server down;
- one experiment at a time: a lock file refuses a second concurrent run.
Results are parsed with the upstream LogParser and appended to results/.

Run from prototype/benchmark/ (after `cargo build --release --features benchmark` in prototype/node):
    python3 run_local.py --nodes 4 --rate 50000 --duration 30 --warmup 10
"""
import argparse
import fcntl
import json
import os
import random
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


def node_parameters(args):
    consensus = {"timeout_delay": args.timeout_delay, "sync_retry_delay": 10_000,
                 "epoch_length": args.epoch_length, "entity_cap_ppm": args.entity_cap_ppm,
                 "class_cap_ppm": args.class_cap_ppm, "attest_guard": args.attest_guard,
                 "l_max_ppm": args.l_max_ppm, "governance_malicious": args.governance_malicious}
    if args.leader_rule != "trust2":                         # the comparison of leader rules (DESIGN.md §15.12)
        consensus["leader_rule"] = args.leader_rule
    if args.g2_threshold:                                    # another G2 threshold, for comparisons (§15.13)
        consensus["g2_threshold"] = args.g2_threshold
    if args.g2_no_reputation:                                # ablation: convictions only exclude (§15.18)
        consensus["g2_no_reputation"] = True
    if args.aptos_failure_percent:                           # LeaderRule::Aptos threshold sweep (§15.20)
        consensus["aptos_failure_percent"] = args.aptos_failure_percent
    return {
        "consensus": consensus,
        "mempool": {"gc_depth": 50, "sync_retry_delay": 5_000, "sync_retry_nodes": 3,
                    "batch_size": 15_000, "max_batch_delay": 10},
    }


def base_weights(args):
    """The committee's base weights w_i and certification (DESIGN.md §9). By default equal and all certified, written
    to the committee file exactly as before. `lognormal:<sigma>` draws the weights with a fixed seed, so every run
    has the same committee; the uncertified members are spread through it (node indices 2, 5, 8, ... first)."""
    stakes = None
    if args.stakes != "equal":
        kind, sigma = args.stakes.split(":")
        if kind != "lognormal":
            sys.exit(f"unknown --stakes {args.stakes}")
        rng = random.Random(0)
        stakes = [max(1, round(1000 * rng.lognormvariate(0, float(sigma)))) for _ in range(args.nodes)]
    certified = None
    if args.uncertified:
        order = sorted(range(args.nodes), key=lambda i: (i % 3 != 2, i))
        uncertified = set(order[:args.uncertified])
        certified = [i not in uncertified for i in range(args.nodes)]
    entities = None
    if args.entity_size:                                     # the last booted nodes, where the switches start
        up = args.nodes - args.faults
        entities = [0 if i >= up - args.entity_size and i < up else None for i in range(args.nodes)]
    return stakes, certified, entities


def in_scope(args):
    """Re-run this script inside a systemd user scope with CPU and memory limits (Linux only)."""
    if os.environ.get("TTRU_SCOPE") == "1" or not shutil.which("systemd-run"):
        return None
    cmd = ["systemd-run", "--user", "--scope", "--quiet", "-p", f"CPUQuota={args.cpu_quota}%",
           "-p", f"MemoryMax={args.mem_max}", sys.executable, *sys.argv]
    return subprocess.run(cmd, env=dict(os.environ, TTRU_SCOPE="1")).returncode


# Binaries of the two builds: Trust 2.0 (this workspace) and the baseline, upstream plus the same fixes (baseline/).
BUILDS = {"trust2": join("..", "target", "release"), "baseline": join("..", "baseline", "target", "release")}


def binary(name, build="trust2"):
    path = join(BUILDS[build], name)
    if not os.path.exists(path):
        sys.exit(f"missing {path}: run `cargo build --release --features benchmark` in the {build} node crate first")
    return os.path.abspath(path)


def delays_file(args, committee):
    """The link-delay table of the run for network/src/delay.rs (DESIGN.md §14.1), or None for no delays."""
    if args.net == "none":
        return None
    with open(join("nets", f"{args.net}-n{args.nodes}-s0.json")) as fh:
        net = json.load(fh)
    addresses = {}
    for i in range(args.nodes):
        for address in (committee.consensus[i], committee.front[i], committee.mempool[i]):
            addresses[address] = i
    path = os.path.abspath(".delays.json")
    with open(path, "w") as fh:
        table = dict(addresses=addresses, base_ms=net["base_ms"], jitter_ms=net["jitter_ms"],
                     bandwidth_mbps=net["bandwidth_mbps"], late_p=args.late_p, late_ms=args.late_ms,
                     late_to=committee.consensus[:args.nodes])
        if args.fault == "outage":                           # region outage (DESIGN.md §15.22)
            start = int((args.start + args.fault_at) * 1000)
            table.update(outage=fault_nodes(args), outage_from_ms=start,
                         outage_until_ms=start + int(args.fault_for * 1000))
        json.dump(table, fh)
    return path


def fault_nodes(args):
    """The honest nodes a crash, restart or region outage hits (DESIGN.md §15.22): right after the client nodes, so
    that the clients, node 0's ledger and the experiment switches (taken from the last nodes) are not affected."""
    if args.fault == "none":
        return []
    first = min(args.clients, args.nodes - args.faults)
    return list(range(first, first + args.fault_nodes))


def run(args):
    node, client = binary("node", args.build), binary("client", args.build)
    observer = binary("observer") if args.otx_rate > 0 else None
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
    committee = LocalCommittee(names, BASE_PORT, *base_weights(args))
    committee.print(PathMaker.committee_file())
    params = NodeParameters(node_parameters(args))
    params.print(PathMaker.parameters_file())
    args.start = time.time()
    delays = delays_file(args, committee)
    hit = fault_nodes(args)
    if hit and (hit[-1] >= args.nodes - args.faults - sum((args.censor, args.equivocate, args.lie_nr,
                                                            args.invalid_block, args.regress, args.frame,
                                                            args.silent))):
        sys.exit("the fault nodes overlap the experiment switches")
    if args.fault == "outage" and not delays:
        sys.exit("a region outage needs a network (--net base or wide)")
    with open(join(PathMaker.logs_path(), "faulted.txt"), "w") as fh:
        fh.write(f"{args.fault} at {args.fault_at} s for {args.fault_for} s\n")
        fh.writelines(f"{names[i]}\n" for i in hit)

    procs, node_procs = [], {}
    up = args.nodes - args.faults                            # faulty nodes are not booted
    clients = min(args.clients, up)
    rate_share = ceil(args.rate / clients)
    for i, addr in enumerate(committee.front[:clients]):
        cmd = f"{client} {addr} --size {args.tx_size} --rate {rate_share} --timeout {args.timeout_delay}"
        procs.append(launch(cmd, PathMaker.client_log_file(i)))
    # Experiment switches, from the last booted node backwards: censors, equivocators, NR liars, invalid-block
    # leaders, then high-QC regressors.
    switches = {}
    tail = list(range(up - 1, -1, -1))
    roles = (("--censor", args.censor), ("--equivocate", args.equivocate), ("--lie-nr", args.lie_nr),
             ("--invalid-block", args.invalid_block), ("--regress", args.regress), ("--frame", args.frame),
             ("--silent", args.silent))
    for flag, count in roles:
        for i in tail[:count]:
            switches.setdefault(i, []).append(flag)
        tail = tail[count:]
    for i in range(up):
        censor = "".join(" " + f for f in switches.get(i, []))
        cmd = (f"{node} {'-vvv' if args.debug else '-vv'} run --keys {key_files[i]} "
               f"--committee {PathMaker.committee_file()} --store {PathMaker.db_path(i)} "
               f"--parameters {PathMaker.parameters_file()}{censor}")
        env = dict(os.environ, TTRU_DELAYS=delays, TTRU_NODE=str(i)) if delays else None
        procs.append(launch(cmd, PathMaker.node_log_file(i), env))
        node_procs[i] = (cmd, env, len(procs) - 1)
    if observer:
        targets = " ".join(committee.consensus[:up])
        cmd = f"{observer} --rate {args.otx_rate} {targets}"
        procs.append(launch(cmd, join(PathMaker.logs_path(), "observer.log")))

    try:
        end = time.time() + 2 * args.timeout_delay / 1000 + args.warmup + args.duration   # synchronize, then run
        if args.fault in ("crash", "restart"):               # crash or maintenance restart (DESIGN.md §15.22)
            time.sleep(max(0.0, args.start + args.fault_at - time.time()))
            for i in hit:
                try:
                    os.killpg(procs[node_procs[i][2]].pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if args.fault == "restart":
                time.sleep(args.fault_for)
                for i in hit:
                    cmd, env, k = node_procs[i]
                    procs[k] = launch(cmd, PathMaker.node_log_file(i), env, append=True)
        time.sleep(max(0.0, end - time.time()))
    finally:
        stop(procs)
    parser = LogParser.process(PathMaker.logs_path(), faults=args.faults, warmup=args.warmup)
    summary = parser.result()
    print(summary)
    with open(PathMaker.result_file(args.faults, args.nodes, args.rate, args.tx_size), "a") as fh:
        fh.write(summary)


def launch(cmd, log_file, env=None, append=False):
    return subprocess.Popen(shlex.split(cmd), stdout=subprocess.DEVNULL, stderr=open(log_file, "a" if append else "w"),
                            start_new_session=True, env=env)


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
    ap.add_argument("--build", choices=sorted(BUILDS), default="trust2", help="Trust 2.0 or the upstream baseline")
    ap.add_argument("--net", choices=["none", "base", "wide"], default="none", help="synthetic link delays")
    ap.add_argument("--late-p", type=float, default=0.0, help="probability that a message is late (model P)")
    ap.add_argument("--late-ms", type=float, default=5000.0, help="extra delay of a late message")
    ap.add_argument("--faults", type=int, default=0)
    ap.add_argument("--clients", type=int, default=4)
    ap.add_argument("--rate", type=int, default=50_000)
    ap.add_argument("--tx-size", type=int, default=512)
    ap.add_argument("--duration", type=int, default=30, help="measured seconds, after the warm-up")
    ap.add_argument("--warmup", type=int, default=0, help="seconds left out of the measurement at the start")
    ap.add_argument("--timeout-delay", type=int, default=1_000)
    ap.add_argument("--epoch-length", type=int, default=25, help="rounds per epoch (0: a single epoch)")
    ap.add_argument("--otx-rate", type=int, default=0, help="observed transactions per second (0: no observer)")
    ap.add_argument("--attest-guard", type=int, default=500, help="attestation guard in ms")
    ap.add_argument("--censor", type=int, default=0, help="number of booted nodes that censor victim accounts")
    ap.add_argument("--equivocate", type=int, default=0, help="number of booted nodes that vote twice (E1)")
    ap.add_argument("--lie-nr", type=int, default=0, help="number of booted nodes that lie about NR")
    ap.add_argument("--invalid-block", type=int, default=0, help="number of booted nodes that propose invalid blocks (E2)")
    ap.add_argument("--regress", type=int, default=0, help="number of booted nodes that regress their high QC (E3)")
    ap.add_argument("--frame", type=int, default=0, help="number of booted nodes that withhold votes and claim NR = 1")
    ap.add_argument("--silent", type=int, default=0, help="number of booted nodes that never propose (Byzantine)")
    ap.add_argument("--leader-rule", choices=["trust2", "none", "aptos", "failed"], default="trust2",
                    help="leader rule of the Trust 2.0 build, for comparisons (DESIGN.md §15.12)")
    ap.add_argument("--aptos-failure-percent", type=int, default=0,
                    help="failure threshold of the Aptos-style leader rule in percent (0: aptos-core's 10)")
    ap.add_argument("--g2-no-reputation", action="store_true",
                    help="ablation: G2 convictions only exclude from leading, reputation stays 1 (B_rep = 0)")
    ap.add_argument("--g2-threshold", type=int, default=0,
                    help="G2 CUSUM threshold ln(gamma) in millionths (0: the protocol's), for comparisons")
    ap.add_argument("--fault", choices=["none", "crash", "restart", "outage"], default="none",
                    help="benign fault of honest nodes (DESIGN.md §15.22): crash, maintenance restart, region outage")
    ap.add_argument("--fault-nodes", type=int, default=3, help="number of honest nodes the fault hits")
    ap.add_argument("--fault-at", type=float, default=40.0, help="seconds after the launch the fault starts")
    ap.add_argument("--fault-for", type=float, default=20.0,
                    help="seconds a restarted node is down, or a region outage lasts")
    ap.add_argument("--l-max-ppm", type=int, default=100_000, help="G1 suspension cap L_max in ppm")
    ap.add_argument("--governance-malicious", action="store_true", help="G1: an L4 without a fork evicts")
    ap.add_argument("--entity-cap-ppm", type=int, default=50_000, help="CapNorm entity cap in ppm, at most L_max")
    ap.add_argument("--class-cap-ppm", type=int, default=250_000,
                    help="class cap u_max of the uncertified members in ppm (1_000_000: none)")
    ap.add_argument("--stakes", default="equal", help="base weights: equal, or lognormal:<sigma> (fixed seed)")
    ap.add_argument("--uncertified", type=int, default=0, help="number of uncertified members (class cap applies)")
    ap.add_argument("--entity-size", type=int, default=0, help="the last booted nodes that belong to one entity")
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

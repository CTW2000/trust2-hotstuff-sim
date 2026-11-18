"""The one run of probe47.py that left no row: repetition 5, framers+late, Aptos-style rule, votes to all. The run
itself completed, but the log parser failed on it (a time-stamp pattern that crossed a line end, fixed in
benchmark/logs.py) and the next run overwrote its logs. The cell was run again after the batch, with the same
configuration (2026-11-18 10:49:20 to 10:52:32 UTC); this script records that run from the logs in logs/.
Run from prototype/benchmark/:  python3 probe47b.py >> results-probe47/run.log 2>&1 < /dev/null"""
import os
os.environ["TTRU_OUT"] = "results-probe47"
import p5

if __name__ == "__main__":      # the pool of the log parser starts a fork server that imports this file again
    p5.run("cmp_votes", dict(scenario="framers+late", build="trust2", nodes=31, net="base", epoch_length=25, rep=5,
                             leader_rule="aptos", g2_threshold=0, broadcast_votes=True, frame=6, late_p=0.1), 180,
           keep_logs="framers+late-aptos-all-5", parse_only=True)

"""DESIGN.md 15.42 and 15.43: the comparison of leader rules with votes to the next leader only (as cmpg) and with
votes to all members (as cmpb, the default of aptos-core), on the code with the fix of the table chain. Both arms
alternate inside every repetition, so they can be compared with each other; the four rules, the three scenarios and
the durations are those of cmpg. The logs are kept: the runs of the Aptos-style rule carry the trace that the test
in aptos-core checks (casestudy/aptos_leader_reputation_check.rs).
Run from prototype/benchmark/:  nohup python3 probe47.py > results-probe47/run.log 2>&1 &"""
import os
os.environ["TTRU_OUT"] = "results-probe47"
import p5


def main():
    scenarios = (("silent", dict(silent=3), 90), ("late", dict(late_p=0.1), 90),
                 ("framers+late", dict(frame=6, late_p=0.1), 180))
    for rep in range(1, 6):
        for name, faults, duration in scenarios:
            for rule in ("none", "aptos", "failed", "trust2"):
                for broadcast in (False, True):
                    p5.run("cmp_votes", dict(scenario=name, build="trust2", nodes=31, net="base", epoch_length=25,
                                             rep=rep, leader_rule=rule, g2_threshold=0, broadcast_votes=broadcast,
                                             **faults), duration,
                           keep_logs=f"{name}-{rule}-{'all' if broadcast else 'next'}-{rep}")


if __name__ == "__main__":
    main()

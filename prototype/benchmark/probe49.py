"""DESIGN.md 15.45: is the gain of forwarding the QC (15.44) a product of lateness that is independent per message?
Two models of lateness that is not: by sender (--late-slot 1: each second a node is slow with probability 0.1, and
then all of its consensus messages are 5 s late, to everyone, so all receivers miss the same votes), and bursts of
congestion (5% late, 40% for 5 s of every 30 s; 15.25). Three ways of sending votes, alternating inside each
repetition: to the next leader, to all members, to all members with the QC forwarded. The logs are kept.
Run from prototype/benchmark/:  nohup python3 probe49.py > results-probe49/run.log 2>&1 < /dev/null &"""
import os
os.environ["TTRU_OUT"] = "results-probe49"
import p5

ARMS = (("next", False, False), ("all", True, False), ("fwd", True, True))


def main():
    scenarios = (("slots", dict(late_p=0.1, late_slot=1), 90, ("none", "trust2")),
                 ("bursts", dict(late_p=0.05, burst_period=30, burst_len=5, burst_late_p=0.4), 120, ("trust2",)))
    for rep in range(1, 6):
        for name, faults, duration, rules in scenarios:
            for rule in rules:
                for arm, broadcast, forward in ARMS:
                    p5.run("cmp_corr", dict(scenario=name, build="trust2", nodes=31, net="base", epoch_length=25,
                                            rep=rep, leader_rule=rule, g2_threshold=0, broadcast_votes=broadcast,
                                            forward_qc=forward, **faults), duration,
                           keep_logs=f"{name}-{rule}-{arm}-{rep}")


if __name__ == "__main__":      # the pool of the log parser starts a fork server that imports this file again
    main()

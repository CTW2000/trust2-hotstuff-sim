"""DESIGN.md 15.44: with votes to all members, does it help that a member that assembles a QC sends it to the leader of
the next round? The two scenarios of probe47.py in which honest leaders were accused (10% late messages, without and
with framers), the same four rules, votes to all members in both arms, without and with the forward (--forward-qc),
alternating inside each repetition. The arm without the forward repeats the broadcast arm of probe47.py, so the two
batches can be put side by side. The logs are kept.
Run from prototype/benchmark/:  nohup python3 probe48.py > results-probe48/run.log 2>&1 < /dev/null &"""
import os
os.environ["TTRU_OUT"] = "results-probe48"
import p5


def main():
    scenarios = (("late", dict(late_p=0.1), 90), ("framers+late", dict(frame=6, late_p=0.1), 180))
    for rep in range(1, 6):
        for name, faults, duration in scenarios:
            for rule in ("none", "aptos", "failed", "trust2"):
                for forward in (False, True):
                    p5.run("cmp_forward", dict(scenario=name, build="trust2", nodes=31, net="base", epoch_length=25,
                                               rep=rep, leader_rule=rule, g2_threshold=0, broadcast_votes=True,
                                               forward_qc=forward, **faults), duration,
                           keep_logs=f"{name}-{rule}-{'fwd' if forward else 'all'}-{rep}")


if __name__ == "__main__":      # the pool of the log parser starts a fork server that imports this file again
    main()

"""DESIGN.md 15.45: from which share of lateness by sender on does the leader rule exclude honest leaders? With 10%
(probe49.py) a slow honest leader is accused about once in ten leads, which is the reference rate of the CUSUM, and
honest leaders are excluded. Here 2%, 5% and 10% (--late-slot 1: each second a node is slow with that probability,
and then all of its consensus messages are 5 s late), the protocol of the paper (votes to the next leader, Trust 2.0
rule), 300 s a run so that every leader leads some fifty times, five repetitions, the rates alternating. Besides the
usual columns those of localstat.py: leads, accusations and convictions of honest nodes, and the highest value a
CUSUM reached (the margin to the threshold). The logs are kept.
Run from prototype/benchmark/:  nohup python3 probe51.py > results-probe51/run.log 2>&1 < /dev/null &"""
import os
os.environ["TTRU_OUT"] = "results-probe51"
import p5


def main():
    for rep in range(1, 6):
        for share in (2, 5, 10):
            p5.run("slots_rate", dict(scenario=f"slots{share}", build="trust2", nodes=31, net="base", epoch_length=25,
                                      rep=rep, leader_rule="trust2", g2_threshold=0, late_p=share / 100, late_slot=1),
                   300, keep_logs=f"slots{share}-{rep}", extra=p5.local_stats)


if __name__ == "__main__":      # the pool of the log parser starts a fork server that imports this file again
    main()

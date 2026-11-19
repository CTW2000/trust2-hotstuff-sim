"""DESIGN.md 15.45: the threshold of the leader rule between 10^2 (three accused leads in a row convict) and 10^4
(six): 300 (four in a row: ln 300 = 5.70 lies between 3 ln 5 = 4.83 and 4 ln 5 = 6.44) and 10^3 (five: ln 10^3 =
6.91 lies between 6.44 and 8.05). The two sides of the trade, as probe52.py:
- lateness by sender at 5% and 10%, 300 s (at 10^2 and 10^4: probe51.py and probe52.py, on the same binaries);
- three silent leaders, no late messages, 180 s, with 10^2 again in the same batch as the reference.
Votes to the next leader, Trust 2.0 rule, five repetitions; the columns of localstat.py are added; the logs are kept.
Run from prototype/benchmark/:  nohup python3 probe53.py > results-probe53/run.log 2>&1 < /dev/null &"""
import os
os.environ["TTRU_OUT"] = "results-probe53"
import p5

LN300, LN1E3 = 5_703_782, 6_907_755     # in millionths; 0 stands for the protocol's ln 10^2


def main():
    base = dict(build="trust2", nodes=31, net="base", epoch_length=25, leader_rule="trust2")
    for rep in range(1, 6):
        for share in (5, 10):
            for threshold, tag in ((LN300, "300"), (LN1E3, "1e3")):
                p5.run("threshold", dict(scenario=f"slots{share}", rep=rep, g2_threshold=threshold,
                                         late_p=share / 100, late_slot=1, **base), 300,
                       keep_logs=f"slots{share}-{tag}-{rep}", extra=p5.local_stats)
        for threshold, tag in ((0, "1e2"), (LN300, "300"), (LN1E3, "1e3")):
            p5.run("threshold", dict(scenario="silent", rep=rep, g2_threshold=threshold, silent=3, **base), 180,
                   keep_logs=f"silent-{tag}-{rep}", extra=p5.local_stats)


if __name__ == "__main__":      # the pool of the log parser starts a fork server that imports this file again
    main()

"""DESIGN.md 15.45: the threshold of the leader rule, 10^2 (three accused leads in a row convict) against 10^4 (six),
on both sides of the trade.
- Lateness by sender at 2%, 5% and 10%, as probe51.py but with the threshold 10^4: how many honest leaders are still
  excluded? (The runs at 10^2 are those of probe51.py, on the same binaries.)
- Three silent leaders, no late messages, both thresholds alternating, 180 s: what does the slower conviction cost?
Votes to the next leader, Trust 2.0 rule, five repetitions; the columns of localstat.py are added; the logs are kept.
Run from prototype/benchmark/:  nohup python3 probe52.py > results-probe52/run.log 2>&1 < /dev/null &"""
import os
os.environ["TTRU_OUT"] = "results-probe52"
import p5

LN1E4 = 9_210_340       # ln 10^4 in millionths; 0 stands for the protocol's ln 10^2


def main():
    base = dict(build="trust2", nodes=31, net="base", epoch_length=25, leader_rule="trust2")
    for rep in range(1, 6):
        for share in (2, 5, 10):
            p5.run("threshold", dict(scenario=f"slots{share}", rep=rep, g2_threshold=LN1E4, late_p=share / 100,
                                     late_slot=1, **base), 300, keep_logs=f"slots{share}-1e4-{rep}",
                   extra=p5.local_stats)
        for threshold, tag in ((0, "1e2"), (LN1E4, "1e4")):
            p5.run("threshold", dict(scenario="silent", rep=rep, g2_threshold=threshold, silent=3, **base), 180,
                   keep_logs=f"silent-{tag}-{rep}", extra=p5.local_stats)


if __name__ == "__main__":      # the pool of the log parser starts a fork server that imports this file again
    main()

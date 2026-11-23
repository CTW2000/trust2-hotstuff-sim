"""DESIGN.md 15.49: should the leader rule count episodes instead of views? Mock review M1 (DA-M7, R3-W2): with one
observation per led view, a node that stalls for a few seconds and is drawn to lead several times is convicted, and
changing the threshold only trades that against the time a silent leader stays (15.45). The switch --g2-window W
leaves a leader's leads unobserved for W rounds after an adverse fact against it is counted. Windows 0 (the
protocol), 25 (one epoch) and 50 rounds at the protocol's threshold ln 300, on both sides of the trade:
- lateness by sender at 5% and 10% (each second a node is slow with that probability, and then all of its consensus
  messages are 5 s late), 300 s: how many honest leaders are excluded;
- three silent leaders, no late messages, 180 s: what the slower conviction costs.
Votes to the next leader, Trust 2.0 rule, five repetitions, the windows alternating; the columns of localstat.py are
added; the logs are kept.
Run from prototype/benchmark/:  nohup python3 probe54.py > results-probe54/run.log 2>&1 < /dev/null &"""
import os
os.environ["TTRU_OUT"] = "results-probe54"
import p5

WINDOWS = (0, 25, 50)


def main():
    base = dict(build="trust2", nodes=31, net="base", epoch_length=25, leader_rule="trust2", g2_threshold=0)
    for rep in range(1, 6):
        for share in (5, 10):
            for window in WINDOWS:
                p5.run("window", dict(scenario=f"slots{share}", rep=rep, g2_window=window, late_p=share / 100,
                                      late_slot=1, **base), 300, keep_logs=f"slots{share}-w{window}-{rep}",
                       extra=p5.local_stats)
        for window in WINDOWS:
            p5.run("window", dict(scenario="silent", rep=rep, g2_window=window, silent=3, **base), 180,
                   keep_logs=f"silent-w{window}-{rep}", extra=p5.local_stats)


if __name__ == "__main__":      # the pool of the log parser starts a fork server that imports this file again
    main()

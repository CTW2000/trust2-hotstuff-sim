# xb

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | frame | late_p | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | accusations_honest | accusations_faulty | honest_cut |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| framers+late | trust2 | 10 | base | 50 | 2 | 0.1 | 6941 [6444–7438] | 2492 [2149–2835] | 6934 [6432–7436] | 3058.5 [2705–3412] | 195 [192–198] | 290.5 [285–296] | 433.5 [413–454] | 1.75 [1.7–1.8] | 9 | 1303 [1067–1539] | 2778 [2198–3358] | 7 | 1 | 0 |
| late | trust2 | 10 | base | 50 |  | 0.1 | 9784 [9765–9803] | 573 [542–604] | 9782 [9762–9802] | 999 [934–1064] | 110 [102–118] | 206.5 [192–221] | 1123 [1048–1198] | 4.5 [4.2–4.8] | 22.5 [21–24] | 297.5 [288–307] | 3755 [3294–4216] | 7.5 [7–8] |  | 0 |

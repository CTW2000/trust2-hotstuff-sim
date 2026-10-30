# xb

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | frame | late_p | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | honest_cut | accusations_honest |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| framers+late | trust2 | 10 | base | 50 | 2 | 0.1 | 8053 [8044–8062] | 2504 [2468–2540] | 8028 [8017–8039] | 3043 [3012–3074] | 187.5 [187–188] | 305 [300–310] | 465.5 [457–474] | 1.85 [1.8–1.9] | 10 | 267 [191–343] | 1637.5 [1062–2213] | 0 |  |
| late | trust2 | 10 | base | 50 |  | 0.1 | 9979.5 [9962–9997] | 545.5 [510–581] | 9968 [9961–9975] | 1001 [958–1044] | 118.5 [112–125] | 218.5 [204–233] | 1073.5 [1017–1130] | 4.3 [4.1–4.5] | 22 [21–23] | 416.5 [293–540] | 3901 [3274–4528] | 0 | 2 |

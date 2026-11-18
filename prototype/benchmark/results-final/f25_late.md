# f25_late

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | late_p | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | client_misses | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | honest_cut | accusations_honest |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| late | baseline | 31 | base | 25 | 0.1 | 9989 [9974–10106] | 343.5 [309–512] | 9983.5 [9961–10073] | 557 [508–751] | 19 [14–21] | 0 | 49 [35–56] | 648.5 [623–700] | 6.5 [6.2–7] | 0 | 0 | 0 | 0 |  |
| late | trust2 | 31 | base | 25 | 0.1 | 9980.5 [9947–10214] | 383 [337–429] | 9971.5 [9876–10141] | 770.5 [619–901] | 25.5 [22–32] | 0 | 58.5 [47–68] | 567 [508–609] | 5.7 [5.1–6.1] | 23 [21–25] | 369 [287–588] | 2856 [2019–5077] | 0 | 7 [3–9] |

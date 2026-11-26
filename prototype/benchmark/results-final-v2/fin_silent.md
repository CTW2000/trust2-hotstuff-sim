# fin_silent

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | faults | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | client_misses | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | honest_cut | accusations_faulty | g2_excluded_faulty | min_r_faulty | accusations_honest | faulty_share_end |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| silent | baseline | 31 | base | 25 | 3 | 9879 [7430–10110] | 351 [334–1072] | 9834 [7421–10078] | 1196 [1110–1822] | 57 [53–58] | 0 | 64 [60–65] | 325 [318–375] | 3.2 [3.2–3.8] | 0 | 0 | 0 | 0 |  |  |  |  |  |
| silent | trust2 | 31 | base | 25 | 3 | 9855 [9634–9906] | 408 [289–488] | 9741 [9632–9905] | 1025 [615–1171] | 25 [18–32] | 0 | 31 [26–40] | 594 [512–641] | 5.9 [5.1–6.4] | 24 [21–26] | 66 [66–68] | 1079 [76–1098] | 0 | 15 [12–20] | 3 | 900000 | 1 | 0.0881 [0.0879–0.0891] |

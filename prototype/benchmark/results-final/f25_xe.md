# f25_xe

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | equivocate | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | client_misses | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | honest_cut | g1_levels_faulty | g1_suspensions_faulty | faulty_share_end | entity_size | base_max_ppm | base_min_ppm | faulty_base_ppm | g1_levels_honest | g1_suspensions_honest |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| separate | trust2 | 31 | base | 25 |  | 9976 | 228 [227–229] | 9960 [9957–9963] | 338 [337–339] | 0 | 0 | 0 | 629.5 [628–631] | 9 | 26 | 67 | 70 [69–71] | 0 |  |  |  |  |  |  |  |  |  |
| separate+equivocator | trust2 | 31 | base | 25 | 1 | 9980 [9978–9982] | 232 | 9971 [9968–9974] | 343 | 0 | 0 | 0 | 622.5 [622–623] | 8.9 | 25 | 67 | 71.5 [71–72] | 0 | 3 | 2 | 0.0323 |  |  |  |  |  |  |
| bound | trust2 | 31 | base | 25 |  | 9981.5 [9980–9983] | 230.5 [230–231] | 9981 [9980–9982] | 341 | 0 | 0 | 0 | 623 [622–624] | 8.9 | 25 | 66.5 [66–67] | 71.5 [71–72] | 0 |  |  |  | 5 | 36538 | 10000 | 0 |  |  |
| bound+equivocator | trust2 | 31 | base | 25 | 1 | 9984 [9981–9987] | 229 [228–230] | 9972.5 [9964–9981] | 339.5 [338–341] | 0 | 0 | 0 | 627.5 [625–630] | 8.95 [8.9–9] | 25.5 [25–26] | 66.5 [66–67] | 70.5 [70–71] | 0 | 3 | 2 | 0.01 | 5 | 36538 | 10000 | 10000 | 12 | 8 |

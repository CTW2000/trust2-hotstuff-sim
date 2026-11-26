# f25_xe

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | equivocate | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | client_misses | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | honest_cut | g1_levels_faulty | g1_suspensions_faulty | faulty_share_end | entity_size | base_max_ppm | base_min_ppm | faulty_base_ppm | g1_levels_honest | g1_suspensions_honest |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| separate | trust2 | 31 | base | 25 |  | 9985 [9982–9988] | 228.5 [228–229] | 9971 [9970–9972] | 339 [338–340] | 0 | 0 | 0 | 632 [631–633] | 9 | 26 | 66.5 [66–67] | 70.5 [70–71] | 0 |  |  |  |  |  |  |  |  |  |
| separate+equivocator | trust2 | 31 | base | 25 | 1 | 9982 | 231.5 [231–232] | 9968 [9962–9974] | 343 | 0 | 0 | 0 | 622 [620–624] | 8.9 | 25 | 66.5 [66–67] | 69 | 0 | 3 | 2 | 0.0323 |  |  |  |  |  |  |
| bound | trust2 | 31 | base | 25 |  | 9985 [9983–9987] | 231 [230–232] | 9976 [9975–9977] | 341.5 [341–342] | 0 | 0 | 0 | 620.5 [620–621] | 8.9 | 25 | 67 | 75 [73–77] | 0 |  |  |  | 5 | 36538 | 10000 | 0 |  |  |
| bound+equivocator | trust2 | 31 | base | 25 | 1 | 9980.5 [9976–9985] | 230.5 [229–232] | 9977.5 [9971–9984] | 342 [340–344] | 0 | 0 | 0 | 624 [620–628] | 8.95 [8.9–9] | 25.5 [25–26] | 67 | 77 [70–84] | 0 | 3 | 2 | 0.01 | 5 | 36538 | 10000 | 10000 | 12 | 8 |

# f25_xe

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | equivocate | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | client_misses | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | honest_cut | g1_levels_faulty | g1_suspensions_faulty | entity_size | base_max_ppm | base_min_ppm | faulty_base_ppm | g1_levels_honest | g1_suspensions_honest |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| separate | trust2 | 31 | base | 25 |  | 9979.5 [9977–9982] | 228 [227–229] | 9967.5 [9967–9968] | 333 [331–335] | 0 | 0 | 0 | 630 [627–633] | 9 | 26 | 66.5 [66–67] | 70 [69–71] | 0 |  |  |  |  |  |  |  |  |
| separate+equivocator | trust2 | 31 | base | 25 | 1 | 9982.5 [9982–9983] | 229.5 [229–230] | 9970.5 [9968–9973] | 336 [335–337] | 0 | 0 | 0 | 624.5 [624–625] | 8.9 | 25 | 66.5 [66–67] | 69.5 [69–70] | 0 | 3 | 2 |  |  |  |  |  |  |
| bound | trust2 | 31 | base | 25 |  | 9980.5 [9977–9984] | 228 | 9971 [9969–9973] | 334.5 [334–335] | 0 | 0 | 0 | 629 [627–631] | 9 | 26 | 66.5 [66–67] | 70.5 [69–72] | 0 |  |  | 5 | 36538 | 10000 | 0 |  |  |
| bound+equivocator | trust2 | 31 | base | 25 | 1 | 9978.5 [9974–9983] | 227.5 [227–228] | 9973.5 [9971–9976] | 333 | 0 | 0 | 0 | 631.5 [631–632] | 9 | 26 | 67 | 69 | 0 | 3 | 2 | 5 | 36538 | 10000 | 10000 | 12 | 8 |

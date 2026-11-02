# xe

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | equivocate | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | honest_cut | g1_levels_faulty | g1_suspensions_faulty | entity_size | base_max_ppm | base_min_ppm | faulty_base_ppm | g1_levels_honest | g1_suspensions_honest |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| separate | trust2 | 31 | base | 50 |  | 9981.5 [9978–9985] | 225.5 [225–226] | 9976.5 [9969–9984] | 331 [330–332] | 0 | 0 | 639 [638–640] | 9.1 | 13 | 66.5 [66–67] | 68.5 [68–69] | 0 |  |  |  |  |  |  |  |  |
| separate+equivocator | trust2 | 31 | base | 50 | 1 | 9984 | 230.5 [230–231] | 9966.5 [9965–9968] | 337 | 0 | 0 | 622.5 [622–623] | 8.9 | 13 | 66 [65–67] | 68.5 [68–69] | 0 | 2 | 2 |  |  |  |  |  |  |
| bound | trust2 | 31 | base | 50 |  | 9977.5 [9975–9980] | 227 [226–228] | 9969.5 [9969–9970] | 333 [331–335] | 0 | 0 | 631 [629–633] | 9 | 13 | 67 | 70 [69–71] | 0 |  |  | 5 | 36538 | 10000 | 0 |  |  |
| bound+equivocator | trust2 | 31 | base | 50 | 1 | 9981.5 [9979–9984] | 228 | 9970 [9967–9973] | 334 | 0 | 0 | 631 | 9 | 13 | 66.5 [66–67] | 71 [69–73] | 0 | 2 | 2 | 5 | 36538 | 10000 | 10000 | 8 | 8 |

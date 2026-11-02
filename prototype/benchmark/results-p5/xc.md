# xc

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | stakes | uncertified | entity_cap_ppm | class_cap_ppm | faults | equivocate | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | honest_cut | base_max_ppm | base_min_ppm | faulty_base_ppm | accusations_faulty | g2_excluded_faulty | min_r_faulty | g1_levels_faulty | g1_suspensions_faulty | accusations_honest |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| normal | trust2 | 31 | base | 50 | lognormal:1 | 10 | 50000 | 250000 |  |  | 9990 [9989–9991] | 219.5 [218–221] | 9976.5 [9976–9977] | 324.5 [323–326] | 0 | 0 | 655 [652–658] | 9.35 [9.3–9.4] | 14 | 66.5 [66–67] | 69.5 [69–70] | 0 | 50000 | 2624 | 0 |  |  |  |  |  |  |
| silent | trust2 | 31 | base | 50 | lognormal:1 | 10 | 50000 | 250000 | 3 |  | 9313.5 [8945–9682] | 613.5 [492–735] | 9124 [8685–9563] | 1370 [1258–1482] | 35 | 43 | 243.5 [242–245] | 3.5 | 5 | 67.5 [67–68] | 579.5 [75–1084] | 0 | 50000 | 2624 | 112991 | 21 | 2.5 [2–3] | 900000 |  |  | 1 |
| equivocators | trust2 | 31 | base | 50 | lognormal:1 | 10 | 50000 | 250000 |  | 3 | 9981.5 [9979–9984] | 223.5 [223–224] | 9973.5 [9972–9975] | 328.5 [328–329] | 0 | 0 | 642.5 [642–643] | 9.2 | 13 | 66 | 69 | 0 | 50000 | 2624 | 112991 |  |  |  | 14 | 2 |  |

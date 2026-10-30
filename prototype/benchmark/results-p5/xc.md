# xc

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | stakes | uncertified | entity_cap_ppm | class_cap_ppm | faults | equivocate | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | honest_cut | base_max_ppm | base_min_ppm | faulty_base_ppm | accusations_faulty | g2_excluded_faulty | min_r_faulty | g1_levels_faulty | g1_suspensions_faulty |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| normal | trust2 | 31 | base | 50 | lognormal:1 | 10 | 50000 | 250000 |  |  | 9981.5 [9978–9985] | 220.5 [215–226] | 9978 [9976–9980] | 325 [318–332] | 0 | 0 | 651.5 [635–668] | 9.3 [9.1–9.5] | 13.5 [13–14] | 66.5 [66–67] | 69 | 0 | 50000 | 2624 | 0 |  |  |  |  |  |
| silent | trust2 | 31 | base | 50 | lognormal:1 | 10 | 50000 | 250000 | 3 |  | 9157 [8283–10031] | 356 [353–359] | 9129.5 [8244–10015] | 991 [933–1049] | 31 | 38 | 286.5 [285–288] | 4.1 | 6 | 66.5 [66–67] | 68.5 [68–69] | 0 | 50000 | 2624 | 112991 | 19 | 3 | 900000 |  |  |
| equivocators | trust2 | 31 | base | 50 | lognormal:1 | 10 | 50000 | 250000 |  | 3 | 9984 | 219 [218–220] | 9969 [9965–9973] | 323 [322–324] | 0 | 0 | 654.5 [654–655] | 9.35 [9.3–9.4] | 14 | 66.5 [66–67] | 69 | 0 | 50000 | 2624 | 112991 |  |  |  | 15 | 2 |

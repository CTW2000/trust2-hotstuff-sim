# f25_xc

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | stakes | uncertified | entity_cap_ppm | class_cap_ppm | faults | equivocate | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | client_misses | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | honest_cut | base_max_ppm | base_min_ppm | faulty_base_ppm | accusations_faulty | g2_excluded_faulty | min_r_faulty | accusations_honest | faulty_share_end | g1_levels_faulty | g1_suspensions_faulty |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| normal | trust2 | 31 | base | 25 | lognormal:1 | 10 | 50000 | 250000 |  |  | 9978 | 221.5 [220–223] | 9969 [9968–9970] | 331.5 [330–333] | 0 | 0 | 0 | 649 [642–656] | 9.3 [9.2–9.4] | 26.5 [26–27] | 67.5 [67–68] | 70 [69–71] | 0 | 50000 | 2624 | 0 |  |  |  |  |  |  |  |
| silent | trust2 | 31 | base | 25 | lognormal:1 | 10 | 50000 | 250000 | 3 |  | 10241 [9828–10654] | 417 [380–454] | 9966.5 [9794–10139] | 1095.5 [998–1193] | 22 [20–24] | 0 | 27.5 [26–29] | 363.5 [353–374] | 5.15 [5–5.3] | 15 | 68 | 1083 [1082–1084] | 0 | 50000 | 2624 | 112991 | 13 [12–14] | 3 | 900000 | 1 | 0.1029 |  |  |
| equivocators | trust2 | 31 | base | 25 | lognormal:1 | 10 | 50000 | 250000 |  | 3 | 9990 [9988–9992] | 219 [216–222] | 9982 [9981–9983] | 328 [324–332] | 0 | 0 | 0 | 656.5 [648–665] | 9.4 [9.3–9.5] | 26.5 [26–27] | 67.5 [67–68] | 70.5 [70–71] | 0 | 50000 | 2624 | 112991 |  |  |  |  | 0.113 | 9 | 2 |

# f25_xc

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | stakes | uncertified | entity_cap_ppm | class_cap_ppm | faults | equivocate | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | client_misses | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | honest_cut | base_max_ppm | base_min_ppm | faulty_base_ppm | accusations_faulty | g2_excluded_faulty | min_r_faulty | g1_levels_faulty | g1_suspensions_faulty |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| normal | trust2 | 31 | base | 25 | lognormal:1 | 10 | 50000 | 250000 |  |  | 9982.5 [9980–9985] | 222.5 [221–224] | 9974.5 [9973–9976] | 327 [325–329] | 0 | 0 | 0 | 649 [646–652] | 9.25 [9.2–9.3] | 26.5 [26–27] | 67 | 93.5 [89–98] | 0 | 50000 | 2624 | 0 |  |  |  |  |  |
| silent | trust2 | 31 | base | 25 | lognormal:1 | 10 | 50000 | 250000 | 3 |  | 8870.5 [8791–8950] | 832 [585–1079] | 8618.5 [8467–8770] | 1560.5 [1324–1797] | 35.5 [35–36] | 0 | 41.5 [41–42] | 256.5 [251–262] | 3.65 [3.6–3.7] | 10.5 [10–11] | 69 [68–70] | 579 [71–1087] | 0 | 50000 | 2624 | 112991 | 21.5 [21–22] | 2 | 900000 |  |  |
| equivocators | trust2 | 31 | base | 25 | lognormal:1 | 10 | 50000 | 250000 |  | 3 | 9978.5 [9978–9979] | 223 | 9964 [9961–9967] | 328 | 0 | 0 | 0 | 644.5 [644–645] | 9.2 | 26 | 67 | 93 [71–115] | 0 | 50000 | 2624 | 112991 |  |  |  | 9 | 2 |

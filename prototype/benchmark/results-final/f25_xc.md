# f25_xc

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | stakes | uncertified | entity_cap_ppm | class_cap_ppm | faults | equivocate | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | client_misses | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | honest_cut | base_max_ppm | base_min_ppm | faulty_base_ppm | accusations_faulty | accusations_honest | g2_excluded_faulty | min_r_faulty | faulty_share_end | g1_levels_faulty | g1_suspensions_faulty |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| normal | trust2 | 31 | base | 25 | lognormal:1 | 10 | 50000 | 250000 |  |  | 9976 [9974–9978] | 222.5 [222–223] | 9968.5 [9966–9971] | 331.5 [331–332] | 0 | 0 | 0 | 643.5 [642–645] | 9.2 | 26 | 67 | 69.5 [69–70] | 0 | 50000 | 2624 | 0 |  |  |  |  |  |  |  |
| silent | trust2 | 31 | base | 25 | lognormal:1 | 10 | 50000 | 250000 | 3 |  | 9688.5 [9429–9948] | 562.5 [377–748] | 9451.5 [9195–9708] | 974.5 [638–1311] | 18 [14–22] | 0 | 25.5 [22–29] | 384.5 [352–417] | 5.5 [5–6] | 16 [15–17] | 67 | 571.5 [69–1074] | 0 | 50000 | 2624 | 112991 | 13.5 [11–16] | 1 | 3 | 900000 | 0.1029 |  |  |
| equivocators | trust2 | 31 | base | 25 | lognormal:1 | 10 | 50000 | 250000 |  | 3 | 9979 [9975–9983] | 222 [218–226] | 9966.5 [9958–9975] | 331.5 [326–337] | 0 | 0 | 0 | 648 [638–658] | 9.25 [9.1–9.4] | 26.5 [26–27] | 66.5 [66–67] | 75.5 [70–81] | 0 | 50000 | 2624 | 112991 |  |  |  |  | 0.113 | 9 | 2 |

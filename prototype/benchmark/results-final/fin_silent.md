# fin_silent

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | faults | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | client_misses | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | honest_cut | accusations_faulty | accusations_honest | g2_excluded_faulty | min_r_faulty | faulty_share_end |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| silent | baseline | 31 | base | 25 | 3 | 7556 [7504–9872] | 354 [330–1809] | 7553 [7501–9842] | 1191 [1069–2466] | 57 [53–58] | 0 | 64 [60–66] | 334 [321–372] | 3.3 [3.2–3.7] | 0 | 0 | 0 | 0 |  |  |  |  |  |
| silent | trust2 | 31 | base | 25 | 3 | 9521 [7701–9675] | 435 [301–619] | 9486 [7640–9640] | 1095 [635–1478] | 27 [22–47] | 0 | 34 [29–52] | 570 [417–619] | 5.7 [4.2–6.2] | 23 [17–25] | 67 | 1074 [72–1086] | 0 | 17 [14–27] | 1 | 3 | 900000 | 0.0879 [0.0879–0.0882] |

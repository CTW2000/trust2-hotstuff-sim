# f25_xb

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | frame | late_p | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | client_misses | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | accusations_honest | honest_cut | accusations_faulty |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| framers+late | trust2 | 10 | base | 25 | 2 | 0.1 | 6936 [6860–7012] | 2395 [2142–2648] | 6930.5 [6857–7004] | 2937.5 [2720–3155] | 196 [195–197] | 0 | 295 [294–296] | 433 [426–440] | 1.75 [1.7–1.8] | 17 | 1064 | 2037 [2014–2060] | 6.5 [4–9] | 0 | 2 |
| late | trust2 | 10 | base | 25 |  | 0.1 | 9902.5 [9872–9933] | 466 [445–487] | 9883 [9872–9894] | 901 [891–911] | 108 [105–111] | 0 | 201.5 [191–212] | 1139.5 [1124–1155] | 4.55 [4.5–4.6] | 45.5 [45–46] | 199.5 [174–225] | 2381.5 [2014–2749] | 7.5 [6–9] | 0 |  |

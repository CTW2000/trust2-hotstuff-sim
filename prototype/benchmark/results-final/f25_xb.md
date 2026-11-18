# f25_xb

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | frame | late_p | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | client_misses | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | accusations_honest | accusations_faulty | honest_cut | faulty_share_end |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| framers+late | trust2 | 10 | base | 25 | 2 | 0.1 | 7193 [6912–7474] | 1947 [1933–1961] | 7180.5 [6893–7468] | 3638 [3609–3667] | 195.5 [195–196] | 0 | 290.5 [287–294] | 417 [409–425] | 1.65 [1.6–1.7] | 17 | 1065 | 2038 [2037–2039] | 7.5 [6–9] | 1 | 0 | 0.2 |
| late | trust2 | 10 | base | 25 |  | 0.1 | 9877 [9864–9890] | 631 [570–692] | 9875 [9860–9890] | 1254 [1215–1293] | 119 [110–128] | 0 | 200.5 [193–208] | 1043 [982–1104] | 4.15 [3.9–4.4] | 42 [40–44] | 257.5 [210–305] | 2073 [2031–2115] | 15.5 [12–19] |  | 0 |  |

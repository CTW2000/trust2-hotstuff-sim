# f25_xb

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | frame | late_p | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | client_misses | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | accusations_honest | accusations_faulty | honest_cut | faulty_share_end |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| framers+late | trust2 | 10 | base | 25 | 2 | 0.1 | 7101 [7100–7102] | 2105 [1915–2295] | 7095 [7090–7100] | 3054 [2677–3431] | 193.5 [193–194] | 0 | 292.5 [292–293] | 431.5 [430–433] | 1.7 | 17 | 1036.5 [1010–1063] | 1581.5 [1126–2037] | 5.5 [4–7] | 3 | 0 | 0.2 |
| late | trust2 | 10 | base | 25 |  | 0.1 | 9786.5 [9714–9859] | 532 [451–613] | 9778.5 [9701–9856] | 1092 [965–1219] | 116 [108–124] | 0 | 204.5 [203–206] | 1076.5 [1040–1113] | 4.35 [4.2–4.5] | 43.5 [42–45] | 214.5 [196–233] | 1766 [1518–2014] | 10 [8–12] |  | 0 |  |

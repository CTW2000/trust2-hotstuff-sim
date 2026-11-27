# f25_late

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | late_p | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | client_misses | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | honest_cut | accusations_honest |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| late | baseline | 31 | base | 25 | 0.1 | 9996 [9952–10100] | 362.5 [293–388] | 9982.5 [9951–10049] | 588 [468–632] | 18 [11–22] | 0 [0–4] | 45 [29–59] | 647.5 [610–722] | 6.5 [6.1–7.2] | 0 | 0 | 0 | 0 |  |
| late | trust2 | 31 | base | 25 | 0.1 | 9987.5 [9963–10092] | 362 [339–488] | 9975.5 [9963–10054] | 599.5 [542–763] | 20 [15–27] | 0 | 47 [38–62] | 631 [576–669] | 6.3 [5.8–6.7] | 25 [23–27] | 322.5 [273–408] | 4765 [584–5099] | 0 | 1 [1–2] |

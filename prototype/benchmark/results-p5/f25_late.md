# f25_late

Median over the runs (range in brackets).

| scenario | build | nodes | net | epoch_length | late_p | consensus_tps | consensus_latency_ms | e2e_tps | e2e_latency_ms | timeouts | client_misses | timeout_rounds | top_round | rounds_per_s | epochs | lag_median_ms | lag_max_ms | honest_cut | accusations_honest |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| late | baseline | 31 | base | 25 | 0.1 | 9985.5 [9968–10097] | 336 [304–391] | 9978.5 [9960–9994] | 557.5 [502–621] | 16.5 [12–19] | 0 [0–4] | 43.5 [32–50] | 661 [628–709] | 6.6 [6.3–7.1] | 0 | 0 | 0 | 0 |  |
| late | trust2 | 31 | base | 25 | 0.1 | 9980 [9961–10068] | 355 [321–463] | 9968 [9953–10041] | 595.5 [510–697] | 19.5 [12–24] | 0 [0–4] | 47.5 [35–54] | 635.5 [600–687] | 6.35 [6–6.9] | 25.5 [24–28] | 319 [300–339] | 2495 [918–4955] | 0 | 1 |

## results-probe50/scale100_votes.csv: 15 runs

### none, rule trust2 (5 / 5 / 5 runs)

| metric | next | all | fwd |
|---|---|---|---|
| timeouts | 0 | 0 | 0 |
| rounds_per_s | 9.2 [9.1-9.3] | 8.7 [8.7-8.8] | 8.8 [8.7-8.8] |
| consensus_latency_ms | 228 [223-228] | 219 [218-220] | 218 [216-220] |
| e2e_latency_ms | 338 [332-340] | 335 [333-337] | 334 [332-337] |
| accusations_honest | 0 | 0 | 0 |
| g2_excluded_honest | 0 | 0 | 0 |
| cores | 4.21 [4.19-4.28] | 10.45 [10.36-10.56] | 10.69 [10.50-10.75] |
| throttled_pct | 0.0 | 14.0 [10.5-16.5] | 17.0 [13.0-20.5] |
| lo_mb_s | 113.3 [113.2-113.5] | 136.2 [136.1-136.5] | 143.4 [142.9-143.9] |

- all against next: timeouts p=1.000; rounds_per_s p=0.008 -5.4% [-6.5%, -4.3%]; consensus_latency_ms p=0.008 -3.9% [-4.4%, -1.8%]; e2e_latency_ms p=0.381 -0.9% [-1.5%, +0.9%]; accusations_honest p=1.000; g2_excluded_honest p=1.000; cores p=0.008 +148.2% [+144.2%, +150.8%]; throttled_pct p=0.008; lo_mb_s p=0.008 +20.2% [+20.0%, +20.5%]
- fwd against next: timeouts p=1.000; rounds_per_s p=0.008 -4.3% [-5.4%, -3.3%]; consensus_latency_ms p=0.008 -4.4% [-5.3%, -2.2%]; e2e_latency_ms p=0.222 -1.2% [-2.1%, +0.6%]; accusations_honest p=1.000; g2_excluded_honest p=1.000; cores p=0.008 +153.9% [+148.8%, +155.3%]; throttled_pct p=0.008; lo_mb_s p=0.008 +26.6% [+26.1%, +27.0%]
- fwd against all: timeouts p=1.000; rounds_per_s p=0.206 +1.1% [+0.0%, +1.1%]; consensus_latency_ms p=0.429 -0.5% [-1.4%, +0.5%]; e2e_latency_ms p=0.413 -0.3% [-1.2%, +0.6%]; accusations_honest p=1.000; g2_excluded_honest p=1.000; cores p=0.032 +2.3% [+0.2%, +3.2%]; throttled_pct p=0.095 +21.4% [-7.1%, +64.0%]; lo_mb_s p=0.008 +5.3% [+4.8%, +5.7%]


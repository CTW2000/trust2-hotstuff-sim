## results-probe49/cmp_corr.csv: 45 runs

### bursts, rule trust2 (5 / 5 / 5 runs)

| metric | next | all | fwd |
|---|---|---|---|
| timeouts | 28 [25-34] | 24 [21-28] | 26 [22-27] |
| rounds_per_s | 6.4 [6.2-6.7] | 6.6 [6.5-6.8] | 6.7 [6.5-6.8] |
| consensus_latency_ms | 684 [655-748] | 588 [568-734] | 655 [609-823] |
| e2e_latency_ms | 975 [921-1036] | 952 [803-1064] | 921 [861-1068] |
| accusations_honest | 2 [0-3] | 3 [3-7] | 3 [2-5] |
| g2_excluded_honest | 0 | 0 | 0 |

- all against next: timeouts p=0.111 -14.3% [-29.4%, +4.0%]; rounds_per_s p=0.111 +3.1% [-1.5%, +6.5%]; consensus_latency_ms p=0.095 -14.0% [-21.4%, +7.3%]; e2e_latency_ms p=0.841 -2.4% [-18.4%, +9.1%]; accusations_honest p=0.032 +50.0%; g2_excluded_honest p=1.000
- fwd against next: timeouts p=0.175 -7.1% [-23.5%, +4.0%]; rounds_per_s p=0.087 +4.7% [+0.0%, +8.1%]; consensus_latency_ms p=0.246 -4.2% [-12.4%, +20.3%]; e2e_latency_ms p=0.579 -5.5% [-12.5%, +12.2%]; accusations_honest p=0.190 +50.0%; g2_excluded_honest p=1.000
- fwd against all: timeouts p=0.738 +8.3% [-15.4%, +23.8%]; rounds_per_s p=0.810 +1.5% [-2.9%, +3.1%]; consensus_latency_ms p=0.222 +11.4% [-10.8%, +40.0%]; e2e_latency_ms p=0.690 -3.3% [-13.4%, +28.6%]; accusations_honest p=0.159 +0.0% [-66.7%, +66.7%]; g2_excluded_honest p=1.000

### slots, rule none (5 / 5 / 5 runs)

| metric | next | all | fwd |
|---|---|---|---|
| timeouts | 55 [53-57] | 43 [39-46] | 46 [39-51] |
| rounds_per_s | 3.0 [2.7-3.3] | 3.9 [3.7-4.2] | 3.8 [3.3-4.2] |
| consensus_latency_ms | 696 [646-858] | 651 [519-852] | 641 [569-1103] |
| e2e_latency_ms | 1543 [1417-1914] | 1042 [972-1285] | 1138 [976-1668] |
| accusations_honest | 0 | 0 | 0 |
| g2_excluded_honest | 0 | 0 | 0 |

- all against next: timeouts p=0.008 -21.8% [-29.8%, -16.4%]; rounds_per_s p=0.008 +30.0% [+18.2%, +51.9%]; consensus_latency_ms p=0.548 -6.5% [-26.1%, +22.4%]; e2e_latency_ms p=0.008 -32.5% [-45.6%, -16.7%]; accusations_honest p=1.000; g2_excluded_honest p=1.000
- fwd against next: timeouts p=0.008 -16.4% [-29.1%, -7.3%]; rounds_per_s p=0.016 +26.7% [+10.0%, +44.4%]; consensus_latency_ms p=0.690 -7.9% [-25.3%, +61.1%]; e2e_latency_ms p=0.151 -26.2% [-40.5%, +8.1%]; accusations_honest p=1.000; g2_excluded_honest p=1.000
- fwd against all: timeouts p=0.381 +7.0% [-9.3%, +20.5%]; rounds_per_s p=0.556 -2.6% [-15.4%, +7.7%]; consensus_latency_ms p=0.690 -1.5% [-24.8%, +93.5%]; e2e_latency_ms p=0.548 +9.2% [-14.1%, +60.1%]; accusations_honest p=1.000; g2_excluded_honest p=1.000

### slots, rule trust2 (5 / 5 / 5 runs)

| metric | next | all | fwd |
|---|---|---|---|
| timeouts | 58 [54-59] | 44 [41-46] | 48 [37-51] |
| rounds_per_s | 2.9 [2.6-3.0] | 3.9 [3.4-4.1] | 3.6 [3.3-4.5] |
| consensus_latency_ms | 673 [626-804] | 758 [579-780] | 839 [583-903] |
| e2e_latency_ms | 1585 [1388-1770] | 1261 [997-1378] | 1334 [1024-1441] |
| accusations_honest | 32 [29-33] | 47 [45-49] | 50 [40-55] |
| g2_excluded_honest | 0 [0-2] | 3 [2-5] | 3 [2-6] |

- all against next: timeouts p=0.008 -24.1% [-29.3%, -16.4%]; rounds_per_s p=0.008 +34.5% [+17.2%, +50.0%]; consensus_latency_ms p=0.651 +12.6% [-15.2%, +21.1%]; e2e_latency_ms p=0.008 -20.4% [-37.1%, -4.3%]; accusations_honest p=0.008 +46.9% [+40.6%, +62.1%]; g2_excluded_honest p=0.024
- fwd against next: timeouts p=0.008 -17.2% [-36.2%, -7.4%]; rounds_per_s p=0.008 +24.1% [+13.8%, +55.2%]; consensus_latency_ms p=0.690 +24.7% [-16.0%, +38.1%]; e2e_latency_ms p=0.032 -15.8% [-39.3%, -3.0%]; accusations_honest p=0.008 +56.2% [+25.0%, +77.4%]; g2_excluded_honest p=0.016
- fwd against all: timeouts p=0.603 +9.1% [-15.9%, +21.4%]; rounds_per_s p=0.659 -7.7% [-15.4%, +15.4%]; consensus_latency_ms p=0.381 +10.7% [-23.1%, +44.9%]; e2e_latency_ms p=1.000 +5.8% [-24.6%, +33.8%]; accusations_honest p=0.540 +6.4% [-14.9%, +17.0%]; g2_excluded_honest p=0.833 +0.0% [-40.0%, +100.0%]


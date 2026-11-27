# The holder of the commit proof proposes the first block of an epoch (DESIGN.md 15.58): 30 runs, blocks [1, 2, 3, 4, 5, 6, 7, 8, 9]

Median [min, max] over the runs of an arm. e25: epochs of 25 rounds; -holder: with the switch; e0: a single epoch.

## 10% late messages


### The arms

| arm | runs | rounds/s | timed-out rounds per 1000 | end-to-end ms | stalls | stalls next to a handover | handovers | per handover |
|---|---|---|---|---|---|---|---|---|
| baseline | 9 | 6.6 [6.4, 6.9] | 62.3 [52.2, 78.1] | 551 [534, 578] | 32 [29, 37] | 8 [2, 15] | 0 [0, 0] | - |
| e25 | 9 | 6.1 [5.8, 6.3] | 85.1 [69.7, 94.7] | 676 [630, 817] | 39 [37, 46] | 12 [5, 16] | 46 [45, 49] | 0.25 [0.11, 0.36] |
| e25-holder | 9 | 6.2 [6.0, 6.4] | 72.4 [66.6, 88.5] | 631 [583, 674] | 37 [33, 42] | 10 [1, 14] | 47 [46, 49] | 0.21 [0.02, 0.29] |
| e0 | 1 | 6.4 [6.4, 6.4] | 63.0 [63.0, 63.0] | 558 [558, 558] | 31 [31, 31] | 9 [9, 9] | 0 [0, 0] | - |

### Trust 2.0 against the baseline

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| e25 against the baseline | end-to-end latency | 9 | +22.9% | [+20.9%, +24.9%] | 45 (9) | 0.004 | 0.023 | no |
| e25 against the baseline | rounds/s | 9 | -7.7% | [-10.4%, -7.6%] | 0 (9) | 0.004 | 0.023 | yes |
| e25 against the baseline | timed-out rounds per 1000 | 9 | +31.3% | [+16.4%, +53.9%] | 44 (9) | 0.008 | 0.023 | no |
| e25-holder against the baseline | end-to-end latency | 9 | +9.5% | [+8.4%, +18.2%] | 45 (9) | 0.004 | 0.023 | no |
| e25-holder against the baseline | rounds/s | 9 | -4.6% | [-7.5%, -3.0%] | 0 (8) | 0.008 | 0.023 | yes |
| e25-holder against the baseline | timed-out rounds per 1000 | 9 | +11.7% | [+3.8%, +33.7%] | 38 (9) | 0.074 | 0.074 | no |

### With the switch against without

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| e25-holder against e25 | end-to-end latency | 9 | -7.0% | [-11.8%, -4.6%] | 2 (9) | 0.012 | 0.035 | yes |
| e25-holder against e25 | rounds/s | 9 | +3.3% | [+1.6%, +3.3%] | 39 (9) | 0.051 | 0.102 | yes |
| e25-holder against e25 | timed-out rounds per 1000 | 9 | -10.8% | [-18.6%, -7.7%] | 7 (9) | 0.074 | 0.102 | no |

## Three silent leaders


### The arms

| arm | runs | rounds/s | timed-out rounds per 1000 | end-to-end ms | stalls | stalls next to a handover | handovers | per handover | all three convicted by round | excluded by the table from round | top round |
|---|---|---|---|---|---|---|---|---|---|---|---|
| e25 | 1 | 5.7 [5.7, 5.7] | 60.4 [60.4, 60.4] | 949 [949, 949] | 65 [65, 65] | 16 [16, 16] | 44 [44, 44] | 0.36 [0.36, 0.36] | 131 [131, 131] | 177 [177, 177] (1 of 1 runs) | 1077 [1077, 1077] |
| e25-holder | 1 | 5.9 [5.9, 5.9] | 54.0 [54.0, 54.0] | 840 [840, 840] | 60 [60, 60] | 11 [11, 11] | 46 [46, 46] | 0.24 [0.24, 0.24] | 131 [131, 131] | 177 [177, 177] (1 of 1 runs) | 1129 [1129, 1129] |

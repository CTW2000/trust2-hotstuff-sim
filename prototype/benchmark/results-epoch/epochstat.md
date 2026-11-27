# The epoch length (DESIGN.md 15.56): 56 runs, blocks [1, 2, 3, 4]

Median [min, max] over the runs of an arm.

## 10% late messages


### The baseline, and Trust 2.0 by epoch length (e0: a single epoch)

| arm | runs | rounds/s | timed-out rounds per 1000 | end-to-end ms | stalls | stalls next to a handover | handovers | per handover |
|---|---|---|---|---|---|---|---|---|
| baseline | 4 | 6.5 [6.2, 6.7] | 70.3 [55.5, 84.2] | 564 [540, 599] | 36 [30, 42] | 10 [7, 12] | 0 [0, 0] | - |
| e25 | 4 | 6.3 [6.2, 6.4] | 77.4 [69.0, 79.8] | 612 [584, 714] | 36 [33, 38] | 10 [7, 11] | 48 [48, 49] | 0.22 [0.14, 0.23] |
| e50 | 4 | 6.5 [6.0, 6.8] | 61.0 [45.8, 86.5] | 634 [550, 670] | 30 [25, 40] | 6 [5, 8] | 25 [23, 26] | 0.25 [0.19, 0.32] |
| e100 | 4 | 6.3 [6.1, 7.0] | 70.9 [41.6, 77.7] | 634 [515, 699] | 36 [22, 39] | 3 [0, 8] | 12 [12, 14] | 0.24 [0.00, 0.67] |
| e400 | 4 | 6.5 [6.2, 6.7] | 65.0 [51.2, 71.2] | 584 [520, 653] | 33 [26, 36] | 0 [0, 1] | 4 [3, 4] | 0.12 [0.00, 0.33] |
| e0 | 4 | 6.6 [6.0, 7.0] | 57.5 [37.1, 90.6] | 558 [517, 641] | 30 [22, 41] | 6 [2, 8] | 0 [0, 0] | - |

### Trust 2.0 against the baseline

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| e25 against the baseline | end-to-end latency | 4 | +11.6% | [+2.6%, +18.2%] | 10 (4) | 0.125 | 1.000 | no |
| e25 against the baseline | rounds/s | 4 | -1.5% | [-6.0%, -0.8%] | 0 (3) | 0.250 | 1.000 | yes |
| e25 against the baseline | timed-out rounds per 1000 | 4 | +4.4% | [-7.9%, +29.3%] | 7 (4) | 0.625 | 1.000 | no |
| e50 against the baseline | end-to-end latency | 4 | +9.7% | [-3.3%, +24.1%] | 9 (4) | 0.250 | 1.000 | no |
| e50 against the baseline | rounds/s | 4 | +2.3% | [-10.4%, +4.8%] | 3 (3) | 1.000 | 1.000 | yes |
| e50 against the baseline | timed-out rounds per 1000 | 4 | -22.4% | [-31.9%, +55.8%] | 4 (4) | 0.875 | 1.000 | no |
| e100 against the baseline | end-to-end latency | 4 | +8.5% | [-7.7%, +29.4%] | 8 (4) | 0.375 | 1.000 | no |
| e100 against the baseline | rounds/s | 4 | -0.8% | [-9.0%, +3.8%] | 2 (3) | 0.750 | 1.000 | yes |
| e100 against the baseline | timed-out rounds per 1000 | 4 | -5.5% | [-43.2%, +21.5%] | 4 (4) | 0.875 | 1.000 | no |
| e400 against the baseline | end-to-end latency | 4 | +0.0% | [-6.8%, +20.9%] | 6 (4) | 0.875 | 1.000 | no |
| e400 against the baseline | rounds/s | 4 | +1.5% | [-3.7%, +4.8%] | 3 (3) | 1.000 | 1.000 | yes |
| e400 against the baseline | timed-out rounds per 1000 | 4 | -13.3% | [-25.5%, +28.3%] | 3 (4) | 0.625 | 1.000 | no |
| e0 against the baseline | end-to-end latency | 4 | -4.4% | [-7.3%, +18.7%] | 4 (4) | 0.875 | 1.000 | no |
| e0 against the baseline | rounds/s | 4 | +4.0% | [-3.7%, +7.7%] | 6 (4) | 0.875 | 1.000 | yes |
| e0 against the baseline | timed-out rounds per 1000 | 4 | -23.5% | [-49.4%, +63.2%] | 4 (4) | 0.875 | 1.000 | no |

### Trust 2.0 with handovers against a single epoch

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| e25 against e0 | end-to-end latency | 4 | +12.4% | [-1.2%, +17.9%] | 9 (4) | 0.250 | 1.000 | no |
| e25 against e0 | rounds/s | 4 | -4.5% | [-8.6%, +0.3%] | 3 (4) | 0.625 | 1.000 | yes |
| e25 against e0 | timed-out rounds per 1000 | 4 | +34.9% | [-11.9%, +63.4%] | 9 (4) | 0.250 | 1.000 | no |
| e50 against e0 | end-to-end latency | 4 | +5.7% | [+4.0%, +23.4%] | 10 (4) | 0.125 | 1.000 | no |
| e50 against e0 | rounds/s | 4 | +0.0% | [-3.6%, +1.5%] | 1 (2) | 1.000 | 1.000 | yes |
| e50 against e0 | timed-out rounds per 1000 | 4 | +0.2% | [-10.5%, +58.7%] | 6 (4) | 0.875 | 1.000 | no |
| e100 against e0 | end-to-end latency | 4 | +9.8% | [-0.4%, +16.3%] | 9 (4) | 0.250 | 1.000 | no |
| e100 against e0 | rounds/s | 4 | -2.2% | [-4.5%, +0.8%] | 1 (3) | 0.500 | 1.000 | yes |
| e100 against e0 | timed-out rounds per 1000 | 4 | +16.4% | [-14.2%, +23.4%] | 8 (4) | 0.375 | 1.000 | no |
| e400 against e0 | end-to-end latency | 4 | +1.4% | [+0.7%, +8.7%] | 10 (4) | 0.125 | 1.000 | yes |
| e400 against e0 | rounds/s | 4 | -1.5% | [-4.3%, +3.3%] | 2 (3) | 0.750 | 1.000 | yes |
| e400 against e0 | timed-out rounds per 1000 | 4 | +13.2% | [-21.4%, +26.7%] | 7 (4) | 0.625 | 1.000 | no |

## Three silent leaders


### Trust 2.0 by epoch length, with H5 and without

| arm | runs | rounds/s | timed-out rounds per 1000 | end-to-end ms | stalls | stalls next to a handover | handovers | per handover | all three convicted by round | excluded by the table from round | top round |
|---|---|---|---|---|---|---|---|---|---|---|---|
| e25-on | 4 | 5.2 [4.7, 5.7] | 75.7 [60.5, 97.5] | 1108 [952, 1257] | 75 [65, 86] | 20 [16, 28] | 40 [36, 43] | 0.50 [0.37, 0.78] | 138 [128, 144] | 190 [177, 202] (4 of 4 runs) | 992 [892, 1075] |
| e25-off | 4 | 5.2 [4.7, 5.7] | 75.8 [60.4, 97.1] | 1112 [950, 1285] | 75 [65, 86] | 20 [16, 27] | 40 [36, 44] | 0.50 [0.36, 0.75] | 138 [128, 144] | 190 [177, 202] (4 of 4 runs) | 991 [886, 1077] |
| e50-on | 4 | 5.3 [4.9, 5.4] | 72.0 [69.2, 85.6] | 988 [851, 1127] | 72 [70, 80] | 10 [5, 13] | 20 [19, 21] | 0.52 [0.24, 0.68] | 118 [108, 185] | 204 [202, 253] (4 of 4 runs) | 1006 [935, 1026] |
| e50-off | 4 | 5.3 [4.9, 5.4] | 72.0 [69.2, 85.6] | 986 [852, 1128] | 72 [70, 80] | 10 [5, 13] | 20 [19, 21] | 0.52 [0.24, 0.68] | 118 [108, 185] | 204 [202, 253] (4 of 4 runs) | 1007 [935, 1026] |
| e100-on | 4 | 4.7 [4.5, 5.2] | 95.9 [76.1, 102.1] | 1166 [968, 1209] | 85 [75, 88] | 8 [7, 12] | 10 [9, 10] | 0.91 [0.70, 1.33] | 142 [102, 168] | 302 [302, 303] (4 of 4 runs) | 892 [862, 985] |
| e100-off | 4 | 4.7 [4.5, 5.2] | 95.9 [76.2, 102.1] | 1168 [967, 1207] | 85 [75, 88] | 8 [7, 12] | 10 [9, 10] | 0.91 [0.70, 1.33] | 142 [102, 168] | 302 [302, 303] (4 of 4 runs) | 892 [862, 984] |
| e400-on | 4 | 3.3 [3.3, 3.5] | 177.7 [161.0, 181.5] | 1540 [1452, 1563] | 113 [108, 114] | 0 [0, 0] | 2 [2, 2] | 0.00 [0.00, 0.00] | 122 [102, 176] | - (0 of 4 runs) | 636 [628, 671] |
| e400-off | 4 | 3.3 [3.3, 3.5] | 176.3 [161.0, 182.7] | 1532 [1445, 1560] | 112 [108, 114] | 0 [0, 0] | 2 [2, 2] | 0.00 [0.00, 0.00] | 122 [102, 176] | - (0 of 4 runs) | 638 [624, 671] |

### H5 on against off, by epoch length

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| e25: on against off | end-to-end latency | 4 | -0.3% | [-2.2%, +0.1%] | 1 (3) | 0.500 | 1.000 | yes |
| e25: on against off | rounds/s | 4 | +0.0% | [+0.0%, +0.0%] | 0 (0) | 1.000 | 1.000 | yes |
| e25: on against off | timed-out rounds per 1000 | 4 | +0.1% | [-0.2%, +0.5%] | 7 (4) | 0.625 | 1.000 | yes |
| e50: on against off | end-to-end latency | 4 | -0.1% | [-0.1%, +0.5%] | 4 (4) | 0.875 | 1.000 | yes |
| e50: on against off | rounds/s | 4 | +0.0% | [+0.0%, +0.0%] | 0 (0) | 1.000 | 1.000 | yes |
| e50: on against off | timed-out rounds per 1000 | 4 | +0.0% | [+0.0%, +0.1%] | 1 (1) | 1.000 | 1.000 | yes |
| e100: on against off | end-to-end latency | 4 | +0.0% | [-0.2%, +0.2%] | 5 (4) | 1.000 | 1.000 | yes |
| e100: on against off | rounds/s | 4 | +0.0% | [+0.0%, +0.0%] | 0 (0) | 1.000 | 1.000 | yes |
| e100: on against off | timed-out rounds per 1000 | 4 | +0.0% | [-0.1%, +0.0%] | 0 (1) | 1.000 | 1.000 | yes |
| e400: on against off | end-to-end latency | 4 | +0.3% | [-0.3%, +1.3%] | 8 (4) | 0.375 | 1.000 | yes |
| e400: on against off | rounds/s | 4 | +0.0% | [+0.0%, +0.0%] | 0 (0) | 1.000 | 1.000 | yes |
| e400: on against off | timed-out rounds per 1000 | 4 | +0.3% | [-0.6%, +0.9%] | 4 (3) | 0.750 | 1.000 | yes |

### With H5: longer epochs against 25 rounds

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| e50 against e25 | end-to-end latency | 4 | -10.5% | [-14.0%, -8.8%] | 0 (4) | 0.125 | 1.000 | yes |
| e50 against e25 | rounds/s | 4 | +2.0% | [-7.0%, +4.3%] | 3 (3) | 1.000 | 1.000 | yes |
| e50 against e25 | timed-out rounds per 1000 | 4 | -5.8% | [-12.3%, +7.7%] | 4 (4) | 0.875 | 1.000 | yes |
| e100 against e25 | end-to-end latency | 4 | +8.7% | [-23.0%, +19.4%] | 6 (4) | 0.875 | 1.000 | no |
| e100 against e25 | rounds/s | 4 | -13.3% | [-15.3%, +10.6%] | 1 (4) | 0.250 | 1.000 | no |
| e100 against e25 | timed-out rounds per 1000 | 4 | +33.7% | [-21.9%, +52.5%] | 9 (4) | 0.250 | 1.000 | no |
| e400 against e25 | end-to-end latency | 4 | +39.4% | [+23.1%, +64.2%] | 10 (4) | 0.125 | 1.000 | no |
| e400 against e25 | rounds/s | 4 | -37.1% | [-40.4%, -30.4%] | 0 (4) | 0.125 | 1.000 | no |
| e400 against e25 | timed-out rounds per 1000 | 4 | +139.5% | [+65.0%, +190.6%] | 10 (4) | 0.125 | 1.000 | no |

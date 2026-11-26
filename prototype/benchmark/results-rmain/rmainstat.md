# The leader rules under lateness (DESIGN.md 15.53): 930 runs, blocks [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

Median [min, max] over the runs of an arm unless stated. A run in which nothing commits after the warm-up has no latency and counts 0 rounds per second.

## A. Four rules, four models of lateness


### P2: model P, 2% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 8.7 [8.6, 8.7] | 0.0 [0.0, 1.2] | 346 [343, 353] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 16495 | 0.0 | 0 |
| aptos | 10 | 8.7 [8.7, 8.7] | 0.0 [0.0, 0.0] | 344 [343, 346] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 16530 | 0.0 | 0 |
| failed | 10 | 8.7 [8.7, 8.7] | 0.0 [0.0, 0.0] | 344 [344, 346] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 16522 | 0.0 | 0 |
| trust2 | 10 | 8.7 [8.6, 8.7] | 0.0 [0.0, 0.0] | 344 [344, 347] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 16515 | 0.0 | 0 |

### P5: model P, 5% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 8.5 [8.3, 8.6] | 1.5 [0.0, 6.3] | 354 [348, 379] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 16121 | 0.2 | 0 |
| aptos | 10 | 8.4 [8.4, 8.5] | 2.5 [0.0, 7.6] | 358 [350, 378] | 0.00 [0.00, 1.31] | 0.00 [0.00, 0.00] | 16084 | 0.2 | 0 |
| failed | 10 | 8.4 [8.3, 8.5] | 2.2 [0.0, 9.5] | 358 [351, 389] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 16044 | 0.2 | 0 |
| trust2 | 10 | 8.4 [8.3, 8.6] | 3.5 [0.0, 7.0] | 363 [349, 412] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 16010 | 0.4 | 0 |

### P10: model P, 10% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 6.1 [5.9, 6.8] | 80.6 [50.0, 98.0] | 676 [541, 809] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 11745 | 1.1 | 0 |
| aptos | 10 | 6.2 [5.8, 6.6] | 74.5 [50.4, 96.9] | 671 [546, 727] | 11.75 [8.89, 16.63] | 0.00 [0.00, 0.00] | 11722 | 1.7 | 0 |
| failed | 10 | 6.2 [5.6, 6.4] | 80.9 [67.9, 111.8] | 648 [571, 770] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 11606 | 1.4 | 0 |
| trust2 | 10 | 6.1 [5.9, 6.5] | 81.8 [62.4, 89.5] | 656 [595, 730] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 11647 | 1.5 | 0 |

### P20: model P, 20% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 1.2 [1.2, 1.3] | 932.8 [881.9, 1004.5] | 5917 [4369, 14563] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 2396 | 18.8 | 0 |
| aptos | 10 | 1.2 [1.1, 1.3] | 952.5 [905.0, 1004.5] | 8336 [4320, 11742] | 76.92 [73.12, 79.68] | 0.00 [0.00, 0.00] | 2340 | 30.8 | 0 |
| failed | 10 | 1.2 [1.1, 1.4] | 952.4 [898.8, 1087.6] | 5333 [4267, 9801] | 15.24 [6.70, 21.18] | 3.23 [1.94, 4.84] | 2436 | 15.6 | 107 |
| trust2 | 10 | 1.2 [1.0, 1.3] | 946.3 [906.9, 1112.8] | 8468 [5135, 10794] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 2378 | 21.4 | 0 |

### S2: model S, 2% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 6.1 [5.6, 6.3] | 48.6 [43.2, 62.5] | 828 [751, 1170] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 11360 | 22.9 | 0 |
| aptos | 10 | 6.0 [5.3, 6.5] | 50.7 [38.6, 76.2] | 840 [687, 1025] | 10.29 [8.03, 14.40] | 0.00 [0.00, 0.00] | 11440 | 21.9 | 0 |
| failed | 10 | 6.1 [5.2, 6.6] | 48.1 [34.9, 76.5] | 811 [690, 1051] | 0.00 [0.00, 1.43] | 0.00 [0.00, 0.10] | 11459 | 22.3 | 1 |
| trust2 | 10 | 6.2 [5.6, 6.7] | 46.4 [32.9, 61.7] | 842 [715, 958] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 11655 | 21.5 | 0 |

### S5: model S, 5% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 4.2 [3.8, 4.6] | 122.1 [97.0, 141.3] | 1294 [1111, 1561] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 7902 | 56.9 | 0 |
| aptos | 10 | 4.0 [3.5, 4.5] | 131.1 [100.7, 158.8] | 1412 [1080, 1646] | 24.84 [18.80, 31.66] | 0.00 [0.00, 0.00] | 7604 | 60.6 | 0 |
| failed | 10 | 4.2 [3.6, 4.5] | 120.0 [101.9, 158.7] | 1316 [1055, 1436] | 0.00 [0.00, 1.20] | 0.00 [0.00, 0.32] | 7931 | 56.5 | 4 |
| trust2 | 10 | 4.2 [3.6, 4.8] | 120.2 [88.3, 160.5] | 1258 [1069, 1514] | 0.00 [0.00, 2.00] | 0.00 [0.00, 0.32] | 8026 | 53.2 | 2 |

### S10: model S, 10% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 3.0 [2.6, 3.5] | 218.1 [158.8, 253.5] | 1720 [1414, 1866] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 5629 | 104.1 | 0 |
| aptos | 10 | 2.8 [2.4, 3.3] | 229.4 [185.3, 283.2] | 1822 [1446, 2459] | 46.80 [34.92, 55.61] | 0.00 [0.00, 0.00] | 5394 | 109.9 | 0 |
| failed | 10 | 3.0 [1.6, 3.1] | 210.8 [189.3, 257.5] | 1681 [1395, 1976] | 0.09 [0.00, 4.59] | 0.16 [0.00, 0.65] | 5321 | 108.3 | 9 |
| trust2 | 10 | 2.8 [2.4, 3.6] | 217.1 [158.1, 287.6] | 1688 [1362, 2064] | 1.08 [0.00, 3.77] | 0.32 [0.00, 0.97] | 5560 | 106.5 | 10 |

### S20: model S, 20% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 1.7 [1.5, 2.0] | 428.2 [361.5, 482.9] | 2774 [2249, 3777] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 3298 | 226.5 | 0 |
| aptos | 10 | 1.9 [1.1, 2.4] | 385.2 [284.8, 442.0] | 2808 [2372, 4494] | 66.86 [51.61, 72.69] | 0.00 [0.00, 0.00] | 3450 | 209.6 | 0 |
| failed | 10 | 1.8 [1.8, 2.0] | 398.9 [367.7, 424.8] | 2406 [2265, 3139] | 2.91 [0.00, 4.07] | 0.81 [0.00, 0.97] | 3470 | 208.9 | 22 |
| trust2 | 10 | 1.6 [1.5, 2.0] | 426.3 [369.4, 482.1] | 2648 [2289, 3880] | 2.50 [0.00, 7.17] | 0.65 [0.00, 1.61] | 3242 | 215.3 | 23 |

### B2: model B, 2% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 8.3 [8.2, 8.4] | 6.7 [6.3, 7.7] | 436 [366, 536] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 15768 | 0.4 | 0 |
| aptos | 10 | 8.3 [8.2, 8.4] | 7.6 [6.3, 7.7] | 444 [430, 478] | 4.62 [4.20, 5.53] | 0.00 [0.00, 0.00] | 15763 | 0.4 | 0 |
| failed | 10 | 8.2 [8.2, 8.4] | 7.7 [6.3, 7.7] | 451 [384, 616] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 15734 | 0.4 | 0 |
| trust2 | 10 | 8.3 [8.2, 8.3] | 6.3 [6.3, 8.4] | 440 [363, 484] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 15806 | 0.2 | 0 |

### B5: model B, 5% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 7.4 [7.3, 7.6] | 21.0 [18.8, 23.0] | 724 [664, 802] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 14114 | 1.0 | 0 |
| aptos | 10 | 7.5 [7.3, 7.5] | 20.9 [18.9, 23.9] | 748 [655, 805] | 8.70 [7.73, 9.85] | 0.00 [0.00, 0.00] | 14099 | 1.4 | 0 |
| failed | 10 | 7.4 [7.3, 7.6] | 21.5 [19.5, 23.9] | 818 [723, 852] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 14036 | 1.4 | 0 |
| trust2 | 10 | 7.4 [7.3, 7.6] | 21.8 [17.3, 23.8] | 712 [637, 1003] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 14107 | 1.1 | 0 |

### B10: model B, 10% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 6.0 [5.8, 6.1] | 54.4 [49.9, 61.0] | 1242 [1166, 1332] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 11307 | 3.9 | 0 |
| aptos | 10 | 5.9 [5.5, 6.0] | 55.6 [51.8, 67.1] | 1299 [1111, 1488] | 19.28 [15.63, 21.97] | 0.00 [0.00, 0.00] | 11126 | 5.0 | 0 |
| failed | 10 | 6.0 [5.8, 6.2] | 53.7 [45.6, 60.7] | 1224 [1097, 1507] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 11362 | 3.9 | 0 |
| trust2 | 10 | 6.0 [5.9, 6.2] | 52.7 [47.6, 56.5] | 1255 [1159, 1361] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 11435 | 3.8 | 0 |

### B20: model B, 20% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 3.2 [2.9, 3.5] | 201.3 [166.9, 227.0] | 2326 [2156, 2600] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 6063 | 14.2 | 0 |
| aptos | 10 | 2.8 [2.5, 3.0] | 248.1 [217.9, 288.7] | 2420 [2141, 2769] | 65.77 [59.53, 69.78] | 0.00 [0.00, 0.00] | 5223 | 40.4 | 0 |
| failed | 10 | 3.1 [2.9, 3.4] | 205.5 [179.7, 230.9] | 2468 [2083, 2783] | 0.37 [0.00, 2.40] | 0.32 [0.00, 0.65] | 5969 | 13.4 | 7 |
| trust2 | 10 | 3.2 [3.0, 3.5] | 197.9 [170.7, 212.8] | 2284 [2026, 2683] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 6141 | 14.7 | 0 |

### Q0.5: model Q, 0.5% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 8.7 [8.7, 8.7] | 0.0 [0.0, 0.0] | 344 [343, 346] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 16553 | 0.0 | 0 |
| aptos | 10 | 8.7 [8.6, 8.7] | 0.0 [0.0, 1.2] | 344 [343, 350] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 16541 | 0.0 | 0 |
| failed | 10 | 8.7 [8.6, 8.7] | 0.0 [0.0, 0.0] | 344 [343, 348] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 16554 | 0.0 | 0 |
| trust2 | 10 | 8.7 [8.7, 8.7] | 0.0 [0.0, 0.6] | 344 [343, 346] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 16561 | 0.0 | 0 |

### Q1: model Q, 1% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 8.6 [8.5, 8.6] | 0.0 [0.0, 2.5] | 349 [347, 355] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 16335 | 0.0 | 0 |
| aptos | 10 | 8.6 [8.4, 8.6] | 0.6 [0.0, 5.6] | 350 [347, 398] | 0.00 [0.00, 0.25] | 0.00 [0.00, 0.00] | 16273 | 0.1 | 0 |
| failed | 10 | 8.6 [8.5, 8.6] | 0.0 [0.0, 2.5] | 348 [347, 361] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 16333 | 0.0 | 0 |
| trust2 | 10 | 8.6 [8.5, 8.6] | 0.6 [0.0, 3.1] | 352 [347, 366] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 16301 | 0.1 | 0 |

### Q2: model Q, 2% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 3.3 [2.1, 6.1] | 230.5 [73.7, 440.3] | 3188 [730, 6933] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 7520 | 2.7 | 0 |
| aptos | 10 | 4.5 [2.0, 6.7] | 131.5 [43.2, 428.9] | 3100 [526, 10018] | 8.47 [0.65, 46.45] | 0.00 [0.00, 0.00] | 7977 | 2.3 | 0 |
| failed | 10 | 4.3 [2.0, 6.6] | 147.9 [45.7, 474.4] | 3296 [715, 9317] | 0.45 [0.00, 14.81] | 0.32 [0.00, 2.90] | 8353 | 1.4 | 19 |
| trust2 | 10 | 4.1 [1.2, 5.3] | 155.2 [90.0, 829.6] | 2078 [712, 5901] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 7493 | 2.3 | 0 |

### Q3: model Q, 3% late

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 0.3 [0.1, 0.8] | 2820.3 [1056.2, 7040.0] | 36349 [3657, 102229] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 2182 | 1.4 | 0 |
| aptos | 10 | 0.3 [0.1, 0.8] | 2480.6 [1045.8, 6250.0] | 3145 [430, 29408] | 0.00 [0.00, 21.77] | 0.00 [0.00, 0.00] | 2346 | 0.9 | 0 |
| failed | 10 | 0.4 [0.2, 0.9] | 2380.4 [1005.8, 3866.7] | 1500 [488, 144978] | 0.00 [0.00, 21.24] | 0.00 [0.00, 4.84] | 2399 | 0.8 | 15 |
| trust2 | 10 | 0.2 [0.2, 0.8] | 3795.5 [1052.3, 5800.0] | 546 [497, 109234] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 2273 | 0.0 | 0 |

### Model P: trust2 against the other rules

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| P2: trust2 against none | M1 | 10 | +0.0% | [-100.0%, +0.0%] | 0 (4) | 0.125 | 1.000 | no |
| P2: trust2 against none | M2 | 10 | -0.1% | [-1.3%, +0.3%] | 9 (8) | 0.250 | 1.000 | yes |
| P2: trust2 against none | rounds/s | 10 | +0.0% | [+0.0%, +0.0%] | 3 (2) | 0.500 | 1.000 | yes |
| P2: trust2 against aptos | M1 | 10 | +0.0% | [+0.0%, +0.0%] | 0 (0) | 1.000 | 1.000 | yes |
| P2: trust2 against aptos | M2 | 10 | +0.0% | [-0.1%, +0.1%] | 13 (6) | 0.719 | 1.000 | yes |
| P2: trust2 against aptos | rounds/s | 10 | +0.0% | [+0.0%, +0.0%] | 0 (1) | 1.000 | 1.000 | yes |
| P2: trust2 against failed | M1 | 10 | +0.0% | [+0.0%, +0.0%] | 0 (0) | 1.000 | 1.000 | yes |
| P2: trust2 against failed | M2 | 10 | +0.0% | [+0.0%, +0.1%] | 9 (5) | 0.812 | 1.000 | yes |
| P2: trust2 against failed | rounds/s | 10 | +0.0% | [+0.0%, +0.0%] | 0 (1) | 1.000 | 1.000 | yes |
| P5: trust2 against none | M1 | 8 | -16.6% | [-44.0%, +234.3%] | 14 (7) | 1.000 | 1.000 | no |
| P5: trust2 against none | M2 | 10 | +1.7% | [-0.8%, +4.0%] | 29 (9) | 0.496 | 1.000 | yes |
| P5: trust2 against none | rounds/s | 10 | -0.6% | [-1.2%, +1.2%] | 14.5 (8) | 0.664 | 1.000 | yes |
| P5: trust2 against aptos | M1 | 8 | +42.2% | [-46.2%, +102.3%] | 26 (8) | 0.312 | 1.000 | no |
| P5: trust2 against aptos | M2 | 10 | +0.3% | [-1.4%, +3.4%] | 33 (10) | 0.625 | 1.000 | yes |
| P5: trust2 against aptos | rounds/s | 10 | -0.6% | [-1.2%, +0.0%] | 11.5 (7) | 0.719 | 1.000 | yes |
| P5: trust2 against failed | M1 | 9 | -33.8% | [-54.2%, +50.8%] | 22 (9) | 1.000 | 1.000 | no |
| P5: trust2 against failed | M2 | 10 | +0.4% | [-1.9%, +2.0%] | 29 (10) | 0.922 | 1.000 | yes |
| P5: trust2 against failed | rounds/s | 10 | +0.0% | [-1.2%, +1.2%] | 20.5 (8) | 0.750 | 1.000 | yes |
| P10: trust2 against none | M1 | 10 | +2.2% | [-4.6%, +8.0%] | 33 (10) | 0.625 | 1.000 | yes |
| P10: trust2 against none | M2 | 10 | -1.4% | [-7.3%, +3.5%] | 21 (10) | 0.557 | 1.000 | yes |
| P10: trust2 against none | rounds/s | 10 | -1.6% | [-2.5%, +1.6%] | 21 (10) | 0.539 | 1.000 | yes |
| P10: trust2 against aptos | M1 | 10 | +0.6% | [-5.4%, +17.8%] | 31 (10) | 0.770 | 1.000 | no |
| P10: trust2 against aptos | M2 | 10 | +1.3% | [-3.4%, +8.1%] | 31 (10) | 0.770 | 1.000 | yes |
| P10: trust2 against aptos | rounds/s | 10 | -2.4% | [-3.3%, +1.6%] | 16 (9) | 0.496 | 1.000 | yes |
| P10: trust2 against failed | M1 | 10 | -1.9% | [-10.3%, +10.4%] | 26 (10) | 0.922 | 1.000 | yes |
| P10: trust2 against failed | M2 | 10 | +1.3% | [-9.7%, +7.0%] | 26 (10) | 0.922 | 1.000 | yes |
| P10: trust2 against failed | rounds/s | 10 | -2.4% | [-4.0%, +3.4%] | 28 (10) | 0.980 | 1.000 | yes |
| P20: trust2 against none | M1 | 10 | +1.2% | [-0.7%, +6.6%] | 41 (10) | 0.193 | 1.000 | yes |
| P20: trust2 against none | M2 | 10 | +41.6% | [-18.5%, +77.9%] | 43 (10) | 0.131 | 1.000 | no |
| P20: trust2 against none | rounds/s | 10 | +0.0% | [-7.7%, +0.0%] | 7 (5) | 1.000 | 1.000 | yes |
| P20: trust2 against aptos | M1 | 10 | +1.2% | [-3.9%, +2.7%] | 29 (10) | 0.922 | 1.000 | yes |
| P20: trust2 against aptos | M2 | 10 | -3.2% | [-31.9%, +17.7%] | 27 (10) | 1.000 | 1.000 | no |
| P20: trust2 against aptos | rounds/s | 10 | +0.0% | [-7.7%, +4.2%] | 12 (7) | 0.766 | 1.000 | yes |
| P20: trust2 against failed | M1 | 10 | +0.0% | [-4.3%, +0.6%] | 27 (10) | 1.000 | 1.000 | yes |
| P20: trust2 against failed | M2 | 10 | +41.1% | [-11.8%, +97.3%] | 42 (10) | 0.160 | 1.000 | no |
| P20: trust2 against failed | rounds/s | 10 | +0.0% | [+0.0%, +0.0%] | 5 (4) | 1.000 | 1.000 | yes |

### Model S: trust2 against the other rules

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| S2: trust2 against none | M1 | 10 | -12.0% | [-19.5%, +12.1%] | 21 (10) | 0.557 | 1.000 | no |
| S2: trust2 against none | M2 | 10 | -5.5% | [-9.5%, +5.1%] | 17 (10) | 0.322 | 1.000 | yes |
| S2: trust2 against none | rounds/s | 10 | +5.0% | [-2.4%, +7.9%] | 33.5 (9) | 0.215 | 1.000 | yes |
| S2: trust2 against aptos | M1 | 10 | -5.7% | [-21.0%, +12.0%] | 20 (10) | 0.492 | 1.000 | no |
| S2: trust2 against aptos | M2 | 10 | -0.4% | [-9.2%, +7.5%] | 24 (10) | 0.770 | 1.000 | yes |
| S2: trust2 against aptos | rounds/s | 10 | +2.5% | [-3.2%, +5.8%] | 35 (10) | 0.492 | 1.000 | yes |
| S2: trust2 against failed | M1 | 10 | +7.0% | [-23.5%, +20.1%] | 27 (10) | 1.000 | 1.000 | no |
| S2: trust2 against failed | M2 | 10 | +0.1% | [-12.5%, +7.2%] | 27 (10) | 1.000 | 1.000 | yes |
| S2: trust2 against failed | rounds/s | 10 | -2.4% | [-4.2%, +6.8%] | 30 (10) | 0.846 | 1.000 | yes |
| S5: trust2 against none | M1 | 10 | -6.5% | [-14.2%, +7.7%] | 24 (10) | 0.770 | 1.000 | yes |
| S5: trust2 against none | M2 | 10 | -3.0% | [-5.3%, +6.0%] | 27 (10) | 1.000 | 1.000 | yes |
| S5: trust2 against none | rounds/s | 10 | +4.6% | [-5.0%, +7.9%] | 33 (10) | 0.625 | 1.000 | yes |
| S5: trust2 against aptos | M1 | 10 | -4.2% | [-19.6%, +1.0%] | 12 (10) | 0.131 | 1.000 | no |
| S5: trust2 against aptos | M2 | 10 | -11.0% | [-16.7%, +6.6%] | 16 (10) | 0.275 | 1.000 | no |
| S5: trust2 against aptos | rounds/s | 10 | +2.7% | [+0.0%, +12.2%] | 32 (8) | 0.055 | 1.000 | yes |
| S5: trust2 against failed | M1 | 10 | -4.2% | [-12.2%, +17.1%] | 29 (10) | 0.922 | 1.000 | no |
| S5: trust2 against failed | M2 | 10 | -3.7% | [-8.5%, +10.4%] | 28 (10) | 1.000 | 1.000 | yes |
| S5: trust2 against failed | rounds/s | 10 | +2.3% | [-9.1%, +7.1%] | 23 (9) | 1.000 | 1.000 | yes |
| S10: trust2 against none | M1 | 10 | +2.8% | [-6.6%, +9.7%] | 34 (10) | 0.557 | 1.000 | yes |
| S10: trust2 against none | M2 | 10 | -0.9% | [-6.3%, +6.2%] | 27 (10) | 1.000 | 1.000 | yes |
| S10: trust2 against none | rounds/s | 10 | -3.3% | [-6.7%, +3.6%] | 18 (9) | 0.652 | 1.000 | yes |
| S10: trust2 against aptos | M1 | 10 | -5.5% | [-13.3%, +6.8%] | 20 (10) | 0.492 | 1.000 | yes |
| S10: trust2 against aptos | M2 | 10 | -14.8% | [-20.9%, +6.1%] | 10 (10) | 0.084 | 1.000 | no |
| S10: trust2 against aptos | rounds/s | 10 | +3.7% | [-9.4%, +8.3%] | 26 (9) | 0.734 | 1.000 | yes |
| S10: trust2 against failed | M1 | 10 | +2.1% | [-9.9%, +13.1%] | 31 (10) | 0.770 | 1.000 | yes |
| S10: trust2 against failed | M2 | 10 | +3.0% | [-5.4%, +7.7%] | 31 (10) | 0.770 | 1.000 | yes |
| S10: trust2 against failed | rounds/s | 10 | -3.2% | [-7.7%, +6.7%] | 17.5 (8) | 0.969 | 1.000 | yes |
| S20: trust2 against none | M1 | 10 | -0.9% | [-6.0%, +6.2%] | 29 (10) | 0.922 | 1.000 | yes |
| S20: trust2 against none | M2 | 10 | -5.7% | [-17.2%, +16.7%] | 24 (10) | 0.770 | 1.000 | no |
| S20: trust2 against none | rounds/s | 10 | -2.8% | [-5.9%, +0.0%] | 10 (7) | 0.562 | 1.000 | yes |
| S20: trust2 against aptos | M1 | 10 | +8.2% | [+4.0%, +24.5%] | 52 (10) | 0.010 | 0.352 | no |
| S20: trust2 against aptos | M2 | 10 | -4.6% | [-23.6%, +18.8%] | 22 (10) | 0.625 | 1.000 | no |
| S20: trust2 against aptos | rounds/s | 10 | -11.1% | [-16.7%, -2.9%] | 8 (8) | 0.180 | 1.000 | no |
| S20: trust2 against failed | M1 | 10 | +8.8% | [+2.6%, +15.9%] | 48 (10) | 0.037 | 1.000 | no |
| S20: trust2 against failed | M2 | 10 | +6.2% | [+4.2%, +21.6%] | 42 (10) | 0.160 | 1.000 | no |
| S20: trust2 against failed | rounds/s | 10 | -11.1% | [-13.9%, -5.6%] | 3 (10) | 0.010 | 0.352 | yes |

### Model B: trust2 against the other rules

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| B2: trust2 against none | M1 | 10 | -0.2% | [-9.4%, +5.4%] | 22 (10) | 0.625 | 1.000 | yes |
| B2: trust2 against none | M2 | 10 | +2.3% | [-6.8%, +3.9%] | 27 (10) | 1.000 | 1.000 | yes |
| B2: trust2 against none | rounds/s | 10 | +0.0% | [+0.0%, +0.0%] | 3 (3) | 1.000 | 1.000 | yes |
| B2: trust2 against aptos | M1 | 10 | -13.1% | [-17.4%, +10.2%] | 22 (10) | 0.625 | 1.000 | no |
| B2: trust2 against aptos | M2 | 10 | +0.6% | [-9.9%, +3.9%] | 18 (9) | 0.652 | 1.000 | yes |
| B2: trust2 against aptos | rounds/s | 10 | +0.0% | [+0.0%, +0.0%] | 3 (3) | 1.000 | 1.000 | yes |
| B2: trust2 against failed | M1 | 10 | -9.3% | [-17.6%, +5.4%] | 18 (10) | 0.375 | 1.000 | no |
| B2: trust2 against failed | M2 | 10 | -5.7% | [-15.9%, +3.7%] | 14 (10) | 0.193 | 1.000 | no |
| B2: trust2 against failed | rounds/s | 10 | +0.0% | [+0.0%, +1.2%] | 14 (5) | 0.125 | 1.000 | yes |
| B5: trust2 against none | M1 | 10 | -1.4% | [-4.7%, +7.8%] | 30 (10) | 0.846 | 1.000 | yes |
| B5: trust2 against none | M2 | 10 | -1.7% | [-5.8%, +5.8%] | 27 (10) | 1.000 | 1.000 | yes |
| B5: trust2 against none | rounds/s | 10 | +0.7% | [-1.3%, +1.4%] | 29 (9) | 0.465 | 1.000 | yes |
| B5: trust2 against aptos | M1 | 10 | -1.7% | [-13.1%, +14.3%] | 31 (10) | 0.770 | 1.000 | yes |
| B5: trust2 against aptos | M2 | 10 | -5.0% | [-7.7%, +6.9%] | 21 (10) | 0.557 | 1.000 | yes |
| B5: trust2 against aptos | rounds/s | 10 | +0.7% | [-1.3%, +1.4%] | 31 (9) | 0.375 | 1.000 | yes |
| B5: trust2 against failed | M1 | 10 | -2.0% | [-8.7%, +6.7%] | 22 (10) | 0.625 | 1.000 | yes |
| B5: trust2 against failed | M2 | 10 | -11.3% | [-13.7%, -7.6%] | 10 (10) | 0.084 | 1.000 | yes |
| B5: trust2 against failed | rounds/s | 10 | +0.7% | [+0.0%, +1.4%] | 16 (6) | 0.281 | 1.000 | yes |
| B10: trust2 against none | M1 | 10 | -5.8% | [-8.5%, +0.5%] | 11 (10) | 0.105 | 1.000 | yes |
| B10: trust2 against none | M2 | 10 | -0.7% | [-3.8%, +6.0%] | 32 (10) | 0.695 | 1.000 | yes |
| B10: trust2 against none | rounds/s | 10 | +0.8% | [-0.8%, +2.6%] | 29 (8) | 0.141 | 1.000 | yes |
| B10: trust2 against aptos | M1 | 10 | -1.7% | [-18.3%, -0.6%] | 10 (10) | 0.084 | 1.000 | no |
| B10: trust2 against aptos | M2 | 10 | -4.4% | [-9.3%, +3.3%] | 19 (10) | 0.432 | 1.000 | yes |
| B10: trust2 against aptos | rounds/s | 10 | +1.7% | [+0.0%, +5.2%] | 33 (8) | 0.031 | 1.000 | yes |
| B10: trust2 against failed | M1 | 10 | -3.7% | [-9.2%, +6.4%] | 23 (10) | 0.695 | 1.000 | yes |
| B10: trust2 against failed | M2 | 10 | +0.6% | [-6.6%, +7.4%] | 31 (10) | 0.770 | 1.000 | yes |
| B10: trust2 against failed | rounds/s | 10 | +0.8% | [-1.7%, +1.7%] | 31 (9) | 0.355 | 1.000 | yes |
| B20: trust2 against none | M1 | 10 | -4.8% | [-7.7%, +5.0%] | 23 (10) | 0.695 | 1.000 | yes |
| B20: trust2 against none | M2 | 10 | -1.5% | [-6.6%, +4.9%] | 25 (10) | 0.846 | 1.000 | yes |
| B20: trust2 against none | rounds/s | 10 | +3.2% | [-5.8%, +6.2%] | 33 (10) | 0.609 | 1.000 | yes |
| B20: trust2 against aptos | M1 | 10 | -19.2% | [-26.4%, -15.5%] | 0 (10) | 0.002 | 0.070 | no |
| B20: trust2 against aptos | M2 | 10 | -8.1% | [-10.7%, +0.6%] | 13 (10) | 0.160 | 1.000 | yes |
| B20: trust2 against aptos | rounds/s | 10 | +16.0% | [+12.4%, +22.1%] | 55 (10) | 0.002 | 0.070 | no |
| B20: trust2 against failed | M1 | 10 | -5.5% | [-8.0%, -1.2%] | 11 (10) | 0.105 | 1.000 | yes |
| B20: trust2 against failed | M2 | 10 | -9.0% | [-13.3%, +7.4%] | 23 (10) | 0.695 | 1.000 | yes |
| B20: trust2 against failed | rounds/s | 10 | +3.1% | [+0.0%, +6.5%] | 25 (7) | 0.078 | 1.000 | yes |

### Model Q: trust2 against the other rules

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| Q0.5: trust2 against none | M1 | 9 | +0.0% | [+0.0%, +0.0%] | 0 (0) | 1.000 | 1.000 | yes |
| Q0.5: trust2 against none | M2 | 10 | +0.0% | [+0.0%, +0.0%] | 5 (4) | 1.000 | 1.000 | yes |
| Q0.5: trust2 against none | rounds/s | 10 | +0.0% | [+0.0%, +0.0%] | 0 (0) | 1.000 | 1.000 | yes |
| Q0.5: trust2 against aptos | M1 | 10 | +0.0% | [+0.0%, +0.0%] | 0 (1) | 1.000 | 1.000 | yes |
| Q0.5: trust2 against aptos | M2 | 10 | -0.1% | [-0.3%, +0.0%] | 11 (7) | 0.641 | 1.000 | yes |
| Q0.5: trust2 against aptos | rounds/s | 10 | +0.0% | [+0.0%, +0.0%] | 1 (1) | 1.000 | 1.000 | yes |
| Q0.5: trust2 against failed | M1 | 9 | +0.0% | [+0.0%, +0.0%] | 0 (0) | 1.000 | 1.000 | yes |
| Q0.5: trust2 against failed | M2 | 10 | +0.0% | [-0.3%, +0.0%] | 7 (6) | 0.562 | 1.000 | yes |
| Q0.5: trust2 against failed | rounds/s | 10 | +0.0% | [+0.0%, +0.0%] | 1 (1) | 1.000 | 1.000 | yes |
| Q1: trust2 against none | M1 | 6 | +0.0% | [-100.0%, +100.4%] | 3 (3) | 1.000 | 1.000 | no |
| Q1: trust2 against none | M2 | 10 | +0.1% | [-0.3%, +1.4%] | 26 (8) | 0.312 | 1.000 | yes |
| Q1: trust2 against none | rounds/s | 10 | +0.0% | [+0.0%, +0.0%] | 3 (3) | 1.000 | 1.000 | yes |
| Q1: trust2 against aptos | M1 | 8 | +0.0% | [-83.7%, +24.8%] | 4 (5) | 0.375 | 1.000 | no |
| Q1: trust2 against aptos | M2 | 10 | +0.0% | [-0.7%, +0.7%] | 19 (8) | 0.945 | 1.000 | yes |
| Q1: trust2 against aptos | rounds/s | 10 | +0.0% | [+0.0%, +0.0%] | 2 (2) | 1.000 | 1.000 | yes |
| Q1: trust2 against failed | M1 | 6 | +0.0% | [-50.0%, +25.0%] | 1 (2) | 1.000 | 1.000 | no |
| Q1: trust2 against failed | M2 | 10 | +0.3% | [-0.1%, +1.4%] | 31 (9) | 0.355 | 1.000 | yes |
| Q1: trust2 against failed | rounds/s | 10 | +0.0% | [-0.6%, +0.0%] | 4 (4) | 1.000 | 1.000 | yes |
| Q2: trust2 against none | M1 | 10 | +6.0% | [-39.9%, +100.0%] | 32 (10) | 0.695 | 1.000 | no |
| Q2: trust2 against none | M2 | 10 | -17.6% | [-54.8%, +35.7%] | 24 (10) | 0.770 | 1.000 | no |
| Q2: trust2 against none | rounds/s | 10 | -5.1% | [-23.1%, +37.9%] | 25 (9) | 0.820 | 1.000 | no |
| Q2: trust2 against aptos | M1 | 10 | +22.7% | [-34.3%, +154.7%] | 39 (10) | 0.275 | 1.000 | no |
| Q2: trust2 against aptos | M2 | 10 | -30.5% | [-61.1%, +25.0%] | 23 (10) | 0.695 | 1.000 | no |
| Q2: trust2 against aptos | rounds/s | 10 | -7.5% | [-29.5%, +29.3%] | 28 (10) | 1.000 | 1.000 | no |
| Q2: trust2 against failed | M1 | 10 | +9.5% | [-42.6%, +117.1%] | 37 (10) | 0.375 | 1.000 | no |
| Q2: trust2 against failed | M2 | 10 | -37.5% | [-49.7%, +20.3%] | 22 (10) | 0.625 | 1.000 | no |
| Q2: trust2 against failed | rounds/s | 10 | -1.0% | [-33.3%, +37.5%] | 30 (10) | 0.846 | 1.000 | no |
| Q3: trust2 against none | M1 | 10 | +9.3% | [-25.1%, +54.4%] | 31 (10) | 0.770 | 1.000 | no |
| Q3: trust2 against none | rounds/s | 10 | +0.0% | [-33.3%, +25.0%] | 15 (7) | 0.891 | 1.000 | no |
| Q3: trust2 against aptos | M1 | 10 | +53.2% | [-7.4%, +70.9%] | 43 (10) | 0.131 | 1.000 | no |
| Q3: trust2 against aptos | M2 | 2 | -35.7% | [-98.3%, +27.0%] | 1 (2) | 1.000 | 1.000 | no |
| Q3: trust2 against aptos | rounds/s | 10 | -33.3% | [-42.9%, +0.0%] | 9 (8) | 0.234 | 1.000 | no |
| Q3: trust2 against failed | M1 | 10 | +45.9% | [-3.0%, +120.8%] | 47 (10) | 0.049 | 1.000 | no |
| Q3: trust2 against failed | M2 | 2 | -33.7% | [-79.2%, +11.9%] | 1 (2) | 1.000 | 1.000 | no |
| Q3: trust2 against failed | rounds/s | 10 | -31.0% | [-46.7%, +0.0%] | 5 (8) | 0.070 | 1.000 | no |

## B. Vote routing and leader rule


### silent, votes to next

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 3.0 [2.6, 3.4] | 215.0 [173.6, 259.6] | 1588 [1387, 1613] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 5077 | 4.3 | 0 |
| aptos | 10 | 6.4 [6.0, 6.6] | 39.9 [35.7, 50.7] | 760 [661, 885] | 0.46 [0.00, 2.41] | 0.00 [0.00, 0.00] | 11947 | 0.9 | 0 |
| failed | 10 | 5.5 [4.9, 6.3] | 63.4 [44.5, 84.3] | 936 [781, 1099] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 10324 | 1.4 | 0 |
| trust2 | 10 | 5.6 [5.0, 6.3] | 63.6 [44.6, 80.8] | 946 [779, 1076] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 10351 | 1.4 | 0 |

### silent, votes to all

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 4.2 [3.9, 4.6] | 106.8 [91.8, 126.2] | 964 [924, 1122] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 7254 | 0.0 | 0 |
| aptos | 10 | 7.3 [7.1, 7.5] | 21.3 [17.5, 24.6] | 486 [447, 522] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 13594 | 0.0 | 0 |
| failed | 10 | 7.0 [6.6, 7.1] | 26.8 [22.9, 32.5] | 541 [500, 568] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 12839 | 0.0 | 0 |
| trust2 | 10 | 7.0 [6.7, 7.1] | 26.9 [23.7, 32.4] | 542 [502, 573] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 12810 | 0.0 | 0 |

### silent: votes to all against votes to the next leader

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| silent, none: votes to all against the next leader | M1 | 10 | -50.1% | [-52.0%, -45.7%] | 0 (10) | 0.002 | 0.023 | no |
| silent, none: votes to all against the next leader | M2 | 10 | -37.2% | [-38.9%, -34.5%] | 0 (10) | 0.002 | 0.023 | no |
| silent, none: votes to all against the next leader | rounds/s | 10 | +42.6% | [+40.3%, +44.8%] | 55 (10) | 0.002 | 0.023 | no |
| silent, aptos: votes to all against the next leader | M1 | 10 | -48.0% | [-51.2%, -45.3%] | 0 (10) | 0.002 | 0.023 | no |
| silent, aptos: votes to all against the next leader | M2 | 10 | -35.1% | [-38.9%, -31.3%] | 0 (10) | 0.002 | 0.023 | no |
| silent, aptos: votes to all against the next leader | rounds/s | 10 | +12.5% | [+12.4%, +14.6%] | 55 (10) | 0.002 | 0.023 | yes |
| silent, failed: votes to all against the next leader | M1 | 10 | -55.6% | [-60.3%, -54.2%] | 0 (10) | 0.002 | 0.023 | no |
| silent, failed: votes to all against the next leader | M2 | 10 | -42.6% | [-45.9%, -41.3%] | 0 (10) | 0.002 | 0.023 | no |
| silent, failed: votes to all against the next leader | rounds/s | 10 | +23.6% | [+20.3%, +25.5%] | 55 (10) | 0.002 | 0.023 | no |
| silent, trust2: votes to all against the next leader | M1 | 10 | -54.2% | [-58.1%, -52.1%] | 0 (10) | 0.002 | 0.023 | no |
| silent, trust2: votes to all against the next leader | M2 | 10 | -42.1% | [-45.2%, -39.5%] | 0 (10) | 0.002 | 0.023 | no |
| silent, trust2: votes to all against the next leader | rounds/s | 10 | +22.4% | [+19.3%, +28.3%] | 55 (10) | 0.002 | 0.023 | no |

### late, votes to next

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 6.1 [5.9, 6.8] | 80.6 [50.0, 98.0] | 676 [541, 809] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 11745 | 1.1 | 0 |
| aptos | 10 | 6.2 [5.8, 6.6] | 74.5 [50.4, 96.9] | 671 [546, 727] | 11.75 [8.89, 16.63] | 0.00 [0.00, 0.00] | 11722 | 1.7 | 0 |
| failed | 10 | 6.2 [5.6, 6.4] | 80.9 [67.9, 111.8] | 648 [571, 770] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 11606 | 1.4 | 0 |
| trust2 | 10 | 6.1 [5.9, 6.5] | 81.8 [62.4, 89.5] | 656 [595, 730] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 11647 | 1.5 | 0 |

### late, votes to all

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 5.3 [5.1, 5.8] | 103.6 [79.9, 118.1] | 786 [719, 871] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 9807 | 45.5 | 0 |
| aptos | 10 | 5.6 [5.2, 5.6] | 96.6 [91.3, 113.1] | 739 [713, 789] | 21.27 [14.78, 24.53] | 0.00 [0.00, 0.00] | 10012 | 43.4 | 0 |
| failed | 10 | 5.2 [4.7, 5.6] | 110.2 [92.2, 143.5] | 779 [715, 952] | 0.00 [0.00, 0.97] | 0.00 [0.00, 0.32] | 9506 | 50.3 | 1 |
| trust2 | 10 | 5.3 [5.1, 5.8] | 99.7 [79.2, 117.8] | 746 [685, 832] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 9851 | 45.5 | 0 |

### late: votes to all against votes to the next leader

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| late, none: votes to all against the next leader | M1 | 10 | +25.4% | [+10.3%, +60.0%] | 54 (10) | 0.004 | 0.031 | no |
| late, none: votes to all against the next leader | M2 | 10 | +18.6% | [+9.5%, +25.6%] | 51 (10) | 0.014 | 0.031 | no |
| late, none: votes to all against the next leader | rounds/s | 10 | -12.5% | [-15.0%, -11.3%] | 0 (10) | 0.002 | 0.023 | no |
| late, aptos: votes to all against the next leader | M1 | 10 | +28.0% | [+8.3%, +49.6%] | 55 (10) | 0.002 | 0.023 | no |
| late, aptos: votes to all against the next leader | M2 | 10 | +11.7% | [+7.3%, +22.0%] | 52 (10) | 0.010 | 0.031 | no |
| late, aptos: votes to all against the next leader | rounds/s | 10 | -10.4% | [-13.9%, -8.2%] | 0 (10) | 0.002 | 0.023 | yes |
| late, failed: votes to all against the next leader | M1 | 10 | +36.6% | [+24.1%, +48.3%] | 54 (10) | 0.004 | 0.031 | no |
| late, failed: votes to all against the next leader | M2 | 10 | +23.3% | [+18.8%, +35.2%] | 54 (10) | 0.004 | 0.031 | no |
| late, failed: votes to all against the next leader | rounds/s | 10 | -13.8% | [-17.7%, -12.5%] | 0 (9) | 0.004 | 0.031 | no |
| late, trust2: votes to all against the next leader | M1 | 10 | +31.5% | [+12.2%, +49.3%] | 54 (10) | 0.004 | 0.031 | no |
| late, trust2: votes to all against the next leader | M2 | 10 | +14.0% | [+8.2%, +22.1%] | 53 (10) | 0.006 | 0.031 | no |
| late, trust2: votes to all against the next leader | rounds/s | 10 | -13.1% | [-16.4%, -10.0%] | 0 (10) | 0.002 | 0.023 | no |

### framers, votes to next

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 1.4 [1.3, 1.6] | 836.1 [754.2, 942.9] | 4612 [3667, 5521] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 2168 | 14.3 | 0 |
| aptos | 10 | 1.4 [1.3, 1.5] | 834.3 [788.2, 941.2] | 4738 [3544, 7331] | 78.17 [74.40, 82.67] | 0.00 [0.00, 0.00] | 2103 | 16.2 | 0 |
| failed | 10 | 1.4 [1.3, 1.5] | 830.3 [774.3, 891.6] | 4829 [2921, 7815] | 11.29 [4.56, 14.70] | 2.58 [1.61, 3.55] | 2208 | 13.1 | 75 |
| trust2 | 10 | 1.4 [1.3, 1.6] | 822.0 [718.0, 933.9] | 5038 [3776, 9423] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 2149 | 18.1 | 0 |

### framers, votes to all

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| none | 10 | 1.4 [1.2, 1.4] | 792.5 [752.9, 873.4] | 3524 [2807, 5100] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 1640 | 221.3 | 0 |
| aptos | 10 | 1.3 [1.2, 1.5] | 787.1 [693.1, 852.8] | 3810 [2478, 4581] | 70.60 [65.45, 73.82] | 0.00 [0.00, 0.00] | 1747 | 206.6 | 0 |
| failed | 10 | 1.3 [1.3, 1.4] | 782.7 [749.1, 818.9] | 3476 [2573, 4563] | 4.09 [2.18, 7.67] | 1.13 [0.32, 1.29] | 1618 | 237.9 | 30 |
| trust2 | 10 | 1.4 [1.3, 1.4] | 766.4 [738.6, 796.9] | 3328 [2769, 5091] | 0.00 [0.00, 2.03] | 0.00 [0.00, 0.32] | 1690 | 205.9 | 3 |

### framers: votes to all against votes to the next leader

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| framers, none: votes to all against the next leader | M1 | 10 | -4.2% | [-9.6%, +1.7%] | 12 (10) | 0.131 | 0.523 | yes |
| framers, none: votes to all against the next leader | M2 | 10 | -26.5% | [-30.7%, -7.5%] | 7 (10) | 0.037 | 0.223 | no |
| framers, none: votes to all against the next leader | rounds/s | 10 | -6.9% | [-13.8%, +0.0%] | 9 (9) | 0.137 | 0.523 | yes |
| framers, aptos: votes to all against the next leader | M1 | 10 | -4.6% | [-9.5%, -3.3%] | 1 (10) | 0.004 | 0.047 | yes |
| framers, aptos: votes to all against the next leader | M2 | 10 | -20.5% | [-36.8%, -12.8%] | 3 (10) | 0.010 | 0.088 | no |
| framers, aptos: votes to all against the next leader | rounds/s | 10 | -6.7% | [-7.1%, +0.0%] | 5 (7) | 0.172 | 0.523 | yes |
| framers, failed: votes to all against the next leader | M1 | 10 | -5.3% | [-8.3%, -2.4%] | 1 (10) | 0.004 | 0.047 | yes |
| framers, failed: votes to all against the next leader | M2 | 10 | -23.3% | [-30.4%, -19.6%] | 2 (10) | 0.006 | 0.059 | no |
| framers, failed: votes to all against the next leader | rounds/s | 10 | -7.1% | [-7.1%, -6.7%] | 8 (10) | 0.049 | 0.244 | yes |
| framers, trust2: votes to all against the next leader | M1 | 10 | -6.7% | [-11.4%, -2.9%] | 5 (10) | 0.020 | 0.156 | yes |
| framers, trust2: votes to all against the next leader | M2 | 10 | -25.3% | [-37.0%, -11.8%] | 6 (10) | 0.027 | 0.191 | no |
| framers, trust2: votes to all against the next leader | rounds/s | 10 | -6.9% | [-10.2%, +0.0%] | 11 (9) | 0.191 | 0.523 | yes |

### Silent leaders: the round by which all three are restricted (M5)

| votes | rule | runs | runs in which all are restricted | M5 |
|---|---|---|---|---|
| next | none | 10 | 0 | - |
| next | aptos | 10 | 10 | 78 [52, 127] |
| next | failed | 10 | 10 | 132 [88, 250] |
| next | trust2 | 10 | 10 | 120 [88, 210] |
| all | none | 10 | 0 | - |
| all | aptos | 10 | 10 | 78 [52, 127] |
| all | failed | 10 | 10 | 132 [88, 250] |
| all | trust2 | 10 | 10 | 120 [88, 210] |

## C. The failure threshold of the Aptos-style rule


### P10, by failure threshold

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| 5% | 10 | 6.0 [5.8, 6.6] | 82.8 [53.5, 96.6] | 674 [565, 887] | 22.38 [16.92, 28.82] | 0.00 [0.00, 0.00] | 11673 | 2.0 | 0 |
| 10% (default) | 10 | 6.2 [5.8, 6.6] | 74.5 [50.4, 96.9] | 671 [546, 727] | 11.75 [8.89, 16.63] | 0.00 [0.00, 0.00] | 11722 | 1.7 | 0 |
| 20% | 10 | 6.2 [5.8, 6.4] | 80.7 [63.8, 92.0] | 644 [595, 779] | 4.15 [1.71, 5.77] | 0.00 [0.00, 0.00] | 11689 | 1.7 | 0 |
| 30% | 10 | 6.1 [5.8, 6.4] | 85.1 [69.8, 96.6] | 675 [595, 784] | 1.87 [0.07, 4.95] | 0.00 [0.00, 0.00] | 11571 | 1.8 | 0 |

### S10, by failure threshold

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| 5% | 10 | 2.7 [0.5, 3.1] | 254.0 [201.7, 297.0] | 1916 [1525, 2116] | 53.76 [13.55, 56.61] | 0.00 [0.00, 0.00] | 4808 | 116.3 | 0 |
| 10% (default) | 10 | 2.8 [2.4, 3.3] | 229.4 [185.3, 283.2] | 1822 [1446, 2459] | 46.80 [34.92, 55.61] | 0.00 [0.00, 0.00] | 5394 | 109.9 | 0 |
| 20% | 10 | 2.8 [0.9, 3.2] | 221.3 [188.5, 260.7] | 1758 [1448, 1929] | 26.79 [10.48, 34.60] | 0.00 [0.00, 0.00] | 5122 | 107.4 | 0 |
| 30% | 10 | 2.8 [2.6, 3.3] | 233.6 [176.4, 262.1] | 1738 [1527, 2203] | 21.48 [11.79, 33.39] | 0.00 [0.00, 0.00] | 5376 | 113.3 | 0 |

## D. The G2 threshold


### Three silent leaders, by threshold (votes to the next leader)

| arm | runs | rounds/s | M1 timed-out rounds per 1000 | M2 end-to-end ms | M3 honest restricted % | M4 honest cut % | honest leads | AT per 1000 honest leads | honest convictions |
|---|---|---|---|---|---|---|---|---|---|
| ln 10^2 | 10 | 6.2 [5.7, 6.6] | 47.2 [36.8, 57.7] | 825 [716, 952] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 11405 | 0.8 | 0 |
| ln 300 | 10 | 5.6 [5.0, 6.3] | 63.6 [44.6, 80.8] | 946 [779, 1076] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 10351 | 1.4 | 0 |
| ln 10^3 | 10 | 5.2 [4.6, 5.7] | 77.8 [60.4, 100.6] | 1023 [916, 1186] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 9399 | 1.6 | 0 |
| ln 10^4 | 10 | 5.0 [4.4, 5.3] | 84.0 [72.4, 110.0] | 1074 [966, 1130] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 8965 | 1.6 | 0 |

| threshold | runs | M5 round by which all three are excluded |
|---|---|---|
| ln 10^2 | 10 | 93 [57, 210] |
| ln 300 | 10 | 120 [88, 210] |
| ln 10^3 | 10 | 142 [125, 347] |
| ln 10^4 | 10 | 180 [149, 447] |

### Selection (blocks 1-5)

| threshold | replayed honest convictions, P at 5% and 10% | honest leads | M1 with silent leaders (median) |
|---|---|---|---|
| ln 10^2 | 0 | 13869 | 49.0 |
| ln 300 | 0 | 13869 | 69.5 |
| ln 10^3 | 0 | 13869 | 76.1 |
| ln 10^4 | 0 | 13869 | 79.9 |

The rule fixed before the runs (no replayed conviction under P, then the fewest timeouts with silent leaders) selects: **ln 10^2**. The protocol uses ln 300, set on 2026-11-22.

For reference, model S at 5% and 10% on the same blocks: ln 10^2 21, ln 300 7, ln 10^3 1, ln 10^4 0 in 6866 honest leads.

### Evaluation (blocks 6-10)

| scenario | honest leads (none arm) | replayed, ln 10^2 | replayed, ln 300 | replayed, ln 10^3 | replayed, ln 10^4 | trust2 arm: convictions / honest leads |
|---|---|---|---|---|---|---|
| P2 | 8245 | 0 | 0 | 0 | 0 | 0 / 8263 |
| P5 | 8082 | 0 | 0 | 0 | 0 | 0 / 7986 |
| P10 | 5930 | 0 | 0 | 0 | 0 | 0 / 5839 |
| P20 | 1196 | 0 | 0 | 0 | 0 | 0 / 1207 |
| S2 | 5759 | 1 | 0 | 0 | 0 | 0 / 5967 |
| S5 | 3895 | 9 | 3 | 1 | 0 | 2 / 3965 |
| S10 | 2810 | 9 | 4 | 0 | 0 | 5 / 2696 |
| S20 | 1614 | 35 | 15 | 9 | 3 | 7 / 1605 |
| B2 | 7914 | 0 | 0 | 0 | 0 | 0 / 7924 |
| B5 | 7079 | 0 | 0 | 0 | 0 | 0 / 7011 |
| B10 | 5715 | 0 | 0 | 0 | 0 | 0 / 5712 |
| B20 | 3076 | 0 | 0 | 0 | 0 | 0 / 3115 |
| Q0.5 | 8276 | 0 | 0 | 0 | 0 | 0 / 8296 |
| Q1 | 8159 | 0 | 0 | 0 | 0 | 0 / 8169 |
| Q2 | 3926 | 0 | 0 | 0 | 0 | 0 / 4209 |
| Q3 | 1123 | 0 | 0 | 0 | 0 | 0 / 1229 |

## The sequences of adverse facts (R8; `none` arm, all blocks)

| scenario | honest leads | adverse share | P(adverse after normal) | P(adverse after adverse) | lag-1 autocorrelation | runs of 1 / 2 / 3 / 4+ |
|---|---|---|---|---|---|---|
| P2 | 16495 | 0.0000 | 0.0000 | 0.0000 | +0.000 | 0 / 0 / 0 / 0 |
| P5 | 16124 | 0.0002 | 0.0002 | 0.0000 | -0.000 | 3 / 0 / 0 / 0 |
| P10 | 11757 | 0.0011 | 0.0011 | 0.0000 | -0.001 | 13 / 0 / 0 / 0 |
| P20 | 2434 | 0.0185 | 0.0187 | 0.0222 | +0.004 | 43 / 1 / 0 / 0 |
| S2 | 11373 | 0.0229 | 0.0191 | 0.1858 | +0.162 | 167 / 45 / 1 / 0 |
| S5 | 7921 | 0.0568 | 0.0499 | 0.1774 | +0.123 | 311 / 51 / 8 / 3 |
| S10 | 5650 | 0.1037 | 0.0897 | 0.2340 | +0.135 | 351 / 90 / 13 / 4 |
| S20 | 3324 | 0.2247 | 0.2091 | 0.2882 | +0.073 | 405 / 96 / 36 / 10 |
| B2 | 15769 | 0.0004 | 0.0005 | 0.0000 | -0.000 | 7 / 0 / 0 / 0 |
| B5 | 14114 | 0.0010 | 0.0009 | 0.0714 | +0.070 | 12 / 1 / 0 / 0 |
| B10 | 11310 | 0.0039 | 0.0039 | 0.0238 | +0.019 | 42 / 1 / 0 / 0 |
| B20 | 6072 | 0.0142 | 0.0151 | 0.0000 | -0.014 | 86 / 0 / 0 / 0 |
| Q0.5 | 16553 | 0.0000 | 0.0000 | 0.0000 | +0.000 | 0 / 0 / 0 / 0 |
| Q1 | 16335 | 0.0000 | 0.0000 | 0.0000 | +0.000 | 0 / 0 / 0 / 0 |
| Q2 | 7539 | 0.0027 | 0.0026 | 0.0000 | -0.003 | 20 / 0 / 0 / 0 |
| Q3 | 2184 | 0.0014 | 0.0016 | 0.0000 | -0.002 | 3 / 0 / 0 / 0 |

Convictions per threshold: expected if the facts were independent, expected under the fitted two-state chain (200 simulated sets of sequences each), and replayed.

| scenario | honest leads | ln 10^2: independent / chain / replayed | ln 300: independent / chain / replayed | ln 10^3: independent / chain / replayed | ln 10^4: independent / chain / replayed |
|---|---|---|---|---|---|
| P2 | 16495 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 |
| P5 | 16124 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 |
| P10 | 11757 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 |
| P20 | 2434 | 0.03 / 0.01 / 0 | 0.01 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 |
| S2 | 11373 | 0.17 / 7.42 / 1 | 0.01 / 1.79 / 0 | 0.00 / 0.40 / 0 | 0.00 / 0.06 / 0 |
| S5 | 7921 | 1.93 / 12.93 / 12 | 0.32 / 3.44 / 4 | 0.03 / 0.73 / 1 | 0.00 / 0.08 / 0 |
| S10 | 5650 | 8.73 / 28.36 / 27 | 2.19 / 10.54 / 10 | 0.52 / 3.40 / 1 | 0.03 / 0.73 / 0 |
| S20 | 3324 | 45.14 / 58.20 / 67 | 19.18 / 26.92 / 29 | 7.12 / 10.78 / 13 | 1.29 / 2.39 / 4 |
| B2 | 15769 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 |
| B5 | 14114 | 0.00 / 0.09 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 |
| B10 | 11310 | 0.01 / 0.04 / 0 | 0.00 / 0.01 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 |
| B20 | 6072 | 0.02 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 |
| Q0.5 | 16553 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 |
| Q1 | 16335 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 |
| Q2 | 7539 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 |
| Q3 | 2184 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 | 0.00 / 0.00 / 0 |

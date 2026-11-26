## honest convictions: runs with at least one, convicted members, per scenario and rule
P20           failed runs 10 convictions 107 in 10 runs; members 107; max per run 15; cut max 4.84%; leads 2436
S2            failed runs 10 convictions 1 in 1 runs; members 1; max per run 1; cut max 0.10%; leads 11459
S5            failed runs 10 convictions 4 in 4 runs; members 4; max per run 1; cut max 0.32%; leads 7931
S5            trust2 runs 10 convictions 2 in 2 runs; members 2; max per run 1; cut max 0.32%; leads 8026
S10           failed runs 10 convictions 9 in 5 runs; members 9; max per run 2; cut max 0.65%; leads 5321
S10           trust2 runs 10 convictions 10 in 7 runs; members 10; max per run 3; cut max 0.97%; leads 5560
S20           failed runs 10 convictions 22 in 9 runs; members 22; max per run 3; cut max 0.97%; leads 3470
S20           trust2 runs 10 convictions 23 in 8 runs; members 23; max per run 5; cut max 1.61%; leads 3242
B20           failed runs 10 convictions 7 in 6 runs; members 7; max per run 2; cut max 0.65%; leads 5969
Q2            failed runs 10 convictions 19 in 7 runs; members 19; max per run 9; cut max 2.90%; leads 8353
Q3            failed runs 10 convictions 15 in 1 runs; members 15; max per run 15; cut max 4.84%; leads 2399
late-all      failed runs 10 convictions 1 in 1 runs; members 1; max per run 1; cut max 0.32%; leads 9506
framers-next  failed runs 10 convictions 75 in 10 runs; members 75; max per run 11; cut max 3.55%; leads 2208
framers-all   failed runs 10 convictions 30 in 10 runs; members 30; max per run 4; cut max 1.29%; leads 1618
framers-all   trust2 runs 10 convictions 3 in 3 runs; members 3; max per run 1; cut max 0.32%; leads 1690

## byzantine members: restricted share (aptos: member-epochs at failed weight; others: exclusions)
silent-next   aptos  byzantine member-epochs at failed weight: median 83.5% [81.0, 87.0]
silent-next   failed exclusions of byzantine members per run: median 6.0 [5, 6], total 59
silent-next   trust2 exclusions of byzantine members per run: median 6.0 [6, 6], total 60
silent-all    aptos  byzantine member-epochs at failed weight: median 83.6% [78.8, 86.5]
silent-all    failed exclusions of byzantine members per run: median 6.0 [6, 7], total 63
silent-all    trust2 exclusions of byzantine members per run: median 6.0 [6, 7], total 63
framers-next  aptos  byzantine member-epochs at failed weight: median 74.6% [71.2, 87.5]
framers-next  failed exclusions of byzantine members per run: median 2.5 [0, 5], total 27
framers-next  trust2 exclusions of byzantine members per run: median 0.0 [0, 0], total 0
framers-all   aptos  byzantine member-epochs at failed weight: median 72.2% [46.7, 80.3]
framers-all   failed exclusions of byzantine members per run: median 1.0 [0, 2], total 10
framers-all   trust2 exclusions of byzantine members per run: median 0.0 [0, 1], total 2

## totals of the trust2 and failed arms by model (part A)
P failed runs 40 honest leads 46608 accusations 57 convictions 107
P trust2 runs 40 honest leads 46550 accusations 74 convictions 0
S failed runs 40 honest leads 28181 accusations 2004 convictions 36
S trust2 runs 40 honest leads 28483 accusations 1968 convictions 35
B failed runs 40 honest leads 47101 accusations 150 convictions 7
B trust2 runs 40 honest leads 47489 accusations 151 convictions 0
Q failed runs 40 honest leads 43639 accusations 14 convictions 34
Q trust2 runs 40 honest leads 42628 accusations 18 convictions 0

## throughput and timeouts per run (part A, trust2): committed tps median, runs without commits
P2    trust2 e2e tps median 9991 [9987, 9996]; runs without a latency 0; ledger conflicts 0
P5    trust2 e2e tps median 9992 [9983, 10002]; runs without a latency 0; ledger conflicts 0
P10   trust2 e2e tps median 9980 [9953, 10011]; runs without a latency 0; ledger conflicts 0
P20   trust2 e2e tps median 6004 [3102, 7104]; runs without a latency 0; ledger conflicts 0
S2    trust2 e2e tps median 9992 [9983, 10087]; runs without a latency 0; ledger conflicts 0
S5    trust2 e2e tps median 10025 [9987, 10214]; runs without a latency 0; ledger conflicts 0
S10   trust2 e2e tps median 10008 [9752, 10082]; runs without a latency 0; ledger conflicts 0
S20   trust2 e2e tps median 9234 [8206, 9682]; runs without a latency 0; ledger conflicts 0
B2    trust2 e2e tps median 9984 [9801, 9988]; runs without a latency 0; ledger conflicts 0
B5    trust2 e2e tps median 9784 [9665, 9851]; runs without a latency 0; ledger conflicts 0
B10   trust2 e2e tps median 9638 [9403, 9933]; runs without a latency 0; ledger conflicts 0
B20   trust2 e2e tps median 9404 [9011, 9699]; runs without a latency 0; ledger conflicts 0
Q0.5  trust2 e2e tps median 9990 [9984, 9992]; runs without a latency 0; ledger conflicts 0
Q1    trust2 e2e tps median 9990 [9986, 10000]; runs without a latency 0; ledger conflicts 0
Q2    trust2 e2e tps median 6944 [3341, 8924]; runs without a latency 0; ledger conflicts 0
Q3    none   e2e tps median 0 [0, 2562]; runs without a latency 7; ledger conflicts 0
Q3    aptos  e2e tps median 139 [0, 8038]; runs without a latency 5; ledger conflicts 0
Q3    failed e2e tps median 0 [0, 9897]; runs without a latency 6; ledger conflicts 0
Q3    trust2 e2e tps median 0 [0, 10383]; runs without a latency 7; ledger conflicts 0

## ledger conflicts over all runs: 0.0 ; runs 930 ; blocks [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

## selection set: silent runs, M1 and rounds/s medians by threshold, blocks 1-5 and 6-10
ln 10^2  blocks 1-5: M1 49.0 rounds/s 6.1 M5 84 honest convictions 0
ln 10^2  blocks 6-10: M1 46.0 rounds/s 6.2 M5 98 honest convictions 0
ln 300   blocks 1-5: M1 69.5 rounds/s 5.4 M5 110 honest convictions 0
ln 300   blocks 6-10: M1 57.6 rounds/s 5.8 M5 130 honest convictions 0
ln 10^3  blocks 1-5: M1 76.1 rounds/s 5.2 M5 133 honest convictions 0
ln 10^3  blocks 6-10: M1 79.5 rounds/s 5.1 M5 152 honest convictions 0
ln 10^4  blocks 1-5: M1 79.9 rounds/s 5.1 M5 218 honest convictions 0
ln 10^4  blocks 6-10: M1 84.1 rounds/s 4.9 M5 174 honest convictions 0

## paired comparisons of the thresholds with silent leaders (against ln 300)

### silent leaders: thresholds against ln 300

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| ln 10^2 against ln 300 | M1 | 10 | -20.9% | [-25.4%, -17.0%] | 0 (10) | 0.002 | 0.018 | no |
| ln 10^2 against ln 300 | M2 | 10 | -8.2% | [-17.5%, -6.2%] | 1 (10) | 0.004 | 0.018 | no |
| ln 10^2 against ln 300 | rounds/s | 10 | +7.2% | [+4.8%, +11.3%] | 55 (10) | 0.002 | 0.018 | yes |
| ln 10^3 against ln 300 | M1 | 10 | +19.3% | [+13.4%, +32.9%] | 55 (10) | 0.002 | 0.018 | no |
| ln 10^3 against ln 300 | M2 | 10 | +9.6% | [+3.5%, +14.3%] | 55 (10) | 0.002 | 0.018 | yes |
| ln 10^3 against ln 300 | rounds/s | 10 | -5.8% | [-10.2%, -3.8%] | 0 (10) | 0.002 | 0.018 | yes |
| ln 10^4 against ln 300 | M1 | 10 | +36.8% | [+25.8%, +52.7%] | 55 (10) | 0.002 | 0.018 | no |
| ln 10^4 against ln 300 | M2 | 10 | +15.5% | [+5.3%, +21.4%] | 51 (10) | 0.014 | 0.018 | no |
| ln 10^4 against ln 300 | rounds/s | 10 | -11.6% | [-15.2%, -8.6%] | 0 (10) | 0.002 | 0.018 | no |

### silent leaders, votes to the next leader: trust2 against the other rules

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| trust2 against none | M1 | 10 | -69.8% | [-73.9%, -66.4%] | 0 (10) | 0.002 | 0.018 | no |
| trust2 against none | M2 | 10 | -37.8% | [-42.5%, -35.7%] | 0 (10) | 0.002 | 0.018 | no |
| trust2 against none | rounds/s | 10 | +82.8% | [+78.6%, +96.7%] | 55 (10) | 0.002 | 0.018 | no |
| trust2 against aptos | M1 | 10 | +44.4% | [+36.8%, +71.4%] | 55 (10) | 0.002 | 0.018 | no |
| trust2 against aptos | M2 | 10 | +22.0% | [+16.2%, +30.0%] | 55 (10) | 0.002 | 0.018 | no |
| trust2 against aptos | rounds/s | 10 | -10.5% | [-17.0%, -9.1%] | 0 (10) | 0.002 | 0.018 | no |
| trust2 against failed | M1 | 10 | -0.1% | [-3.8%, +0.2%] | 23 (10) | 0.695 | 1.000 | yes |
| trust2 against failed | M2 | 10 | +0.2% | [-0.3%, +3.2%] | 28 (9) | 0.570 | 1.000 | yes |
| trust2 against failed | rounds/s | 10 | +0.0% | [-1.8%, +2.0%] | 11 (6) | 0.938 | 1.000 | yes |

### silent leaders, votes to all: trust2 against the other rules

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| trust2 against none | M1 | 10 | -74.4% | [-75.2%, -73.2%] | 0 (10) | 0.002 | 0.018 | no |
| trust2 against none | M2 | 10 | -45.4% | [-46.3%, -41.6%] | 0 (10) | 0.002 | 0.018 | no |
| trust2 against none | rounds/s | 10 | +61.2% | [+55.6%, +66.7%] | 55 (10) | 0.002 | 0.018 | no |
| trust2 against aptos | M1 | 10 | +29.1% | [+23.2%, +42.7%] | 55 (10) | 0.002 | 0.018 | no |
| trust2 against aptos | M2 | 10 | +10.8% | [+7.0%, +16.1%] | 55 (10) | 0.002 | 0.018 | no |
| trust2 against aptos | rounds/s | 10 | -4.2% | [-6.0%, -4.1%] | 0 (10) | 0.002 | 0.018 | yes |
| trust2 against failed | M1 | 10 | +1.3% | [-2.0%, +5.3%] | 31 (9) | 0.359 | 0.750 | yes |
| trust2 against failed | M2 | 10 | +0.2% | [-0.2%, +2.5%] | 27 (8) | 0.250 | 0.750 | yes |
| trust2 against failed | rounds/s | 10 | +0.0% | [+0.0%, +0.7%] | 11 (5) | 0.438 | 0.750 | yes |

### framers, votes to the next leader: trust2 against the other rules

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| trust2 against none | M1 | 10 | -1.5% | [-11.0%, +6.5%] | 25 (10) | 0.846 | 1.000 | yes |
| trust2 against none | M2 | 10 | +7.2% | [+2.5%, +25.0%] | 42 (10) | 0.160 | 1.000 | no |
| trust2 against none | rounds/s | 10 | +0.0% | [-7.1%, +11.3%] | 24 (8) | 0.438 | 1.000 | yes |
| trust2 against aptos | M1 | 10 | -0.1% | [-7.4%, +2.9%] | 21 (10) | 0.557 | 1.000 | yes |
| trust2 against aptos | M2 | 10 | +3.8% | [-14.7%, +40.8%] | 36 (10) | 0.432 | 1.000 | no |
| trust2 against aptos | rounds/s | 10 | +0.0% | [-6.7%, +7.7%] | 20 (7) | 0.375 | 1.000 | yes |
| trust2 against failed | M1 | 10 | -1.2% | [-7.0%, +2.1%] | 23 (10) | 0.695 | 1.000 | yes |
| trust2 against failed | M2 | 10 | +11.8% | [-13.4%, +24.0%] | 35 (10) | 0.492 | 1.000 | no |
| trust2 against failed | rounds/s | 10 | +0.0% | [+0.0%, +7.1%] | 8 (5) | 1.000 | 1.000 | yes |

### framers, votes to all: trust2 against the other rules

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| trust2 against none | M1 | 10 | -3.5% | [-5.7%, +0.1%] | 8 (10) | 0.049 | 0.439 | yes |
| trust2 against none | M2 | 10 | -3.1% | [-14.6%, +12.8%] | 28 (10) | 1.000 | 1.000 | yes |
| trust2 against none | rounds/s | 10 | +0.0% | [+0.0%, +4.2%] | 9 (4) | 0.250 | 1.000 | yes |
| trust2 against aptos | M1 | 10 | -3.4% | [-6.5%, +0.9%] | 14 (10) | 0.193 | 1.000 | yes |
| trust2 against aptos | M2 | 10 | +11.5% | [-21.5%, +25.6%] | 35 (10) | 0.492 | 1.000 | no |
| trust2 against aptos | rounds/s | 10 | +3.8% | [-7.1%, +7.7%] | 26 (8) | 0.258 | 1.000 | yes |
| trust2 against failed | M1 | 10 | -1.3% | [-4.3%, -0.9%] | 9 (10) | 0.064 | 0.516 | yes |
| trust2 against failed | M2 | 10 | +5.7% | [-14.7%, +20.5%] | 34 (10) | 0.557 | 1.000 | no |
| trust2 against failed | rounds/s | 10 | +0.0% | [+0.0%, +7.7%] | 18 (6) | 0.125 | 0.875 | yes |

### late, votes to all: trust2 against the other rules

| comparison | metric | blocks | median relative difference | 90% interval | signed rank W (n) | p | p (Holm) | within +-15% |
|---|---|---|---|---|---|---|---|---|
| trust2 against none | M1 | 10 | +1.4% | [-10.7%, +5.4%] | 24 (10) | 0.770 | 1.000 | yes |
| trust2 against none | M2 | 10 | -5.6% | [-10.1%, +2.4%] | 18 (10) | 0.375 | 1.000 | yes |
| trust2 against none | rounds/s | 10 | +0.9% | [-3.6%, +1.9%] | 22 (9) | 1.000 | 1.000 | yes |
| trust2 against aptos | M1 | 10 | +3.7% | [-3.6%, +6.4%] | 35 (10) | 0.492 | 1.000 | yes |
| trust2 against aptos | M2 | 10 | -0.8% | [-5.5%, +8.4%] | 31 (10) | 0.770 | 1.000 | yes |
| trust2 against aptos | rounds/s | 10 | -3.6% | [-4.6%, +1.8%] | 7 (9) | 0.070 | 0.633 | yes |
| trust2 against failed | M1 | 10 | -7.6% | [-16.4%, +11.8%] | 20 (10) | 0.492 | 1.000 | no |
| trust2 against failed | M2 | 10 | -7.4% | [-13.7%, +1.4%] | 11 (10) | 0.105 | 0.844 | yes |
| trust2 against failed | rounds/s | 10 | +2.9% | [-3.6%, +8.7%] | 31 (9) | 0.344 | 1.000 | yes |

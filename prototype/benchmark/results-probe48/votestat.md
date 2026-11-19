# Votes to: broadcast

## /var/folders/qq/39nrh8px7332nc96rd2bd6340000gn/T/tmpqdyz5lrn.csv: 40 runs

| scenario | rule | timeouts | rounds/s | e2e ms | against honest leaders | excluded honest / faulty |
|---|---|---|---|---|---|---|
| late | none | 28 [24-31] | 5.5 [5.2-5.8] | 709 [700-828] | - | - |
| late | aptos | 30 [24-34] | 5.5 [5.2-5.8] | 780 [694-1029] | failed weight: 133 [79-194] member-epochs, 19 [13-30]% of honest | - |
| late | failed | 26 [25-32] | 5.7 [5.5-6.0] | 691 [671-914] | failed proposals 21 [19-27] | 0 / 0 (means 0.0 / 0.0); honest cut 0.00% |
| late | trust2 | 31 [26-37] | 5.2 [4.9-5.7] | 784 [744-874] | AT 28 [20-31] | 0 / 0 (means 0.0 / 0.0); honest cut 0.00% |
| framers+late | none | 139 [136-142] | 1.3 [1.2-1.4] | 3900 [2944-4628] | - | - |
| framers+late | aptos | 140 [138-142] | 1.3 [1.2-1.4] | 3561 [2792-4051] | failed weight: 185 [154-198] member-epochs, 79 [68-88]% of honest; faulty 65 [57-78]% | - |
| framers+late | failed | 138 [136-141] | 1.4 [1.2-1.4] | 3012 [2925-4799] | failed proposals 70 [65-75] | 7 [6-8] / 1 [0-1] (means 7.2 / 0.6); honest cut 2.26 [1.94-2.58]% |
| framers+late | trust2 | 140 [137-142] | 1.3 [1.2-1.4] | 3580 [3274-4784] | AT 40 [38-43] | 2 [0-4] / 0 [0-1] (means 2.0 / 0.4); honest cut 0.65 [0.00-1.29]% |

## Against Trust 2.0 (exact two-sided rank-sum test; relative difference of medians, bootstrap 95%)

- late, trust2 vs none: timeouts p=0.151, trust2 +10.7% [-7.1%, +32.1%]; rounds_per_s p=0.286, trust2 -5.5% [-10.9%, +3.6%]; e2e_latency_ms p=0.095, trust2 +10.6% [-5.3%, +23.3%]
- late, trust2 vs aptos: timeouts p=0.730, trust2 +3.3% [-13.3%, +29.2%]; rounds_per_s p=0.143, trust2 -5.5% [-10.9%, +3.6%]; e2e_latency_ms p=0.595, trust2 +0.5% [-23.8%, +20.9%]
- late, trust2 vs failed: timeouts p=0.119, trust2 +19.2% [-3.1%, +42.3%]; rounds_per_s p=0.032, trust2 -8.8% [-14.0%, +0.0%]; e2e_latency_ms p=0.222, trust2 +13.5% [-14.2%, +27.2%]
- framers+late, trust2 vs none: timeouts p=0.889, trust2 +0.7% [-2.8%, +2.9%]; rounds_per_s p=0.714, trust2 +0.0% [-14.3%, +8.3%]; e2e_latency_ms p=1.000, trust2 -8.2% [-23.5%, +30.7%]
- framers+late, trust2 vs aptos: timeouts p=1.000, trust2 +0.0% [-2.1%, +2.2%]; rounds_per_s p=0.881, trust2 +0.0% [-7.7%, +8.3%]; e2e_latency_ms p=0.548, trust2 +0.5% [-12.6%, +37.8%]
- framers+late, trust2 vs failed: timeouts p=0.357, trust2 +1.4% [-1.4%, +3.6%]; rounds_per_s p=0.429, trust2 -7.1% [-14.3%, +8.3%]; e2e_latency_ms p=0.151, trust2 +18.9% [-25.4%, +58.8%]

# Votes to: forward

## /var/folders/qq/39nrh8px7332nc96rd2bd6340000gn/T/tmpnvorhcxb.csv: 40 runs

| scenario | rule | timeouts | rounds/s | e2e ms | against honest leaders | excluded honest / faulty |
|---|---|---|---|---|---|---|
| late | none | 11 [8-23] | 7.5 [7.2-8.1] | 445 [371-495] | - | - |
| late | aptos | 11 [8-17] | 7.6 [7.2-7.8] | 441 [415-509] | failed weight: 52 [29-77] member-epochs, 6 [3-9]% of honest | - |
| late | failed | 14 [9-14] | 7.6 [7.5-7.8] | 439 [414-457] | failed proposals 6 [4-6] | 0 / 0 (means 0.0 / 0.0); honest cut 0.00% |
| late | trust2 | 12 [11-21] | 7.5 [7.2-7.7] | 445 [441-497] | AT 6 [5-9] | 0 [0-1] / 0 (means 0.2 / 0.0); honest cut 0.00 [0.00-0.32]% |
| framers+late | none | 81 [75-85] | 3.4 [3.4-3.6] | 1191 [1065-1304] | - | - |
| framers+late | aptos | 78 [73-82] | 3.7 [3.4-3.7] | 1144 [1088-1290] | failed weight: 334 [276-371] member-epochs, 52 [39-55]% of honest; faulty 40 [18-57]% | - |
| framers+late | failed | 75 [70-86] | 3.8 [3.2-3.9] | 1094 [1032-1296] | failed proposals 56 [54-62] | 1 [0-3] / 0 [0-2] (means 1.2 / 0.4); honest cut 0.31 [0.00-0.97]% |
| framers+late | trust2 | 77 [71-78] | 3.7 [3.6-3.9] | 1090 [1051-1166] | AT 1 [0-1] | 0 / 0 (means 0.0 / 0.0); honest cut 0.00% |

## Against Trust 2.0 (exact two-sided rank-sum test; relative difference of medians, bootstrap 95%)

- late, trust2 vs none: timeouts p=0.683, trust2 +9.1% [-47.8%, +90.9%]; rounds_per_s p=0.603, trust2 +0.0% [-7.4%, +4.2%]; e2e_latency_ms p=0.690, trust2 +0.0% [-10.1%, +19.9%]
- late, trust2 vs aptos: timeouts p=0.270, trust2 +9.1% [-31.2%, +110.0%]; rounds_per_s p=0.643, trust2 -1.3% [-5.3%, +4.2%]; e2e_latency_ms p=0.579, trust2 +0.9% [-12.6%, +12.7%]
- late, trust2 vs failed: timeouts p=0.873, trust2 -14.3% [-21.4%, +75.0%]; rounds_per_s p=0.119, trust2 -1.3% [-5.3%, +1.3%]; e2e_latency_ms p=0.071, trust2 +1.4% [-2.6%, +13.2%]
- framers+late, trust2 vs none: timeouts p=0.087, trust2 -4.9% [-14.1%, +2.7%]; rounds_per_s p=0.024, trust2 +8.8% [+2.8%, +14.7%]; e2e_latency_ms p=0.056, trust2 -8.5% [-16.8%, +2.3%]
- framers+late, trust2 vs aptos: timeouts p=0.190, trust2 -1.3% [-10.1%, +5.5%]; rounds_per_s p=0.524, trust2 +0.0% [-2.7%, +8.8%]; e2e_latency_ms p=0.222, trust2 -4.7% [-15.5%, +4.0%]
- framers+late, trust2 vs failed: timeouts p=0.706, trust2 +2.7% [-10.5%, +10.0%]; rounds_per_s p=0.992, trust2 -2.6% [-5.3%, +15.6%]; e2e_latency_ms p=0.968, trust2 -0.4% [-15.9%, +9.7%]

# forward against broadcast, cell by cell

## late

- none (5 v 5 runs)
  - timeouts: broadcast 28 [24-31] / forward 11 [8-23], p=0.008, forward -60.7% [-71.4%, -17.9%]
  - rounds_per_s: broadcast 5.5 [5.2-5.8] / forward 7.5 [7.2-8.1], p=0.008, forward +36.4% [+29.3%, +47.3%]
  - e2e_latency_ms: broadcast 709 [700-828] / forward 445 [371-495], p=0.008, forward -37.2% [-49.5%, -30.2%]
- aptos (5 v 5 runs)
  - timeouts: broadcast 30 [24-34] / forward 11 [8-17], p=0.008, forward -63.3% [-73.3%, -37.0%]
  - rounds_per_s: broadcast 5.5 [5.2-5.8] / forward 7.6 [7.2-7.8], p=0.008, forward +38.2% [+30.9%, +47.2%]
  - e2e_latency_ms: broadcast 780 [694-1029] / forward 441 [415-509], p=0.008, forward -43.5% [-57.1%, -33.6%]
  - honest member-epochs at the failed weight, %: broadcast 18.65 [12.74-29.80] / forward 5.59 [3.12-9.20], p=0.008, forward -70.0% [-85.5%, -47.9%]
- failed (5 v 5 runs)
  - timeouts: broadcast 26 [25-32] / forward 14 [9-14], p=0.008, forward -46.2% [-65.4%, -44.0%]
  - rounds_per_s: broadcast 5.7 [5.5-6.0] / forward 7.6 [7.5-7.8], p=0.008, forward +33.3% [+26.7%, +38.2%]
  - e2e_latency_ms: broadcast 691 [671-914] / forward 439 [414-457], p=0.008, forward -36.5% [-52.0%, -33.9%]
  - failed proposals of honest leaders: broadcast 21.00 [19.00-27.00] / forward 6.00 [4.00-6.00], p=0.008, forward -71.4% [-81.0%, -68.4%]
  - honest leaders excluded: broadcast 0.00 / forward 0.00, p=1.000
  - honest cut, %: broadcast 0.00 / forward 0.00, p=1.000
- trust2 (5 v 5 runs)
  - timeouts: broadcast 31 [26-37] / forward 12 [11-21], p=0.008, forward -61.3% [-67.6%, -30.0%]
  - rounds_per_s: broadcast 5.2 [4.9-5.7] / forward 7.5 [7.2-7.7], p=0.008, forward +44.2% [+31.6%, +53.1%]
  - e2e_latency_ms: broadcast 784 [744-874] / forward 445 [441-497], p=0.008, forward -43.2% [-49.1%, -36.6%]
  - AT against honest leaders: broadcast 28.00 [20.00-31.00] / forward 6.00 [5.00-9.00], p=0.008, forward -78.6% [-82.1%, -66.7%]
  - honest leaders excluded: broadcast 0.00 / forward 0.00 [0.00-1.00], p=1.000
  - honest cut, %: broadcast 0.00 / forward 0.00 [0.00-0.32], p=1.000

- pooled over the rules of late (forward against broadcast; bootstrap 95%, permutation test within a rule):
  - timeouts: -57.9% [-62.6%, -41.3%], p=0.0733
  - rounds_per_s: +38.0% [+33.9%, +42.9%], p=0.0000
  - e2e_latency_ms: -40.1% [-46.3%, -37.2%], p=0.0687

## framers+late

- none (5 v 5 runs)
  - timeouts: broadcast 139 [136-142] / forward 81 [75-85], p=0.008, forward -41.7% [-46.0%, -38.8%]
  - rounds_per_s: broadcast 1.3 [1.2-1.4] / forward 3.4 [3.4-3.6], p=0.008, forward +161.5% [+142.9%, +183.3%]
  - e2e_latency_ms: broadcast 3900 [2944-4628] / forward 1191 [1065-1304], p=0.008, forward -69.5% [-74.4%, -59.5%]
- aptos (5 v 5 runs)
  - timeouts: broadcast 140 [138-142] / forward 78 [73-82], p=0.008, forward -44.3% [-47.9%, -41.4%]
  - rounds_per_s: broadcast 1.3 [1.2-1.4] / forward 3.7 [3.4-3.7], p=0.008, forward +184.6% [+161.5%, +208.3%]
  - e2e_latency_ms: broadcast 3561 [2792-4051] / forward 1144 [1088-1290], p=0.008, forward -67.9% [-71.8%, -59.0%]
  - honest member-epochs at the failed weight, %: broadcast 78.67 [68.44-88.00] / forward 52.15 [39.43-54.96], p=0.008, forward -33.7% [-49.9%, -23.8%]
- failed (5 v 5 runs)
  - timeouts: broadcast 138 [136-141] / forward 75 [70-86], p=0.008, forward -45.7% [-49.3%, -37.7%]
  - rounds_per_s: broadcast 1.4 [1.2-1.4] / forward 3.8 [3.2-3.9], p=0.008, forward +171.4% [+128.6%, +216.7%]
  - e2e_latency_ms: broadcast 3012 [2925-4799] / forward 1094 [1032-1296], p=0.008, forward -63.7% [-77.2%, -57.0%]
  - failed proposals of honest leaders: broadcast 70.00 [65.00-75.00] / forward 56.00 [54.00-62.00], p=0.008, forward -20.0% [-26.7%, -10.8%]
  - honest leaders excluded: broadcast 7.00 [6.00-8.00] / forward 1.00 [0.00-3.00], p=0.008, forward -85.7% [-100.0%, -57.1%]
  - honest cut, %: broadcast 2.26 [1.94-2.58] / forward 0.31 [0.00-0.97], p=0.008, forward -86.3% [-100.0%, -57.1%]
- trust2 (5 v 5 runs)
  - timeouts: broadcast 140 [137-142] / forward 77 [71-78], p=0.008, forward -45.0% [-49.3%, -43.5%]
  - rounds_per_s: broadcast 1.3 [1.2-1.4] / forward 3.7 [3.6-3.9], p=0.008, forward +184.6% [+164.3%, +208.3%]
  - e2e_latency_ms: broadcast 3580 [3274-4784] / forward 1090 [1051-1166], p=0.008, forward -69.6% [-77.2%, -66.7%]
  - AT against honest leaders: broadcast 40.00 [38.00-43.00] / forward 1.00 [0.00-1.00], p=0.008, forward -97.5% [-100.0%, -97.4%]
  - honest leaders excluded: broadcast 2.00 [0.00-4.00] / forward 0.00, p=0.048, forward -100.0%
  - honest cut, %: broadcast 0.65 [0.00-1.29] / forward 0.00, p=0.048, forward -100.0%

- pooled over the rules of framers+late (forward against broadcast; bootstrap 95%, permutation test within a rule):
  - timeouts: -44.2% [-46.1%, -42.2%], p=0.1537
  - rounds_per_s: +175.5% [+162.2%, +189.0%], p=0.0000
  - e2e_latency_ms: -67.6% [-71.1%, -63.9%], p=0.3392


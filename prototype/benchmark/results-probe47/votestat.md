# Votes to: next leader

## /var/folders/qq/39nrh8px7332nc96rd2bd6340000gn/T/tmpeg1t62oj.csv: 60 runs

| scenario | rule | timeouts | rounds/s | e2e ms | against honest leaders | excluded honest / faulty |
|---|---|---|---|---|---|---|
| silent | none | 49 [49-59] | 3.6 [2.8-3.8] | 1500 [1207-1694] | - | - |
| silent | aptos | 17 [12-28] | 6.8 [5.8-7.2] | 644 [552-896] | failed weight: - member-epochs, 0% of honest; faulty 82 [80-92]% | - |
| silent | failed | 24 [19-32] | 6.0 [5.6-6.5] | 870 [720-900] | failed proposals 1 [0-1] | 0 / 3 (means 0.0 / 3.0); honest cut 0.00% |
| silent | trust2 | 23 [20-26] | 6.2 [5.9-6.5] | 782 [639-964] | AT 0 [0-2] | 0 / 3 (means 0.0 / 3.0); honest cut 0.00% |
| late | none | 20 [16-27] | 6.5 [5.6-6.5] | 613 [605-768] | - | - |
| late | aptos | 21 [15-24] | 6.2 [5.8-6.8] | 634 [534-822] | failed weight: 103 [68-136] member-epochs, 14 [9-19]% of honest | - |
| late | failed | 24 [18-25] | 6.0 [5.7-6.5] | 705 [621-816] | failed proposals 20 [18-22] | 0 / 0 (means 0.0 / 0.0); honest cut 0.00% |
| late | trust2 | 25 [19-30] | 5.8 [5.2-6.0] | 694 [667-932] | AT 2 [0-4] | 0 / 0 (means 0.0 / 0.0); honest cut 0.00% |
| framers+late | none | 139 [138-145] | 1.4 [1.3-1.5] | 5516 [4009-6908] | - | - |
| framers+late | aptos | 138 [136-146] | 1.5 [1.2-1.5] | 4875 [3778-8984] | failed weight: 203 [167-247] member-epochs, 87 [77-90]% of honest; faulty 88 [78-90]% | - |
| framers+late | failed | 140 [138-142] | 1.4 [1.4-1.5] | 5056 [3626-5870] | failed proposals 98 [87-106] | 11 [10-14] / 4 [1-5] (means 11.6 / 3.4); honest cut 3.55 [3.23-4.52]% |
| framers+late | trust2 | 140 [137-143] | 1.4 | 4732 [4313-6152] | AT 3 [2-7] | 0 / 0 (means 0.0 / 0.0); honest cut 0.00% |

## Against Trust 2.0 (exact two-sided rank-sum test; relative difference of medians, bootstrap 95%)

- silent, trust2 vs none: timeouts p=0.008, trust2 -53.1% [-66.1%, -46.9%]; rounds_per_s p=0.008, trust2 +72.2% [+60.5%, +124.1%]; e2e_latency_ms p=0.008, trust2 -47.9% [-57.5%, -30.5%]
- silent, trust2 vs aptos: timeouts p=0.651, trust2 +35.3% [-25.9%, +91.7%]; rounds_per_s p=0.595, trust2 -8.8% [-15.3%, +8.6%]; e2e_latency_ms p=0.421, trust2 +21.4% [-21.4%, +53.5%]
- silent, trust2 vs failed: timeouts p=0.738, trust2 -4.2% [-28.1%, +21.1%]; rounds_per_s p=0.516, trust2 +3.3% [-6.2%, +12.1%]; e2e_latency_ms p=0.690, trust2 -10.1% [-26.6%, +21.8%]
- late, trust2 vs none: timeouts p=0.413, trust2 +25.0% [-18.5%, +57.9%]; rounds_per_s p=0.056, trust2 -10.8% [-20.0%, +3.6%]; e2e_latency_ms p=0.143, trust2 +13.2% [-9.6%, +52.0%]
- late, trust2 vs aptos: timeouts p=0.111, trust2 +19.0% [-9.5%, +66.7%]; rounds_per_s p=0.095, trust2 -6.5% [-19.1%, +1.7%]; e2e_latency_ms p=0.095, trust2 +9.5% [-15.6%, +48.9%]
- late, trust2 vs failed: timeouts p=0.310, trust2 +4.2% [-20.8%, +44.4%]; rounds_per_s p=0.143, trust2 -3.3% [-15.4%, +1.8%]; e2e_latency_ms p=0.690, trust2 -1.6% [-15.0%, +32.2%]
- framers+late, trust2 vs none: timeouts p=1.000, trust2 +0.7% [-3.4%, +2.9%]; rounds_per_s p=1.000, trust2 +0.0% [-6.7%, +7.7%]; e2e_latency_ms p=0.421, trust2 -14.2% [-35.2%, +28.0%]
- framers+late, trust2 vs aptos: timeouts p=0.786, trust2 +1.4% [-4.8%, +3.7%]; rounds_per_s p=0.643, trust2 -6.7% [-6.7%, +16.7%]; e2e_latency_ms p=1.000, trust2 -2.9% [-47.3%, +37.0%]
- framers+late, trust2 vs failed: timeouts p=1.000, trust2 +0.0% [-2.1%, +2.2%]; rounds_per_s p=0.444, trust2 +0.0% [-6.7%, +0.0%]; e2e_latency_ms p=1.000, trust2 -6.4% [-19.4%, +33.2%]

# Votes to: broadcast

## /var/folders/qq/39nrh8px7332nc96rd2bd6340000gn/T/tmpgb4n5bhy.csv: 60 runs

| scenario | rule | timeouts | rounds/s | e2e ms | against honest leaders | excluded honest / faulty |
|---|---|---|---|---|---|---|
| silent | none | 38 [36-41] | 4.7 [4.2-4.9] | 899 [880-959] | - | - |
| silent | aptos | 9 [6-12] | 7.5 [7.3-7.9] | 449 [392-539] | failed weight: - member-epochs, 0% of honest; faulty 89 [80-91]% | - |
| silent | failed | 14 [13-17] | 6.9 [6.7-7.1] | 512 [467-556] | failed proposals 0 | 0 / 3 [3-4] (means 0.0 / 3.2); honest cut 0.00% |
| silent | trust2 | 15 [12-17] | 7.0 [6.8-7.0] | 499 [485-548] | AT 0 | 0 / 4 [3-4] (means 0.0 / 3.6); honest cut 0.00% |
| late | none | 30 [25-34] | 5.3 [4.8-5.7] | 766 [675-906] | - | - |
| late | aptos | 29 [26-30] | 5.5 [5.3-5.7] | 722 [710-793] | failed weight: 118 [106-138] member-epochs, 18 [16-20]% of honest | - |
| late | failed | 30 [25-37] | 5.5 [4.8-5.8] | 745 [673-920] | failed proposals 26 [19-28] | 0 / 0 (means 0.0 / 0.0); honest cut 0.00% |
| late | trust2 | 30 [23-37] | 5.4 [5.0-5.7] | 833 [619-916] | AT 25 [23-27] | 0 / 0 (means 0.0 / 0.0); honest cut 0.00% |
| framers+late | none | 138 [137-141] | 1.3 [1.2-1.4] | 3567 [3091-3884] | - | - |
| framers+late | aptos | 140 [138-141] | 1.3 [1.2-1.4] | 3944 [3069-5249] | failed weight: 188 [172-203] member-epochs, 78 [76-90]% of honest; faulty 65 [63-68]% | - |
| framers+late | failed | 138 [135-138] | 1.4 [1.2-1.4] | 3166 [3148-3599] | failed proposals 67 [62-74] | 6 [3-8] / 2 [1-3] (means 6.0 / 2.0); honest cut 1.94 [0.97-2.58]% |
| framers+late | trust2 | 140 [138-143] | 1.3 [1.2-1.4] | 4329 [2837-4653] | AT 39 [31-41] | 1 [0-3] / 1 [0-1] (means 1.4 / 0.6); honest cut 0.32 [0.00-0.97]% |

## Against Trust 2.0 (exact two-sided rank-sum test; relative difference of medians, bootstrap 95%)

- silent, trust2 vs none: timeouts p=0.008, trust2 -60.5% [-68.4%, -55.3%]; rounds_per_s p=0.008, trust2 +48.9% [+41.7%, +66.7%]; e2e_latency_ms p=0.008, trust2 -44.5% [-48.0%, -39.0%]
- silent, trust2 vs aptos: timeouts p=0.024, trust2 +66.7% [+16.7%, +150.0%]; rounds_per_s p=0.008, trust2 -6.7% [-11.4%, -4.1%]; e2e_latency_ms p=0.310, trust2 +11.1% [-7.4%, +32.4%]
- silent, trust2 vs failed: timeouts p=1.000, trust2 +7.1% [-17.6%, +21.4%]; rounds_per_s p=0.810, trust2 +1.4% [-4.2%, +4.5%]; e2e_latency_ms p=0.841, trust2 -2.5% [-10.3%, +8.3%]
- late, trust2 vs none: timeouts p=0.984, trust2 +0.0% [-23.3%, +24.0%]; rounds_per_s p=0.849, trust2 +1.9% [-9.1%, +12.5%]; e2e_latency_ms p=0.841, trust2 +8.7% [-19.2%, +23.4%]
- late, trust2 vs aptos: timeouts p=0.548, trust2 +3.4% [-20.7%, +27.6%]; rounds_per_s p=0.310, trust2 -1.8% [-10.5%, +3.6%]; e2e_latency_ms p=0.151, trust2 +15.4% [-14.3%, +26.9%]
- late, trust2 vs failed: timeouts p=0.913, trust2 +0.0% [-23.3%, +24.0%]; rounds_per_s p=0.643, trust2 -1.8% [-12.1%, +12.5%]; e2e_latency_ms p=1.000, trust2 +11.8% [-16.9%, +25.3%]
- framers+late, trust2 vs none: timeouts p=0.310, trust2 +1.4% [-1.4%, +3.6%]; rounds_per_s p=1.000, trust2 +0.0% [-7.7%, +8.3%]; e2e_latency_ms p=0.690, trust2 +21.4% [-21.7%, +40.1%]
- framers+late, trust2 vs aptos: timeouts p=0.929, trust2 +0.0% [-1.4%, +2.2%]; rounds_per_s p=1.000, trust2 +0.0% [-7.7%, +8.3%]; e2e_latency_ms p=1.000, trust2 +9.8% [-32.7%, +41.1%]
- framers+late, trust2 vs failed: timeouts p=0.079, trust2 +1.4% [+0.0%, +4.4%]; rounds_per_s p=0.762, trust2 -7.1% [-14.3%, +8.3%]; e2e_latency_ms p=0.690, trust2 +36.7% [-11.9%, +47.0%]

# Broadcast against next leader, cell by cell

## silent

- none (5 v 5 runs)
  - timeouts: next 49 [49-59] / broadcast 38 [36-41], p=0.008, broadcast -22.4% [-39.0%, -16.3%]
  - rounds_per_s: next 3.6 [2.8-3.8] / broadcast 4.7 [4.2-4.9], p=0.008, broadcast +30.6% [+16.7%, +69.0%]
  - e2e_latency_ms: next 1500 [1207-1694] / broadcast 899 [880-959], p=0.008, broadcast -40.1% [-46.9%, -25.5%]
- aptos (5 v 5 runs)
  - timeouts: next 17 [12-28] / broadcast 9 [6-12], p=0.024, broadcast -47.1% [-75.0%, -20.0%]
  - rounds_per_s: next 6.8 [5.8-7.2] / broadcast 7.5 [7.3-7.9], p=0.008, broadcast +10.3% [+2.8%, +29.3%]
  - e2e_latency_ms: next 644 [552-896] / broadcast 449 [392-539], p=0.008, broadcast -30.3% [-53.4%, -14.2%]
  - honest member-epochs at the failed weight, %: next 0.00 / broadcast 0.00, p=1.000
- failed (5 v 5 runs)
  - timeouts: next 24 [19-32] / broadcast 14 [13-17], p=0.008, broadcast -41.7% [-56.2%, -22.7%]
  - rounds_per_s: next 6.0 [5.6-6.5] / broadcast 6.9 [6.7-7.1], p=0.008, broadcast +15.0% [+6.2%, +23.2%]
  - e2e_latency_ms: next 870 [720-900] / broadcast 512 [467-556], p=0.008, broadcast -41.1% [-46.3%, -28.3%]
  - failed proposals of honest leaders: next 1.00 [0.00-1.00] / broadcast 0.00, p=0.048, broadcast -100.0%
  - honest leaders excluded: next 0.00 / broadcast 0.00, p=1.000
  - honest cut, %: next 0.00 / broadcast 0.00, p=1.000
- trust2 (5 v 5 runs)
  - timeouts: next 23 [20-26] / broadcast 15 [12-17], p=0.008, broadcast -34.8% [-47.8%, -25.0%]
  - rounds_per_s: next 6.2 [5.9-6.5] / broadcast 7.0 [6.8-7.0], p=0.008, broadcast +12.9% [+7.7%, +18.6%]
  - e2e_latency_ms: next 782 [639-964] / broadcast 499 [485-548], p=0.008, broadcast -36.2% [-48.2%, -21.9%]
  - AT against honest leaders: next 0.00 [0.00-2.00] / broadcast 0.00, p=0.444
  - honest leaders excluded: next 0.00 / broadcast 0.00, p=1.000
  - honest cut, %: next 0.00 / broadcast 0.00, p=1.000

- pooled over the rules of silent (broadcast against next leader; bootstrap 95%, permutation test within a rule):
  - timeouts: -36.5% [-46.7%, -26.0%], p=0.0088
  - rounds_per_s: +17.2% [+12.2%, +30.6%], p=0.0000
  - e2e_latency_ms: -36.9% [-43.5%, -29.1%], p=0.0164

## late

- none (5 v 5 runs)
  - timeouts: next 20 [16-27] / broadcast 30 [25-34], p=0.024, broadcast +50.0% [+3.7%, +87.5%]
  - rounds_per_s: next 6.5 [5.6-6.5] / broadcast 5.3 [4.8-5.7], p=0.016, broadcast -18.5% [-26.2%, -5.0%]
  - e2e_latency_ms: next 613 [605-768] / broadcast 766 [675-906], p=0.087, broadcast +25.0% [-0.9%, +47.8%]
- aptos (5 v 5 runs)
  - timeouts: next 21 [15-24] / broadcast 29 [26-30], p=0.008, broadcast +38.1% [+20.8%, +93.3%]
  - rounds_per_s: next 6.2 [5.8-6.8] / broadcast 5.5 [5.3-5.7], p=0.008, broadcast -11.3% [-19.1%, -3.4%]
  - e2e_latency_ms: next 634 [534-822] / broadcast 722 [710-793], p=0.151, broadcast +13.9% [-12.2%, +38.4%]
  - honest member-epochs at the failed weight, %: next 13.84 [8.77-19.07] / broadcast 18.13 [15.54-20.23], p=0.095, broadcast +30.9% [-5.0%, +106.6%]
- failed (5 v 5 runs)
  - timeouts: next 24 [18-25] / broadcast 30 [25-37], p=0.016, broadcast +25.0% [+4.2%, +66.7%]
  - rounds_per_s: next 6.0 [5.7-6.5] / broadcast 5.5 [4.8-5.8], p=0.024, broadcast -8.3% [-21.5%, -1.7%]
  - e2e_latency_ms: next 705 [621-816] / broadcast 745 [673-920], p=0.222, broadcast +5.7% [-9.5%, +35.9%]
  - failed proposals of honest leaders: next 20.00 [18.00-22.00] / broadcast 26.00 [19.00-28.00], p=0.119, broadcast +30.0% [-5.0%, +44.4%]
  - honest leaders excluded: next 0.00 / broadcast 0.00, p=1.000
  - honest cut, %: next 0.00 / broadcast 0.00, p=1.000
- trust2 (5 v 5 runs)
  - timeouts: next 25 [19-30] / broadcast 30 [23-37], p=0.111, broadcast +20.0% [-8.0%, +63.2%]
  - rounds_per_s: next 5.8 [5.2-6.0] / broadcast 5.4 [5.0-5.7], p=0.087, broadcast -6.9% [-15.0%, +3.8%]
  - e2e_latency_ms: next 694 [667-932] / broadcast 833 [619-916], p=0.548, broadcast +20.0% [-11.6%, +32.0%]
  - AT against honest leaders: next 2.00 [0.00-4.00] / broadcast 25.00 [23.00-27.00], p=0.008, broadcast +1150.0%
  - honest leaders excluded: next 0.00 / broadcast 0.00, p=1.000
  - honest cut, %: next 0.00 / broadcast 0.00, p=1.000

- pooled over the rules of late (broadcast against next leader; bootstrap 95%, permutation test within a rule):
  - timeouts: +33.3% [+18.5%, +56.0%], p=0.0000
  - rounds_per_s: -11.2% [-16.0%, -6.3%], p=0.0002
  - e2e_latency_ms: +16.1% [+4.7%, +29.8%], p=0.0042

## framers+late

- none (5 v 5 runs)
  - timeouts: next 139 [138-145] / broadcast 138 [137-141], p=0.278, broadcast -0.7% [-4.8%, +1.4%]
  - rounds_per_s: next 1.4 [1.3-1.5] / broadcast 1.3 [1.2-1.4], p=0.135, broadcast -7.1% [-14.3%, +0.0%]
  - e2e_latency_ms: next 5516 [4009-6908] / broadcast 3567 [3091-3884], p=0.008, broadcast -35.3% [-53.0%, -11.0%]
- aptos (5 v 5 runs)
  - timeouts: next 138 [136-146] / broadcast 140 [138-141], p=0.738, broadcast +1.4% [-4.8%, +2.9%]
  - rounds_per_s: next 1.5 [1.2-1.5] / broadcast 1.3 [1.2-1.4], p=0.302, broadcast -13.3% [-20.0%, +8.3%]
  - e2e_latency_ms: next 4875 [3778-8984] / broadcast 3944 [3069-5249], p=0.310, broadcast -19.1% [-56.6%, +11.6%]
  - honest member-epochs at the failed weight, %: next 87.20 [76.80-90.22] / broadcast 77.60 [76.44-90.22], p=0.460, broadcast -11.0% [-14.3%, +8.1%]
- failed (5 v 5 runs)
  - timeouts: next 140 [138-142] / broadcast 138 [135-138], p=0.032, broadcast -1.4% [-4.3%, +0.0%]
  - rounds_per_s: next 1.4 [1.4-1.5] / broadcast 1.4 [1.2-1.4], p=0.159, broadcast +0.0% [-14.3%, +0.0%]
  - e2e_latency_ms: next 5056 [3626-5870] / broadcast 3166 [3148-3599], p=0.008, broadcast -37.4% [-46.1%, -12.7%]
  - failed proposals of honest leaders: next 98.00 [87.00-106.00] / broadcast 67.00 [62.00-74.00], p=0.008, broadcast -31.6% [-37.4%, -21.8%]
  - honest leaders excluded: next 11.00 [10.00-14.00] / broadcast 6.00 [3.00-8.00], p=0.008, broadcast -45.5% [-72.7%, -27.3%]
  - honest cut, %: next 3.55 [3.23-4.52] / broadcast 1.94 [0.97-2.58], p=0.008, broadcast -45.4% [-72.7%, -27.3%]
- trust2 (5 v 5 runs)
  - timeouts: next 140 [137-143] / broadcast 140 [138-143], p=1.000, broadcast +0.0% [-2.1%, +2.9%]
  - rounds_per_s: next 1.4 / broadcast 1.3 [1.2-1.4], p=0.167, broadcast -7.1% [-14.3%, +0.0%]
  - e2e_latency_ms: next 4732 [4313-6152] / broadcast 4329 [2837-4653], p=0.095, broadcast -8.5% [-45.2%, +0.4%]
  - AT against honest leaders: next 3.00 [2.00-7.00] / broadcast 39.00 [31.00-41.00], p=0.008, broadcast +1200.0% [+457.1%, +1950.0%]
  - honest leaders excluded: next 0.00 / broadcast 1.00 [0.00-3.00], p=0.048
  - honest cut, %: next 0.00 / broadcast 0.32 [0.00-0.97], p=0.048

- pooled over the rules of framers+late (broadcast against next leader; bootstrap 95%, permutation test within a rule):
  - timeouts: -0.2% [-2.6%, +0.7%], p=0.8251
  - rounds_per_s: -6.9% [-12.0%, -1.5%], p=0.0072
  - e2e_latency_ms: -25.1% [-41.5%, -14.1%], p=0.0152


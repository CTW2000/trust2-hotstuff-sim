# Unresponsive weight that builds up (dirTtruMargin, 10 seeds, n = 31, equal base weights)

Median [min, max] over the seeds. `commit`: share of the views of the phase whose block commits. `share of the down replicas`: their largest share on the epoch tables of the phase (a quorum of the others needs it below 0.333). `epochs without a quorum`: epochs of the phase in which it is not, summed over the seeds. `margin`: the smallest (1 + 2 D_N - D_O)/3 - u over the epochs of the phase.

| views | down | u | B_rep | commit | share of the down replicas | epochs without a quorum | margin | honest convictions |
|---|---|---|---|---|---|---|---|---|
| 1-1999 | 9 | 0.290 | 0.10 | 0.927 [0.925, 0.930] | 0.290 [0.290, 0.290] | 0 of 800 | 0.043 [0.043, 0.043] | 0 |
| 1-1999 | 9 | 0.290 | 0.00 | 0.924 [0.919, 0.928] | 0.290 [0.290, 0.290] | 0 of 800 | 0.043 [0.043, 0.043] | 0 |
| 2000-3999 | 10 | 0.323 | 0.10 | 0.933 [0.927, 0.936] | 0.267 [0.264, 0.269] | 0 of 800 | 0.061 [0.060, 0.064] | 0 |
| 2000-3999 | 10 | 0.323 | 0.00 | 0.928 [0.923, 0.934] | 0.323 [0.323, 0.323] | 0 of 800 | 0.011 [0.011, 0.011] | 0 |
| 4000-6999 | 11 | 0.355 | 0.10 | 0.927 [0.925, 0.931] | 0.288 [0.287, 0.292] | 0 of 1200 | 0.041 [0.038, 0.042] | 0 |
| 4000-6999 | 11 | 0.355 | 0.00 | 0.000 [0.000, 0.000] | 0.355 [0.355, 0.355] | 1200 of 1200 | -0.022 [-0.022, -0.022] | 0 |
| 7000-8999 | 12 | 0.387 | 0.10 | 0.915 [0.909, 0.919] | 0.319 [0.319, 0.319] | 0 of 800 | 0.013 [0.013, 0.013] | 0 |
| 7000-8999 | 12 | 0.387 | 0.00 | 0.000 [0.000, 0.000] | 0.387 [0.387, 0.387] | 800 of 800 | -0.054 [-0.054, -0.054] | 0 |
| 9000-10489 | 13 | 0.419 | 0.10 | 0.000 [0.000, 0.000] | 0.355 [0.355, 0.355] | 600 of 600 | -0.019 [-0.019, -0.019] | 0 |
| 9000-10489 | 13 | 0.419 | 0.00 | 0.000 [0.000, 0.000] | 0.419 [0.419, 0.419] | 600 of 600 | -0.086 [-0.086, -0.086] | 0 |

The tables of the simulator follow the facts of all views, committed or not; the protocol changes tables only through commits. A phase of the B_rep = 0.10 arm that has epochs without a quorum is therefore one the protocol would not get through: read its commit share as an upper bound.

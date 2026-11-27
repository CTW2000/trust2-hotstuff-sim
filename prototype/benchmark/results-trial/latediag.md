# Where a batch waits under late messages, by the position of its block in the epoch

## e25: 9 runs, 672423 batches (900329 inclusions in blocks), 9866 blocks (0 without a batch), 411 epochs entered

Per batch: wait before its block 344 ms (median 135), block to commit 339 ms (median 259); per run, mean wait 305, 341, 354, 312, 309, 475, 311, 319, 372

Handovers: 411; pause without a batch in any block: median 253 ms, mean 379 ms, longer than 1 s in 14 (rounds from the last block with a payload to the first: median 2, max 7). The first block with a payload of an epoch holds 8.6% of the batches and 18.9% of the total wait; elsewhere a batch waits 306 ms. What these batches wait beyond that, spread over all batches: 39 ms per batch, of which 44 ms from the 14 pauses longer than 1 s (1.09, 1.31, 2.71, 2.80, 3.62, 3.65, 3.71, 3.72, 3.72, 3.91, 4.06, 5.05, 5.09, 5.10 s).

| position | blocks to the next | mean time to the next block ms | rounds skipped after it | batches % | mean wait ms | share of the total wait % | mean block-to-commit ms |
|---|---|---|---|---|---|---|---|
| 0 | 400 | 181 | 0 | 6.3 | 227 | 4.1 | 322 |
| 1 | 411 | 164 | 1 | 6.5 | 949 | 18.1 | 390 |
| 2 | 410 | 161 | 0 | 4.0 | 295 | 3.4 | 316 |
| 3 | 411 | 159 | 0 | 3.8 | 300 | 3.3 | 348 |
| 4 | 409 | 176 | 0 | 4.3 | 404 | 5.0 | 306 |
| 5 | 410 | 153 | 0 | 3.8 | 270 | 3.0 | 328 |
| 6 | 410 | 158 | 0 | 3.7 | 250 | 2.7 | 331 |
| 7 | 409 | 165 | 0 | 4.2 | 482 | 5.9 | 312 |
| 8 | 409 | 150 | 0 | 4.0 | 287 | 3.3 | 362 |
| 9 | 409 | 155 | 0 | 3.7 | 283 | 3.0 | 318 |
| 10 | 409 | 146 | 0 | 3.7 | 234 | 2.5 | 352 |
| 11 | 409 | 167 | 0 | 3.6 | 281 | 3.0 | 341 |
| 12 | 410 | 158 | 0 | 4.0 | 307 | 3.6 | 358 |
| 13 | 411 | 175 | 0 | 3.8 | 265 | 2.9 | 319 |
| 14 | 411 | 166 | 0 | 3.8 | 264 | 2.9 | 344 |
| 15 | 415 | 179 | 0 | 4.3 | 396 | 4.9 | 323 |
| 16 | 415 | 154 | 0 | 4.3 | 304 | 3.8 | 344 |
| 17 | 415 | 161 | 0 | 3.8 | 222 | 2.4 | 311 |
| 18 | 415 | 158 | 0 | 4.0 | 284 | 3.3 | 319 |
| 19 | 415 | 172 | 6 | 3.9 | 260 | 2.9 | 317 |
| 20 | 412 | 157 | 0 | 4.0 | 302 | 3.5 | 360 |
| 21 | 411 | 172 | 9 | 3.7 | 236 | 2.6 | 336 |
| 22 | 402 | 158 | 0 | 3.9 | 358 | 4.1 | 370 |
| 23 | 401 | 405 | 423 | 3.8 | 282 | 3.1 | 361 |
| 24 | 18 | 447 | 16 | 1.2 | 749 | 2.6 | 419 |

## holder: 9 runs, 670404 batches (896294 inclusions in blocks), 10116 blocks (0 without a batch), 421 epochs entered

Per batch: wait before its block 283 ms (median 132), block to commit 334 ms (median 258); per run, mean wait 309, 304, 316, 260, 251, 262, 288, 270, 288

Handovers: 421; pause without a batch in any block: median 248 ms, mean 305 ms, longer than 1 s in 11 (rounds from the last block with a payload to the first: median 2, max 5). The first block with a payload of an epoch holds 7.5% of the batches and 8.6% of the total wait; elsewhere a batch waits 280 ms. What these batches wait beyond that, spread over all batches: 3 ms per batch, of which 8 ms from the 11 pauses longer than 1 s (1.59, 1.60, 1.61, 1.61, 1.64, 1.65, 1.69, 1.71, 1.74, 1.76, 2.81 s).

| position | blocks to the next | mean time to the next block ms | rounds skipped after it | batches % | mean wait ms | share of the total wait % | mean block-to-commit ms |
|---|---|---|---|---|---|---|---|
| 0 | 420 | 171 | 0 | 7.4 | 299 | 7.8 | 334 |
| 1 | 421 | 172 | 0 | 4.3 | 314 | 4.8 | 318 |
| 2 | 421 | 163 | 1 | 4.4 | 339 | 5.2 | 333 |
| 3 | 419 | 169 | 1 | 3.9 | 266 | 3.6 | 308 |
| 4 | 418 | 162 | 0 | 4.0 | 257 | 3.7 | 390 |
| 5 | 419 | 164 | 0 | 3.9 | 257 | 3.5 | 315 |
| 6 | 421 | 169 | 0 | 4.0 | 304 | 4.3 | 354 |
| 7 | 421 | 167 | 0 | 4.3 | 304 | 4.6 | 323 |
| 8 | 421 | 160 | 0 | 3.9 | 243 | 3.4 | 337 |
| 9 | 422 | 160 | 0 | 4.2 | 315 | 4.6 | 345 |
| 10 | 422 | 167 | 0 | 4.0 | 253 | 3.5 | 327 |
| 11 | 421 | 159 | 0 | 4.1 | 278 | 4.0 | 341 |
| 12 | 421 | 163 | 0 | 3.9 | 265 | 3.6 | 313 |
| 13 | 421 | 152 | 0 | 4.1 | 261 | 3.8 | 344 |
| 14 | 420 | 152 | 0 | 3.8 | 269 | 3.6 | 321 |
| 15 | 422 | 158 | 0 | 3.7 | 240 | 3.2 | 323 |
| 16 | 423 | 158 | 0 | 4.1 | 337 | 4.8 | 323 |
| 17 | 423 | 145 | 0 | 3.8 | 239 | 3.2 | 328 |
| 18 | 423 | 167 | 0 | 3.6 | 204 | 2.6 | 304 |
| 19 | 423 | 162 | 0 | 4.1 | 315 | 4.6 | 320 |
| 20 | 423 | 155 | 0 | 4.0 | 265 | 3.7 | 330 |
| 21 | 422 | 163 | 13 | 3.9 | 252 | 3.5 | 362 |
| 22 | 413 | 162 | 2 | 3.8 | 268 | 3.6 | 332 |
| 23 | 410 | 325 | 414 | 3.6 | 236 | 3.0 | 352 |
| 24 | 17 | 421 | 17 | 1.3 | 803 | 3.7 | 422 |

## Summary

| arm | wait before the block ms | block to commit ms | sum ms |
|---|---|---|---|
| e25 | 344 | 339 | 683 |
| holder | 283 | 334 | 617 |

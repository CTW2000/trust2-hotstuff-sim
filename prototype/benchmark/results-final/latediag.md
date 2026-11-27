# Where a batch waits under late messages, by the position of its block in the epoch

## baseline: 10 runs, 391867 batches (585161 inclusions in blocks), 6423 blocks (0 without a batch), 0 epochs entered

Per batch: wait before its block 259 ms (median 125), block to commit 299 ms (median 253); per run, mean wait 307, 197, 237, 236, 286, 244, 243, 338, 273, 234

| position | blocks to the next | mean time to the next block ms | rounds skipped after it | batches % | mean wait ms | share of the total wait % | mean block-to-commit ms |
|---|---|---|---|---|---|---|---|
| 0 | 258 | 151 | 0 | 4.3 | 297 | 5.0 | 312 |
| 1 | 258 | 159 | 0 | 4.0 | 257 | 3.9 | 287 |
| 2 | 257 | 158 | 0 | 3.9 | 216 | 3.3 | 271 |
| 3 | 257 | 140 | 0 | 4.1 | 247 | 3.9 | 299 |
| 4 | 255 | 165 | 0 | 3.7 | 349 | 5.0 | 290 |
| 5 | 255 | 160 | 0 | 4.1 | 268 | 4.3 | 280 |
| 6 | 255 | 150 | 0 | 4.1 | 264 | 4.2 | 294 |
| 7 | 255 | 163 | 0 | 4.0 | 294 | 4.6 | 278 |
| 8 | 257 | 145 | 0 | 4.2 | 244 | 3.9 | 293 |
| 9 | 257 | 166 | 0 | 3.8 | 297 | 4.4 | 283 |
| 10 | 254 | 141 | 0 | 4.2 | 263 | 4.3 | 314 |
| 11 | 255 | 174 | 0 | 3.5 | 183 | 2.5 | 310 |
| 12 | 255 | 170 | 0 | 4.4 | 332 | 5.6 | 339 |
| 13 | 255 | 146 | 0 | 4.4 | 277 | 4.7 | 369 |
| 14 | 254 | 164 | 0 | 3.7 | 231 | 3.3 | 291 |
| 15 | 254 | 159 | 0 | 4.3 | 279 | 4.6 | 321 |
| 16 | 258 | 157 | 0 | 4.0 | 245 | 3.8 | 277 |
| 17 | 258 | 149 | 0 | 4.0 | 245 | 3.8 | 306 |
| 18 | 258 | 170 | 0 | 3.9 | 249 | 3.7 | 316 |
| 19 | 258 | 174 | 0 | 4.4 | 282 | 4.8 | 308 |
| 20 | 258 | 145 | 0 | 4.4 | 260 | 4.4 | 281 |
| 21 | 258 | 141 | 0 | 3.9 | 274 | 4.1 | 266 |
| 22 | 258 | 130 | 0 | 3.6 | 182 | 2.6 | 279 |
| 23 | 258 | 145 | 0 | 3.4 | 187 | 2.5 | 322 |
| 24 | 258 | 164 | 0 | 3.7 | 224 | 3.2 | 285 |

## e25: 10 runs, 391170 batches (515817 inclusions in blocks), 5767 blocks (0 without a batch), 240 epochs entered

Per batch: wait before its block 350 ms (median 135), block to commit 333 ms (median 259); per run, mean wait 300, 314, 334, 385, 422, 266, 412, 563, 257, 250

Handovers: 240; pause without a batch in any block: median 255 ms, mean 424 ms, longer than 1 s in 11 (rounds from the last block with a payload to the first: median 2.0, max 8). The first block with a payload of an epoch holds 9.8% of the batches and 25.8% of the total wait; elsewhere a batch waits 288 ms. What these batches wait beyond that, spread over all batches: 62 ms per batch, of which 66 ms from the 11 pauses longer than 1 s.

| position | blocks to the next | mean time to the next block ms | rounds skipped after it | batches % | mean wait ms | share of the total wait % | mean block-to-commit ms |
|---|---|---|---|---|---|---|---|
| 0 | 231 | 151 | 0 | 6.2 | 222 | 3.9 | 292 |
| 1 | 240 | 154 | 0 | 7.5 | 1204 | 25.9 | 365 |
| 2 | 240 | 152 | 0 | 3.8 | 264 | 2.8 | 326 |
| 3 | 239 | 183 | 0 | 3.6 | 256 | 2.7 | 348 |
| 4 | 239 | 153 | 0 | 4.4 | 298 | 3.7 | 305 |
| 5 | 239 | 143 | 0 | 3.9 | 340 | 3.8 | 289 |
| 6 | 239 | 146 | 0 | 3.4 | 177 | 1.7 | 303 |
| 7 | 240 | 158 | 0 | 3.5 | 210 | 2.1 | 327 |
| 8 | 240 | 184 | 0 | 3.7 | 272 | 2.9 | 343 |
| 9 | 238 | 157 | 0 | 4.1 | 349 | 4.1 | 314 |
| 10 | 238 | 155 | 0 | 4.2 | 315 | 3.8 | 401 |
| 11 | 238 | 174 | 0 | 3.7 | 263 | 2.8 | 354 |
| 12 | 238 | 177 | 0 | 3.8 | 278 | 3.1 | 303 |
| 13 | 238 | 159 | 0 | 4.4 | 355 | 4.5 | 345 |
| 14 | 242 | 175 | 0 | 3.3 | 198 | 1.9 | 329 |
| 15 | 243 | 143 | 0 | 4.6 | 339 | 4.4 | 340 |
| 16 | 244 | 146 | 0 | 3.5 | 181 | 1.8 | 313 |
| 17 | 244 | 171 | 0 | 3.5 | 217 | 2.2 | 309 |
| 18 | 244 | 171 | 1 | 4.4 | 361 | 4.5 | 362 |
| 19 | 242 | 150 | 0 | 3.9 | 248 | 2.8 | 321 |
| 20 | 241 | 162 | 0 | 3.6 | 242 | 2.5 | 296 |
| 21 | 240 | 157 | 7 | 3.8 | 307 | 3.3 | 306 |
| 22 | 233 | 156 | 0 | 3.7 | 272 | 2.9 | 372 |
| 23 | 232 | 457 | 246 | 3.6 | 244 | 2.5 | 355 |
| 24 | 15 | 652 | 17 | 1.7 | 691 | 3.4 | 465 |

## e0: 10 runs, 391651 batches (533657 inclusions in blocks), 6294 blocks (0 without a batch), 0 epochs entered

Per batch: wait before its block 258 ms (median 127), block to commit 328 ms (median 258); per run, mean wait 221, 277, 245, 230, 262, 254, 305, 252, 277, 260

| position | blocks to the next | mean time to the next block ms | rounds skipped after it | batches % | mean wait ms | share of the total wait % | mean block-to-commit ms |
|---|---|---|---|---|---|---|---|
| 0 | 252 | 174 | 0 | 4.1 | 268 | 4.3 | 302 |
| 1 | 252 | 152 | 0 | 4.3 | 261 | 4.4 | 336 |
| 2 | 252 | 151 | 0 | 4.0 | 269 | 4.1 | 306 |
| 3 | 252 | 166 | 0 | 3.6 | 207 | 2.9 | 327 |
| 4 | 252 | 178 | 0 | 4.3 | 327 | 5.4 | 338 |
| 5 | 252 | 144 | 0 | 4.4 | 302 | 5.2 | 330 |
| 6 | 251 | 162 | 0 | 3.7 | 217 | 3.1 | 307 |
| 7 | 251 | 152 | 0 | 4.1 | 282 | 4.4 | 361 |
| 8 | 252 | 165 | 0 | 3.8 | 236 | 3.5 | 308 |
| 9 | 252 | 151 | 0 | 4.1 | 257 | 4.1 | 332 |
| 10 | 251 | 172 | 0 | 3.8 | 227 | 3.3 | 338 |
| 11 | 249 | 147 | 0 | 4.3 | 297 | 5.0 | 366 |
| 12 | 248 | 165 | 0 | 3.6 | 197 | 2.7 | 301 |
| 13 | 248 | 160 | 0 | 4.2 | 276 | 4.4 | 344 |
| 14 | 248 | 140 | 0 | 4.1 | 353 | 5.7 | 304 |
| 15 | 250 | 158 | 0 | 3.6 | 226 | 3.2 | 316 |
| 16 | 249 | 166 | 0 | 3.8 | 224 | 3.3 | 293 |
| 17 | 252 | 143 | 0 | 4.2 | 266 | 4.4 | 342 |
| 18 | 253 | 185 | 0 | 3.4 | 190 | 2.5 | 350 |
| 19 | 253 | 165 | 0 | 4.7 | 317 | 5.7 | 388 |
| 20 | 253 | 174 | 0 | 4.2 | 291 | 4.7 | 308 |
| 21 | 253 | 138 | 0 | 4.5 | 258 | 4.5 | 328 |
| 22 | 253 | 156 | 0 | 3.4 | 149 | 2.0 | 284 |
| 23 | 253 | 143 | 0 | 4.0 | 283 | 4.4 | 306 |
| 24 | 253 | 163 | 0 | 3.6 | 197 | 2.7 | 369 |

## Summary

| arm | wait before the block ms | block to commit ms | sum ms |
|---|---|---|---|
| baseline | 259 | 299 | 559 |
| e25 | 350 | 333 | 683 |
| e0 | 258 | 328 | 587 |

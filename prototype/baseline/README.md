# Baseline: upstream plus the same fixes

The consensus and node crates of [asonnino/hotstuff](https://github.com/asonnino/hotstuff) at `dc01ac8` (as vendored
in the first commit of `prototype/`), with only the fixes the Trust 2.0 prototype also carries, so that the
experiments compare like with like (prototype/DESIGN.md §10, §11, §14.2):

1. a node missing a block asks a few signers of the QC that certifies it (`consensus/src/synchronizer.rs`);
2. blocks committed together are committed oldest first (`consensus/src/core.rs`, `commit`).

The crypto, store, network (including the synthetic link delays) and mempool crates are the prototype's.
Build with `cargo build --release --features benchmark` in `baseline/node`; run with
`python3 run_local.py --build baseline ...` from `prototype/benchmark`.

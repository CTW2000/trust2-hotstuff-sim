// Check for Trust 2.0 (prototype/DESIGN.md §15.42): the Aptos-style leader rule of the prototype against the leader
// reputation of aptos-core itself, on the ledger records of a prototype run. Put this file at
//     consensus/src/liveness/trust2_trace_check.rs
// add `#[cfg(test)] mod trust2_trace_check;` to consensus/src/liveness/mod.rs, and run
//     TRUST2_TRACE=/path/to/node-0.log cargo test -p aptos-consensus trust2_trace_check -- --nocapture
//
// The prototype logs, with `--leader-rule aptos`, one `AptosEvent` line per committed block (its round, its
// proposer, the failed proposers it records and the voters of its parent, all as member indices) and one
// `AptosWeights` line per weight table it derives (how many blocks had been recorded, and the weight it gave each
// member). This test rebuilds the same history as `NewBlockEvent`s, newest first and cut to the proposer window as
// the storage backend of aptos-core hands it over, runs `ProposerAndVoterHeuristic::get_weights` with the default
// parameters of aptos-core on it, and compares the weights member by member. What it checks is the classification
// of members into active, inactive and failed from a given history; when the weights are recomputed (every round
// in aptos-core, every epoch of 25 rounds in the prototype) is not part of the check.

use super::leader_reputation::{ProposerAndVoterHeuristic, ReputationHeuristic};
use aptos_bitvec::BitVec;
use aptos_consensus_types::common::Author;
use aptos_types::{account_address::AccountAddress, account_config::NewBlockEvent};
use std::collections::HashMap;

// ConsensusConfigV1::default() of aptos-core (ProposerAndVoterV2): weights and failure threshold in percent, and
// the windows as multiples of the number of validators. V2 takes its windows from the fresh end of the history.
const ACTIVE: u64 = 1000;
const INACTIVE: u64 = 10;
const FAILED: u64 = 1;
const FAILURE_THRESHOLD_PERCENT: u32 = 10;
const PROPOSER_WINDOW: usize = 10;
const VOTER_WINDOW: usize = 1;

struct Recorded {
    round: u64,
    proposer: i64,
    failed: Vec<u64>,
    voters: Vec<u64>,
}

fn indices(value: &serde_json::Value) -> Vec<u64> {
    value.as_array().unwrap().iter().map(|x| x.as_u64().unwrap()).collect()
}

#[test]
fn trust2_trace_check() {
    let path = match std::env::var("TRUST2_TRACE") {
        Ok(path) => path,
        Err(_) => {
            println!("[LeaderReputation] TRUST2_TRACE is not set: nothing to check");
            return;
        },
    };
    let text = std::fs::read_to_string(&path).unwrap();
    let mut recorded: Vec<Recorded> = Vec::new();
    let (mut tables, mut same, mut members, mut differing) = (0u64, 0u64, 0u64, 0u64);
    let mut by_weight: HashMap<u64, u64> = HashMap::new();

    for line in text.lines() {
        if let Some(at) = line.find("AptosEvent ") {
            let v: serde_json::Value = serde_json::from_str(&line[at + "AptosEvent ".len()..]).unwrap();
            recorded.push(Recorded {
                round: v["round"].as_u64().unwrap(),
                proposer: v["proposer"].as_i64().unwrap(),
                failed: indices(&v["failed"]),
                voters: indices(&v["voters"]),
            });
        } else if let Some(at) = line.find("AptosWeights ") {
            let v: serde_json::Value = serde_json::from_str(&line[at + "AptosWeights ".len()..]).unwrap();
            let n = v["members"].as_u64().unwrap() as usize;
            let events = v["events"].as_u64().unwrap() as usize;
            let expected = indices(&v["weights"]);
            assert_eq!(expected.len(), n);
            assert!(events <= recorded.len(), "the trace names blocks it does not hold");

            let validators: Vec<Author> = (0..n)
                .map(|i| AccountAddress::from_hex_literal(&format!("0x{:x}", i + 0x1000)).unwrap())
                .collect();
            let epoch_to_candidates = HashMap::from([(1u64, validators.clone())]);
            // Newest first, at most the proposer window: what the backend returns for the round of the election.
            let history: Vec<NewBlockEvent> = recorded[..events]
                .iter()
                .rev()
                .take(PROPOSER_WINDOW * n)
                .map(|block| {
                    let mut voters = BitVec::with_num_bits(n as u16);
                    for i in &block.voters {
                        voters.set(*i as u16);
                    }
                    let proposer = match block.proposer {
                        i if i >= 0 => validators[i as usize],
                        _ => AccountAddress::ZERO,
                    };
                    NewBlockEvent::new(
                        AccountAddress::ONE,
                        1,
                        block.round,
                        block.round,
                        voters.into(),
                        proposer,
                        block.failed.clone(),
                        0,
                    )
                })
                .collect();
            let heuristic = ProposerAndVoterHeuristic::new(
                validators[0],
                ACTIVE,
                INACTIVE,
                FAILED,
                FAILURE_THRESHOLD_PERCENT,
                VOTER_WINDOW * n,
                PROPOSER_WINDOW * n,
                false,
            );
            let weights = heuristic.get_weights(1, &epoch_to_candidates, &history);

            tables += 1;
            same += (weights == expected) as u64;
            members += n as u64;
            differing += weights.iter().zip(&expected).filter(|(a, b)| a != b).count() as u64;
            for w in &weights {
                *by_weight.entry(*w).or_default() += 1;
            }
        }
    }

    println!(
        "[LeaderReputation] {}: {} blocks, {} weight tables; aptos-core gives the same weights in {} tables; {} of {} member weights differ",
        path,
        recorded.len(),
        tables,
        same,
        differing,
        members
    );
    println!(
        "[LeaderReputation] member weights by aptos-core: active {}, inactive {}, failed {}",
        by_weight.get(&ACTIVE).copied().unwrap_or(0),
        by_weight.get(&INACTIVE).copied().unwrap_or(0),
        by_weight.get(&FAILED).copied().unwrap_or(0)
    );
    assert!(tables > 0, "the trace holds no weight table");
    assert_eq!(differing, 0, "the prototype's rule and aptos-core disagree on this history");
}

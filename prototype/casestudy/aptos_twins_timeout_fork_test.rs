// Case study for Trust 2.0 (prototype/DESIGN.md §15.37): a fork that goes through a timeout certificate, in the Twins
// test framework of aptos-core. Append this file to consensus/src/twins/basic_twins_test.rs of an aptos-core checkout
// and run
//     cargo test -p aptos-consensus twins_timeout_fork_test -- --ignored --nocapture
// Nothing here touches a deployed network: the framework runs every validator in one process on a mock network.

use aptos_consensus_types::common::Author;
use aptos_crypto::HashValue;
use aptos_types::validator_verifier::ValidatorVerifier;
use std::collections::HashSet;

#[test]
/// Two of four validators run twins, which is beyond the fault assumption (one of four): the question is not
/// whether the ledger forks, but what the records left behind allow one to prove afterwards.
///
/// Setup:
///
/// 4 nodes (n0, n1, n2, n3) and 2 twins (twin0, twin1), split for the whole run into
/// side one [n0, n1, n2] and side two [n3, twin0, twin1]. n2 leads rounds 1-3, n3 every later round.
///
/// Side one certifies the blocks of rounds 1 and 2 and commits the block of round 1.
/// Side two hears no proposal in rounds 1-3 and times out; its timeout certificate of round 3 reports the
/// genesis QC as the highest one. In round 4, n3 extends the genesis under that certificate, and side two
/// commits that block.
///
/// Checks:
///
/// 1. the two committed blocks conflict;
/// 2. in the QCs both sides stored, no validator voted for two blocks of one round;
/// 3. the timeout certificate of side two, which no block carries, names the validators that voted for the
///    block of round 2 on side one (it certifies round 1) and reported round 0 in a timeout of round 3.
#[ignore]
fn twins_timeout_fork_test() {
    let runtime = consensus_runtime();
    let mut playground = NetworkPlayground::new(runtime.handle().clone());
    let num_nodes = 4;
    let num_twins = 2;

    let mut round_proposers: HashMap<Round, usize> = HashMap::new();
    for round in 1..=3 {
        round_proposers.insert(round, 2);
    }
    for round in 4..60 {
        round_proposers.insert(round, 3);
    }

    let mut nodes = SMRNode::start_num_nodes_with_twins(
        num_nodes,
        num_twins,
        &mut playground,
        RoundProposer(HashMap::new()),
        Some(round_proposers),
    );
    assert_eq!(nodes[0].id.author, nodes[4].id.author);
    assert_eq!(nodes[1].id.author, nodes[5].id.author);
    let twin_authors: HashSet<Author> = [nodes[0].id.author, nodes[1].id.author].into_iter().collect();

    let side_one = vec![nodes[0].id, nodes[1].id, nodes[2].id];
    let side_two = vec![nodes[3].id, nodes[4].id, nodes[5].id];
    assert!(playground.split_network(side_one, side_two));
    runtime.spawn(playground.start());

    let (commit_one, commit_two) = timed_block_on(&runtime, async {
        let one = nodes[0].commit_cb_receiver.next().await;
        let two = nodes[3].commit_cb_receiver.next().await;
        (
            one.expect("no commit on side one"),
            two.expect("no commit on side two"),
        )
    });
    let committed_one = commit_one.ledger_info().commit_info().clone();
    let committed_two = commit_two.ledger_info().commit_info().clone();

    // 1. The two committed blocks conflict: the one of side two extends the genesis, not the block of round 1.
    assert_eq!(committed_one.round(), 1);
    assert_ne!(committed_one.id(), committed_two.id());
    let block_two = nodes[3]
        .storage
        .shared_storage
        .block
        .lock()
        .get(&committed_two.id())
        .cloned()
        .expect("side two stores the block it committed");
    assert_eq!(block_two.quorum_cert().certified_block().round(), 0);
    assert!(block_two.round() > committed_one.round());

    // 2. The votes in the QCs of both ledgers: nobody voted twice in a round.
    let verifier = ValidatorVerifier::from(nodes[0].storage.shared_storage.get_validator_set());
    let addresses = verifier.get_ordered_account_addresses();
    let votes_of = |node: &SMRNode| -> Vec<(Round, HashValue, Vec<Author>)> {
        node.storage
            .shared_storage
            .qc
            .lock()
            .values()
            .map(|qc| {
                (
                    qc.certified_block().round(),
                    qc.certified_block().id(),
                    qc.ledger_info().get_voters(&addresses),
                )
            })
            .collect()
    };
    let (votes_one, votes_two) = (votes_of(&nodes[0]), votes_of(&nodes[3]));
    let mut voted: HashMap<(Author, Round), HashSet<HashValue>> = HashMap::new();
    for (round, id, voters) in votes_one.iter().chain(votes_two.iter()) {
        for voter in voters {
            voted.entry((*voter, *round)).or_default().insert(*id);
        }
    }
    let double_votes = voted.values().filter(|blocks| blocks.len() > 1).count();
    assert_eq!(double_votes, 0, "a validator voted for two blocks of one round");

    // 3. With the timeout certificate side two entered round 4 on: who voted for the block of round 2 on side
    // one, which certifies round 1, and reported a highest QC below round 1 in a timeout of a later round.
    let x_plus_voters: HashSet<Author> = votes_one
        .iter()
        .filter(|(round, _, _)| *round == committed_one.round() + 1)
        .flat_map(|(_, _, voters)| voters.iter().cloned())
        .collect();
    assert!(!x_plus_voters.is_empty(), "side one stores the QC of round 2");
    let tc = nodes[3]
        .storage
        .shared_storage
        .highest_2chain_timeout_certificate
        .lock()
        .clone()
        .expect("side two keeps its highest timeout certificate");
    let reports = tc.signatures_with_rounds().get_voters_and_rounds(&addresses);
    let culprits: HashSet<Author> = reports
        .iter()
        .filter(|(author, hqc_round)| {
            *hqc_round < committed_one.round()
                && tc.round() >= committed_one.round() + 1
                && x_plus_voters.contains(author)
        })
        .map(|(author, _)| *author)
        .collect();
    assert_eq!(culprits, twin_authors);

    println!(
        "[TwinsTest] side one committed round {}, side two committed round {} (its block extends round {})",
        committed_one.round(),
        committed_two.round(),
        block_two.quorum_cert().certified_block().round()
    );
    println!(
        "[TwinsTest] QCs stored: {} on side one, {} on side two; validators with two votes in one round: {}",
        votes_one.len(),
        votes_two.len(),
        double_votes
    );
    println!(
        "[TwinsTest] timeout certificate of round {} (highest QC round {}): {} signers, {} of them voted for round {} on side one -> {} of {} validators",
        tc.round(),
        tc.highest_hqc_round(),
        reports.len(),
        culprits.len(),
        committed_one.round() + 1,
        culprits.len(),
        addresses.len()
    );
}

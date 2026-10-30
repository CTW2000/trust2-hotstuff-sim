use super::*;
use crate::common::{chain, committee, committee_with_base_port, keys, listener, EPOCH};
use crate::leader::LeaderElector;
use crypto::SecretKey;
use futures::future::try_join_all;
use std::fs;
use std::time::Duration;
use tokio::sync::mpsc::channel;

fn core(
    name: PublicKey,
    secret: SecretKey,
    committee: Committee,
    store_path: &str,
) -> (
    Sender<ConsensusMessage>,
    Receiver<ProposerMessage>,
    Receiver<Block>,
) {
    let (tx_core, rx_core) = channel(1);
    let (tx_loopback, rx_loopback) = channel(1);
    let (tx_proposer, rx_proposer) = channel(1);
    let (tx_mempool, mut rx_mempool) = channel(1);
    let (tx_commit, rx_commit) = channel(1);

    let signature_service = SignatureService::new(secret);
    let _ = fs::remove_dir_all(store_path);
    let store = Store::new(store_path).unwrap();
    let mempool_driver = MempoolDriver::new(store.clone(), tx_mempool, tx_loopback.clone());
    let synchronizer = Synchronizer::new(
        name,
        committee.clone(),
        store.clone(),
        tx_loopback,
        /* sync_retry_delay */ 100_000,
    );

    tokio::spawn(async move {
        loop {
            rx_mempool.recv().await;
        }
    });

    let epoch_config = EpochConfig {
        length: 100,
        entity_cap_ppm: 1_000_000,
        class_cap_ppm: 1_000_000,
        l_max_ppm: 100_000,
        governance_malicious: false,
    };
    Core::spawn(
        name,
        committee,
        epoch_config,
        Inclusion::new(Duration::from_millis(500), false),
        Faults::default(),
        signature_service,
        store,
        mempool_driver,
        synchronizer,
        /* timeout_delay */ 100,
        /* rx_message */ rx_core,
        rx_loopback,
        tx_proposer,
        tx_commit,
    );

    (tx_core, rx_proposer, rx_commit)
}

fn leader_keys(round: Round) -> (PublicKey, SecretKey) {
    let leader_elector = LeaderElector::new(committee());
    let leader = leader_elector.get_leader(round);
    keys()
        .into_iter()
        .find(|(public_key, _)| *public_key == leader)
        .unwrap()
}

#[tokio::test]
async fn handle_proposal() {
    let committee = committee_with_base_port(16_000);

    // Make a block and the vote we expect to receive.
    let block = chain(vec![leader_keys(1)]).pop().unwrap();
    let (public_key, secret_key) = keys().pop().unwrap();
    let vote = Vote::new_from_key(block.digest(), block.round, public_key, &secret_key);
    let expected = bincode::serialize(&ConsensusMessage::Vote(vote)).unwrap();

    // Run a core instance.
    let store_path = ".db_test_handle_proposal";
    let (tx_core, _rx_proposer, _rx_commit) =
        core(public_key, secret_key, committee.clone(), store_path);

    // Send a block to the core.
    let message = ConsensusMessage::Propose(block.clone());
    tx_core.send(message).await.unwrap();

    // Ensure the next leaders gets the vote.
    let (next_leader, _) = leader_keys(2);
    let address = committee.address(&next_leader).unwrap();
    let handle = listener(address, Some(Bytes::from(expected)));
    assert!(handle.await.is_ok());
}

#[tokio::test]
async fn generate_proposal() {
    // Get the keys of the leaders of this round and the next.
    let (leader, leader_key) = leader_keys(1);
    let (next_leader, next_leader_key) = leader_keys(2);

    // Make a block, votes, and QC.
    let block = Block::new_from_key(QC::genesis(), leader, 1, Vec::new(), &leader_key);
    let hash = block.digest();
    let votes: Vec<_> = keys()
        .iter()
        .map(|(public_key, secret_key)| {
            Vote::new_from_key(hash.clone(), block.round, *public_key, &secret_key)
        })
        .collect();
    let hight_qc = QC {
        hash,
        round: block.round,
        epoch: EPOCH,
        votes: votes
            .iter()
            .cloned()
            .map(|x| (x.author, x.signature))
            .collect(),
    };

    // Run a core instance.
    let store_path = ".db_test_generate_proposal";
    let (tx_core, mut rx_proposer, _rx_commit) =
        core(next_leader, next_leader_key, committee(), store_path);

    // Send all votes to the core.
    for vote in votes.clone() {
        let message = ConsensusMessage::Vote(vote);
        tx_core.send(message).await.unwrap();
    }

    // Ensure the core sends a new block.
    match rx_proposer.recv().await.unwrap() {
        ProposerMessage::Make { round, qc, tc, .. } => {
            assert_eq!(round, 2);
            assert_eq!(qc, hight_qc);
            assert!(tc.is_none());
        }
        _ => panic!("Unexpected protocol message"),
    }
}

#[tokio::test]
async fn commit_block() {
    // Get enough distinct leaders to form a quorum.
    let leaders = vec![leader_keys(1), leader_keys(2), leader_keys(3)];
    let chain = chain(leaders);

    // Run a core instance.
    let store_path = ".db_test_commit_block";
    let (public_key, secret_key) = keys().pop().unwrap();
    let (tx_core, mut rx_proposer, mut rx_commit) =
        core(public_key, secret_key, committee(), store_path);

    // Send a the blocks to the core.
    let committed = chain[0].clone();
    for block in chain {
        let message = ConsensusMessage::Propose(block);
        tx_core.send(message).await.unwrap();

        let _ = rx_proposer.recv().await.unwrap();
    }

    // Ensure the core commits the head.
    match rx_commit.recv().await {
        Some(b) => assert_eq!(b, committed),
        _ => assert!(false),
    }
}

#[tokio::test]
async fn local_timeout_round() {
    let committee = committee_with_base_port(16_100);

    // Make the timeout vote we expect to send.
    let (public_key, secret_key) = leader_keys(3);
    // The node never received a proposal for round 1, so it reports NR (N6).
    let timeout = Timeout::new_from_key(QC::genesis(), 1, true, public_key, &secret_key);
    let expected = bincode::serialize(&ConsensusMessage::Timeout(timeout)).unwrap();

    // Run a core instance.
    let store_path = ".db_test_local_timeout_round";
    let (_tx_core, _rx_proposer, _rx_commit) =
        core(public_key, secret_key, committee.clone(), store_path);

    // Ensure the node broadcasts a timeout vote.
    let handles: Vec<_> = committee
        .broadcast_addresses(&public_key)
        .into_iter()
        .map(|(_, address)| listener(address, Some(Bytes::from(expected.clone()))))
        .collect();
    assert!(try_join_all(handles).await.is_ok());
}

#[tokio::test]
async fn far_future_block_does_not_turn_off_nr() {
    // 3.6 / N6: a valid block of a far-future round (from that round's leader) must not raise ready_round, so a
    // timeout of the current round still reports NR = 1 (no usable proposal for this round was received). Were
    // ready_round raised by any block, a faulty leader could keep every node's NR at 0 and disable AT.
    let committee = committee_with_base_port(16_300);
    let (public_key, secret_key) = leader_keys(3);
    let timeout = Timeout::new_from_key(QC::genesis(), 1, true, public_key, &secret_key);
    let expected = bincode::serialize(&ConsensusMessage::Timeout(timeout)).unwrap();

    let store_path = ".db_test_far_future_block_does_not_turn_off_nr";
    let (tx_core, mut rx_proposer, _rx_commit) = core(public_key, secret_key, committee.clone(), store_path);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });

    // A valid block for a much later round, from that round's leader, while we are still in round 1.
    let (future_leader, future_key) = leader_keys(10);
    let block = Block::new_from_key(QC::genesis(), future_leader, 10, Vec::new(), &future_key);
    tx_core.send(ConsensusMessage::Propose(block)).await.unwrap();

    let handles: Vec<_> = committee
        .broadcast_addresses(&public_key)
        .into_iter()
        .map(|(_, address)| listener(address, Some(Bytes::from(expected.clone()))))
        .collect();
    assert!(try_join_all(handles).await.is_ok());
}

#[test]
fn periodic_cleanup_is_due_once_per_detection_window() {
    // The round-based cleanup runs about once per DETECT_WINDOW rounds -- not on every advance -- and cleans to
    // the start of the detection window, so the detection / accusation / inclusion state cannot grow with the
    // round number between epoch handovers (and in a single-epoch run, where there is none).
    assert_eq!(periodic_cleanup_floor(1, 0), None);
    assert_eq!(periodic_cleanup_floor(DETECT_WINDOW, 0), Some(0));
    assert_eq!(periodic_cleanup_floor(DETECT_WINDOW + 1, DETECT_WINDOW), None);
    assert_eq!(periodic_cleanup_floor(2 * DETECT_WINDOW, DETECT_WINDOW), Some(DETECT_WINDOW));
}

#[tokio::test]
async fn far_future_round_messages_are_dropped() {
    // 1.13: a current-epoch consensus message for a round implausibly far beyond ours is dropped before it
    // reaches the per-round aggregator / accuser / detector / inclusion maps, so a faulty member cannot grow
    // memory without bound by signing votes or timeouts for arbitrary future rounds. A full quorum of NR = 1
    // timeouts for such a round therefore yields no accusation -- contrast nr_timeouts_make_an_accusation,
    // where the same quorum at the current round does produce one.
    let (leader1, leader2) = (leader_keys(1).0, leader_keys(2).0);
    let (name, secret) = keys()
        .into_iter()
        .find(|(k, _)| *k != leader1 && *k != leader2)
        .unwrap();
    let store_path = ".db_test_far_future_round_messages_are_dropped";
    let (tx_core, mut rx_proposer, _rx_commit) = core(name, secret, committee(), store_path);

    let far = 1 + ACCEPT_WINDOW + 1; // just past the acceptance window ahead of the starting round (1)
    for (key, secret) in keys().iter().filter(|(k, _)| *k != name) {
        let timeout = Timeout::new_from_key(QC::genesis(), far, true, *key, secret);
        tx_core.send(ConsensusMessage::Timeout(timeout)).await.unwrap();
    }

    // Nothing should reach the proposer: the far-future timeouts are dropped, so no accusation forms.
    let got = tokio::time::timeout(Duration::from_millis(300), rx_proposer.recv()).await;
    assert!(got.is_err(), "a far-future round must not produce a proposer message");
}

#[tokio::test]
async fn node_far_behind_catches_up_from_a_tc() {
    // N2: a TC needs 2f+1 signatures, so a faulty member cannot forge one, and the acceptance window never drops
    // it. A node still at round 1 that receives a valid TC of a round far beyond the window moves past it -- here
    // it leads the next round, so it proposes. Were the TC dropped, a node that fell behind would stay stuck.
    // The TC is of round target - 1, which must lie past the window ahead of round 1 (beyond 1 + ACCEPT_WINDOW).
    let round1_leader = leader_keys(1).0;
    let target = (3 + ACCEPT_WINDOW..).find(|r| leader_keys(*r).0 != round1_leader).unwrap();
    let (name, secret) = leader_keys(target);
    let store_path = ".db_test_node_far_behind_catches_up_from_a_tc";
    let (tx_core, mut rx_proposer, _rx_commit) = core(name, secret, committee(), store_path);

    let mut aggregator = Aggregator::new();
    let tc = keys()
        .into_iter()
        .find_map(|(key, secret)| {
            let timeout = Timeout::new_from_key(QC::genesis(), target - 1, false, key, &secret);
            aggregator.add_timeout(timeout, &committee()).unwrap()
        })
        .unwrap();
    tx_core.send(ConsensusMessage::TC(tc)).await.unwrap();

    match tokio::time::timeout(Duration::from_secs(2), rx_proposer.recv()).await {
        Ok(Some(ProposerMessage::Make { round, .. })) => assert_eq!(round, target),
        other => panic!("the node did not catch up from the TC: {:?}", other),
    }
}

#[tokio::test]
async fn node_far_behind_catches_up_from_a_carried_qc() {
    // N2: a message far beyond the window is dropped only after the certificate it carries is processed. A valid
    // timeout of a far round carries its signer's high QC; the node catches up from that QC first, so its own next
    // timeout is for the round after the QC, with that QC as high QC -- not for round 1, where it would be stuck.
    let committee = committee_with_base_port(16_500);
    let far = 2 + ACCEPT_WINDOW;
    let hash = Digest([9; 32]);
    let qc = QC {
        hash: hash.clone(),
        round: far - 1,
        epoch: EPOCH,
        votes: keys()
            .iter()
            .map(|(key, secret)| {
                let vote = Vote::new_from_key(hash.clone(), far - 1, *key, secret);
                (vote.author, vote.signature)
            })
            .collect(),
    };
    let mut members = keys();
    let (sender, sender_secret) = members.remove(0);
    let (public_key, secret_key) = members.remove(0);
    let theirs = Timeout::new_from_key(qc.clone(), far, false, sender, &sender_secret);
    // We hold no proposal for round `far`, so our own timeout reports NR = 1.
    let ours = Timeout::new_from_key(qc, far, true, public_key, &secret_key);
    let expected = bincode::serialize(&ConsensusMessage::Timeout(ours)).unwrap();

    let store_path = ".db_test_node_far_behind_catches_up_from_a_carried_qc";
    let (tx_core, mut rx_proposer, _rx_commit) = core(public_key, secret_key, committee.clone(), store_path);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    tx_core.send(ConsensusMessage::Timeout(theirs)).await.unwrap();

    let handles: Vec<_> = committee
        .broadcast_addresses(&public_key)
        .into_iter()
        .map(|(_, address)| listener(address, Some(Bytes::from(expected.clone()))))
        .collect();
    assert!(try_join_all(handles).await.is_ok());
}

#[tokio::test]
async fn nr_timeouts_make_an_accusation() {
    // G2: NR = 1 timeouts of a round from more than 2/3 of the weight go to the proposer as an AT accusation.
    let (leader1, leader2) = (leader_keys(1).0, leader_keys(2).0);
    let (name, secret) = keys()
        .into_iter()
        .find(|(k, _)| *k != leader1 && *k != leader2)
        .unwrap();
    let store_path = ".db_test_nr_timeouts_make_an_accusation";
    let (tx_core, mut rx_proposer, _rx_commit) = core(name, secret, committee(), store_path);
    for (key, secret) in keys().iter().filter(|(k, _)| *k != name) {
        let timeout = Timeout::new_from_key(QC::genesis(), 1, true, *key, secret);
        tx_core.send(ConsensusMessage::Timeout(timeout)).await.unwrap();
    }
    match rx_proposer.recv().await.unwrap() {
        ProposerMessage::Accuse(accusation) => {
            assert_eq!((accusation.epoch, accusation.round, accusation.votes.len()), (EPOCH, 1, 3));
            assert!(accusation.verify(&committee()).is_ok());
        }
        message => panic!("Unexpected message {:?}", message),
    }
}

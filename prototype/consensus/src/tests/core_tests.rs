use super::*;
use crate::common::{chain, committee, committee_with_base_port, keys, listener, signed_otx, table_at, EPOCH};
use crate::leader::LeaderElector;
use crypto::{SecretKey, Signature};
use futures::future::try_join_all;
use futures::stream::StreamExt as _;
use std::fs;
use std::net::SocketAddr;
use std::time::Duration;
use tokio::net::TcpListener;
use tokio::sync::mpsc::channel;
use tokio::time::{sleep, timeout};
use tokio_util::codec::{Framed, LengthDelimitedCodec};

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
    core_with_epochs(name, secret, committee, store_path, 100)
}

fn core_with_epochs(
    name: PublicKey,
    secret: SecretKey,
    committee: Committee,
    store_path: &str,
    length: Round,
) -> (
    Sender<ConsensusMessage>,
    Receiver<ProposerMessage>,
    Receiver<Block>,
) {
    let _ = fs::remove_dir_all(store_path);
    core_on(name, secret, committee, Store::new(store_path).unwrap(), length)
}

fn core_on(
    name: PublicKey,
    secret: SecretKey,
    committee: Committee,
    store: Store,
    length: Round,
) -> (
    Sender<ConsensusMessage>,
    Receiver<ProposerMessage>,
    Receiver<Block>,
) {
    core_on_with(name, secret, committee, store, length, Faults::default())
}

fn core_on_with(
    name: PublicKey,
    secret: SecretKey,
    committee: Committee,
    store: Store,
    length: Round,
    faults: Faults,
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
        length,
        reference_length: 0,
        entity_cap_ppm: 1_000_000,
        class_cap_ppm: 1_000_000,
        l_max_ppm: 100_000,
        governance_malicious: false,
        leader_rule: Default::default(),
        g2_threshold: 0,
        g2_no_reputation: false,
        aptos_failure_percent: 0,
    };
    Core::spawn(
        name,
        committee,
        epoch_config,
        Inclusion::new(Duration::from_millis(500), false),
        faults,
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

/// A listener that hands over the first `n` frames as they arrive, for checks that look at more than one frame or
/// must act between two of them.
fn frames(address: SocketAddr, n: usize) -> Receiver<Bytes> {
    let (tx, rx) = channel(n);
    tokio::spawn(async move {
        let listener = TcpListener::bind(&address).await.unwrap();
        let (socket, _) = listener.accept().await.unwrap();
        let mut transport = Framed::new(socket, LengthDelimitedCodec::new());
        for _ in 0..n {
            match transport.next().await {
                Some(Ok(frame)) => tx.send(frame.freeze()).await.unwrap(),
                _ => return,
            }
        }
    });
    rx
}

/// A listener that hands over the frames of every connection to it: the core and its synchronizer connect apart.
fn all_frames(address: SocketAddr) -> Receiver<Bytes> {
    let (tx, rx) = channel(1_000);
    tokio::spawn(async move {
        let listener = TcpListener::bind(&address).await.unwrap();
        while let Ok((socket, _)) = listener.accept().await {
            let tx = tx.clone();
            tokio::spawn(async move {
                let mut transport = Framed::new(socket, LengthDelimitedCodec::new());
                while let Some(Ok(frame)) = transport.next().await {
                    if tx.send(frame.freeze()).await.is_err() {
                        return;
                    }
                }
            });
        }
    });
    rx
}

/// A QC for `block` signed by every member.
fn qc_for(block: &Block) -> QC {
    QC {
        hash: block.digest(),
        round: block.round,
        epoch: EPOCH,
        votes: signed_by(&keys(), block.digest(), block.round),
    }
}

/// The votes of `signers` for `hash` at `round`, as a QC holds them.
fn signed_by(signers: &[(PublicKey, SecretKey)], hash: Digest, round: Round) -> Vec<(PublicKey, Signature)> {
    signers
        .iter()
        .map(|(key, secret)| {
            let vote = Vote::new_from_key(hash.clone(), round, *key, secret);
            (vote.author, vote.signature)
        })
        .collect()
}

/// The TC of `round` the members make, each reporting `high_qc` and NR = 0.
fn tc_of(round: Round, high_qc: &QC, committee: &Committee) -> TC {
    let mut aggregator = Aggregator::new();
    keys()
        .into_iter()
        .find_map(|(key, secret)| {
            let timeout = Timeout::new_from_key(high_qc.clone(), round, false, key, &secret);
            aggregator.add_timeout(timeout, committee).unwrap()
        })
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
async fn honest_vote_then_timeout_reports_nr_0() {
    // 5.4 / N6: a node that received the round's proposal (and voted for it) reports NR = 0 when it later times out
    // in that round. With NR = 1, the nodes that receive both its vote and its timeout would hold an NR
    // contradiction against an honest node.
    let committee = committee_with_base_port(16_600);
    let block = chain(vec![leader_keys(1)]).pop().unwrap();
    let (l1, l2) = (leader_keys(1).0, leader_keys(2).0);
    let (name, secret) = keys().into_iter().find(|(k, _)| *k != l1 && *k != l2).unwrap();
    let timeout = Timeout::new_from_key(QC::genesis(), 1, false, name, &secret);
    let expected = bincode::serialize(&ConsensusMessage::Timeout(timeout)).unwrap();

    let store_path = ".db_test_honest_vote_then_timeout_reports_nr_0";
    let (tx_core, mut rx_proposer, _rx_commit) = core(name, secret, committee.clone(), store_path);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    tx_core.send(ConsensusMessage::Propose(block)).await.unwrap();

    // Everyone but the next leader (which first gets our vote) receives our timeout of round 1, with NR = 0.
    let next = committee.address(&l2).unwrap();
    let handles: Vec<_> = committee
        .broadcast_addresses(&name)
        .into_iter()
        .filter(|(_, address)| *address != next)
        .map(|(_, address)| listener(address, Some(Bytes::from(expected.clone()))))
        .collect();
    assert!(try_join_all(handles).await.is_ok());
}

#[tokio::test]
async fn honest_node_votes_for_a_block_justified_by_a_tc() {
    // 5.4: Core::make_vote and the E2 check share one voting rule (messages::extends_validly). After round 2 times
    // out, the leader of round 3 extends the QC of round 1 with the TC of round 2: not adjacent, but vouched for. An
    // honest node votes for it (and messages_tests checks that such a vote is not E2).
    let committee = committee_with_base_port(16_700);
    let b1 = chain(vec![leader_keys(1)]).pop().unwrap();
    let qc1 = QC {
        hash: b1.digest(),
        round: 1,
        epoch: EPOCH,
        votes: keys()
            .iter()
            .map(|(key, secret)| {
                let vote = Vote::new_from_key(b1.digest(), 1, *key, secret);
                (vote.author, vote.signature)
            })
            .collect(),
    };
    let mut aggregator = Aggregator::new();
    let tc2 = keys()
        .into_iter()
        .find_map(|(key, secret)| {
            let timeout = Timeout::new_from_key(qc1.clone(), 2, false, key, &secret);
            aggregator.add_timeout(timeout, &committee).unwrap()
        })
        .unwrap();
    let (l3, l3_secret) = leader_keys(3);
    let b3 = Block::new_from_key_with_tc(qc1, Some(tc2), l3, 3, Vec::new(), &l3_secret);

    // Our vote for b3 goes to the leader of round 4, which is not us (it may also get our vote for b1).
    let next = leader_keys(4).0;
    let (name, secret) = keys().into_iter().find(|(key, _)| *key != next).unwrap();
    let vote = Vote::new_from_key(b3.digest(), 3, name, &secret);
    let expected = bincode::serialize(&ConsensusMessage::Vote(vote)).unwrap();
    let mut received = frames(committee.address(&next).unwrap(), 2);
    let store_path = ".db_test_honest_node_votes_for_a_block_justified_by_a_tc";
    let (tx_core, mut rx_proposer, _rx_commit) = core(name, secret, committee.clone(), store_path);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    tx_core.send(ConsensusMessage::Propose(b1)).await.unwrap();
    tx_core.send(ConsensusMessage::Propose(b3)).await.unwrap();

    while received.recv().await.expect("no vote for the block") != Bytes::from(expected.clone()) {}
}

#[tokio::test]
async fn r3_a_second_timeout_of_a_round_repeats_the_first() {
    // 12.9 / R3: a node signs one timeout per round. When its timer fires again in that round it resends the one it
    // signed, even if the proposal has arrived since: a fresh one would report NR = 0 against the NR = 1 it signed.
    let committee = committee_with_base_port(16_800);
    let (l1, l2) = (leader_keys(1).0, leader_keys(2).0);
    let (name, secret) = keys().into_iter().find(|(k, _)| *k != l1 && *k != l2).unwrap();
    let timeout = Timeout::new_from_key(QC::genesis(), 1, true, name, &secret);
    let expected = Bytes::from(bincode::serialize(&ConsensusMessage::Timeout(timeout)).unwrap());
    let mut received = frames(committee.address(&l2).unwrap(), 2);

    let store_path = ".db_test_r3_a_second_timeout_of_a_round_repeats_the_first";
    let (tx_core, mut rx_proposer, _rx_commit) = core(name, secret, committee.clone(), store_path);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });

    assert_eq!(received.recv().await.unwrap(), expected, "no proposal yet: NR = 1");
    let block = chain(vec![leader_keys(1)]).pop().unwrap();
    tx_core.send(ConsensusMessage::Propose(block)).await.unwrap();
    assert_eq!(received.recv().await.unwrap(), expected, "the timer fired again in round 1");
}

#[tokio::test]
async fn r6_a_tc_hands_over_its_high_qc() {
    // 12.9 / R6: a node adopts the high QC a TC carries. A TC of round 2 carries a QC of round 1 the node never saw;
    // the node leads round 3 and proposes on that QC, not on genesis.
    let b1 = chain(vec![leader_keys(1)]).pop().unwrap();
    let qc1 = qc_for(&b1);
    let tc2 = tc_of(2, &qc1, &committee());
    let (name, secret) = leader_keys(3);
    let store_path = ".db_test_r6_a_tc_hands_over_its_high_qc";
    let (tx_core, mut rx_proposer, _rx_commit) = core(name, secret, committee(), store_path);
    tx_core.send(ConsensusMessage::TC(tc2)).await.unwrap();
    match tokio::time::timeout(Duration::from_secs(2), rx_proposer.recv()).await {
        Ok(Some(ProposerMessage::Make { round, qc, .. })) => assert_eq!((round, qc), (3, qc1)),
        other => panic!("no proposal after the TC: {:?}", other),
    }
}

#[tokio::test]
async fn r6_a_tc_inside_a_block_hands_over_its_high_qc() {
    // 12.9 / R6: likewise for the TC inside a block. The block of round 4 extends a QC of round 1 but carries a TC of
    // round 3 reporting a QC of round 2. It breaks the voting rule, so nobody votes; the node still adopts the TC's
    // high QC, so its timeout of round 4 reports the QC of round 2.
    let committee = committee_with_base_port(16_900);
    let (l4, l4_secret) = leader_keys(4);
    let mut signers: Vec<_> = keys().into_iter().filter(|(k, _)| *k != l4).collect();
    let (low, high) = (Digest([1; 32]), Digest([2; 32]));
    let qc1 = QC { hash: low.clone(), round: 1, epoch: EPOCH, votes: signed_by(&signers, low, 1) };
    let qc2 = QC { hash: high.clone(), round: 2, epoch: EPOCH, votes: signed_by(&keys(), high, 2) };
    let tc3 = tc_of(3, &qc2, &committee);
    let block = Block::new_from_key_with_tc(qc1, Some(tc3), l4, 4, Vec::new(), &l4_secret);

    // The block's parent is missing, so the node asks the other signers of its QC for it. The leader of round 4 did
    // not sign, so the first thing it hears from the node is the timeout.
    let (name, secret) = signers.remove(0);
    let timeout = Timeout::new_from_key(qc2, 4, false, name, &secret);
    let expected = bincode::serialize(&ConsensusMessage::Timeout(timeout)).unwrap();
    let store_path = ".db_test_r6_a_tc_inside_a_block_hands_over_its_high_qc";
    let (tx_core, mut rx_proposer, _rx_commit) = core(name, secret, committee.clone(), store_path);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    tx_core.send(ConsensusMessage::Propose(block)).await.unwrap();

    let handle = listener(committee.address(&l4).unwrap(), Some(Bytes::from(expected)));
    assert!(handle.await.is_ok());
}

#[tokio::test]
async fn h3_no_vote_for_a_block_of_the_old_epoch() {
    // 12.9 / H3: a node that entered the next epoch signs nothing of the old one. With epochs of 2 rounds, block 2 is
    // terminal and its commit proof, the QC of round 3, comes inside block 4. So block 4 moves the node to the next
    // epoch, which starts at round 4, while being a block of the old epoch itself: it gets no vote, and the first
    // thing the next leader hears from the node is its timeout of round 4 in the new epoch.
    let committee = committee_with_base_port(17_000);
    let blocks = chain(vec![leader_keys(1), leader_keys(2), leader_keys(3), leader_keys(4)]);

    // A vote for block 4 would go to the leader of round 5 in the new table. That leader may also get our votes for
    // the earlier blocks, so listen for what comes before the timeout.
    let next = LeaderElector::new(Committee { epoch: EPOCH + 1, ..committee.clone() }).get_leader(5);
    let mut received = frames(committee.address(&next).unwrap(), 4);
    let (name, secret) = keys().into_iter().find(|(key, _)| *key != next).unwrap();
    let store_path = ".db_test_h3_no_vote_for_a_block_of_the_old_epoch";
    let (tx_core, mut rx_proposer, mut rx_commit) =
        core_with_epochs(name, secret, committee.clone(), store_path, 2);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    tokio::spawn(async move { while rx_commit.recv().await.is_some() {} });
    for block in blocks {
        tx_core.send(ConsensusMessage::Propose(block)).await.unwrap();
    }

    loop {
        let frame = received.recv().await.unwrap();
        match bincode::deserialize(&frame).unwrap() {
            ConsensusMessage::Timeout(timeout) => {
                assert_eq!((timeout.round, timeout.epoch), (4, EPOCH + 1));
                break;
            }
            ConsensusMessage::Vote(vote) => assert!(vote.round < 4, "a vote for a block of the old epoch"),
            message => panic!("Unexpected message {:?}", message),
        }
    }
}

#[tokio::test]
async fn commit_delivers_skipped_ancestors_oldest_first() {
    // 12.9: after a gap in the chain one commit delivers every uncommitted ancestor, oldest first. In b1 <- b3 <- b4 <-
    // b5 the 2-chain b3 <- b4 commits b3 and, with it, b1.
    let b1 = chain(vec![leader_keys(1)]).pop().unwrap();
    let on = |parent: &Block, round: Round| {
        let (author, secret) = leader_keys(round);
        Block::new_from_key(qc_for(parent), author, round, Vec::new(), &secret)
    };
    let b3 = on(&b1, 3);
    let b4 = on(&b3, 4);
    let b5 = on(&b4, 5);

    let store_path = ".db_test_commit_delivers_skipped_ancestors_oldest_first";
    let (name, secret) = keys().pop().unwrap();
    let (tx_core, mut rx_proposer, mut rx_commit) = core(name, secret, committee(), store_path);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    for block in vec![b1.clone(), b3.clone(), b4, b5] {
        tx_core.send(ConsensusMessage::Propose(block)).await.unwrap();
    }
    assert_eq!(rx_commit.recv().await.unwrap(), b1);
    assert_eq!(rx_commit.recv().await.unwrap(), b3);
}

#[tokio::test]
async fn a_commit_proof_inside_a_timeout_commits() {
    // 12.9: a node commits as soon as it holds a commit proof, not when the next block arrives. Here the proof for
    // block 1, the QC of round 2, comes in another member's timeout, and no later block does.
    let b1 = chain(vec![leader_keys(1)]).pop().unwrap();
    let (l2, l2_secret) = leader_keys(2);
    let b2 = Block::new_from_key(qc_for(&b1), l2, 2, Vec::new(), &l2_secret);

    let mut members = keys();
    let (name, secret) = members.pop().unwrap();
    let (other, other_secret) = members.pop().unwrap();
    let timeout = Timeout::new_from_key(qc_for(&b2), 3, false, other, &other_secret);

    let store_path = ".db_test_a_commit_proof_inside_a_timeout_commits";
    let (tx_core, mut rx_proposer, mut rx_commit) = core(name, secret, committee(), store_path);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    tx_core.send(ConsensusMessage::Propose(b1.clone())).await.unwrap();
    tx_core.send(ConsensusMessage::Propose(b2)).await.unwrap();
    tx_core.send(ConsensusMessage::Timeout(timeout)).await.unwrap();
    match tokio::time::timeout(Duration::from_secs(2), rx_commit.recv()).await {
        Ok(Some(block)) => assert_eq!(block, b1),
        other => panic!("nothing committed: {:?}", other),
    }
}

/// The leader of round 1 on `store`, not running: each call stands for one run of the same node.
fn node_on(store: Store) -> Core {
    node_with_proposer(store).0
}

fn node_with_proposer(store: Store) -> (Core, Receiver<ProposerMessage>) {
    let (name, secret) = leader_keys(1);
    let (tx_loopback, rx_loopback) = channel(1);
    let (tx_mempool, _rx_mempool) = channel(1);
    let (_tx_message, rx_message) = channel(1);
    let (tx_proposer, rx_proposer) = channel(1);
    let (tx_commit, _rx_commit) = channel(1);
    let synchronizer = Synchronizer::new(name, committee(), store.clone(), tx_loopback.clone(), 100_000);
    let core = Core::new(
        name,
        committee(),
        EpochConfig {
            length: 0,
            reference_length: 0,
            entity_cap_ppm: 1_000_000,
            class_cap_ppm: 1_000_000,
            l_max_ppm: 100_000,
            governance_malicious: false,
            leader_rule: Default::default(),
            g2_threshold: 0,
            g2_no_reputation: false,
            aptos_failure_percent: 0,
        },
        Inclusion::new(Duration::from_millis(500), false),
        Faults::default(),
        SignatureService::new(secret),
        store.clone(),
        MempoolDriver::new(store, tx_mempool, tx_loopback),
        synchronizer,
        /* timeout_delay */ 100,
        rx_message,
        rx_loopback,
        tx_proposer,
        tx_commit,
    );
    (core, rx_proposer)
}

fn store_at(path: &str) -> Store {
    let _ = fs::remove_dir_all(path);
    Store::new(path).unwrap()
}

#[tokio::test]
async fn r8_a_restarted_node_does_not_vote_twice() {
    // A leader that sends two blocks of one round: the vote for the first is remembered across a restart.
    let store = store_at(".db_test_r8_a_restarted_node_does_not_vote_twice");
    let (leader, secret) = leader_keys(1);
    let block = Block::new_from_key(QC::genesis(), leader, 1, vec![Digest([1; 32])], &secret);
    let rival = Block::new_from_key(QC::genesis(), leader, 1, vec![Digest([2; 32])], &secret);

    let mut first = node_on(store.clone());
    assert!(first.make_vote(&block).await.is_some());

    let mut second = node_on(store.clone());
    assert!(second.make_vote(&rival).await.is_some(), "without the store a new run would vote again");
    let mut second = node_on(store);
    assert!(second.restore().await);
    assert_eq!((second.round, second.last_voted_round), (1, 1));
    assert!(second.make_vote(&rival).await.is_none());
}

#[tokio::test]
async fn r8_a_restarted_node_reports_nr_0_after_voting() {
    // It voted in the round, so its first timeout after the restart must not claim that no proposal arrived.
    let store = store_at(".db_test_r8_a_restarted_node_reports_nr_0_after_voting");
    let (leader, secret) = leader_keys(1);
    let block = Block::new_from_key(QC::genesis(), leader, 1, Vec::new(), &secret);
    assert!(node_on(store.clone()).make_vote(&block).await.is_some());

    let mut restarted = node_on(store);
    assert!(restarted.restore().await);
    restarted.local_timeout_round().await.unwrap();
    let timeout = restarted.last_timeout.clone().unwrap();
    assert_eq!((timeout.round, timeout.nr), (1, false));
}

#[tokio::test]
async fn r8_a_restarted_node_resends_its_timeout() {
    // R3 across a restart: the timeout of the round, not a second one that could say something else.
    let store = store_at(".db_test_r8_a_restarted_node_resends_its_timeout");
    let mut first = node_on(store.clone());
    first.local_timeout_round().await.unwrap();
    let signed = first.last_timeout.clone().unwrap();
    assert!(signed.nr);

    let mut restarted = node_on(store);
    assert!(restarted.restore().await);
    assert_eq!(restarted.last_timeout.as_ref().map(|t| t.digest()), Some(signed.digest()));
    restarted.local_timeout_round().await.unwrap();
    assert_eq!(restarted.last_timeout.as_ref().unwrap().digest(), signed.digest());

    // Until the chain is replayed the table is behind the epoch of what was signed.
    let later = Timeout { epoch: EPOCH + 1, ..signed };
    restarted.last_timeout = Some(later.clone());
    restarted.local_timeout_round().await.unwrap();
    assert_eq!(restarted.last_timeout.unwrap().digest(), later.digest());
}

#[tokio::test]
async fn r8_a_restarted_leader_does_not_propose_again() {
    // The leader of round 1 proposes when it boots, but not if it has been through that round before.
    let store = store_at(".db_test_r8_a_restarted_leader_does_not_propose_again");
    let (mut fresh, mut rx_proposer) = node_with_proposer(store.clone());
    tokio::spawn(async move { fresh.run().await });
    assert!(matches!(rx_proposer.recv().await, Some(ProposerMessage::Make { .. })));
    sleep(Duration::from_millis(150)).await; // its timeout of round 1 is remembered

    let (mut restarted, mut rx_proposer) = node_with_proposer(store);
    tokio::spawn(async move { restarted.run().await });
    assert!(timeout(Duration::from_millis(50), rx_proposer.recv()).await.is_err());
}

#[tokio::test]
async fn r8_the_high_qc_survives_a_restart() {
    let store = store_at(".db_test_r8_the_high_qc_survives_a_restart");
    let b1 = chain(vec![leader_keys(1)]).pop().unwrap();
    let qc = qc_for(&b1);
    let mut first = node_on(store.clone());
    first.update_high_qc(&qc);
    first.last_voted_round = 5;
    first.remember().await;

    let mut restarted = node_on(store);
    assert!(restarted.restore().await);
    assert_eq!(restarted.high_qc.round, 1);
    assert_eq!(restarted.round, 5);
}

#[tokio::test]
async fn r8_a_restarted_node_replays_its_own_chain() {
    // The ledger and the tables are in memory, the chain is in the store. A restarted node rebuilds them at once and
    // without the network: nothing of a later epoch can be processed before that.
    // Round 4 timed out, so the highest QC does not prove a commit: the last proof is the QC of round 3 for B3, over
    // its parent B2, and B3 itself must stay uncommitted.
    let mut store = store_at(".db_test_r8_a_restarted_node_replays_its_own_chain");
    let mut blocks = chain(vec![leader_keys(1), leader_keys(2), leader_keys(3)]);
    let (leader, secret) = leader_keys(5);
    blocks.push(Block::new_from_key(qc_for(&blocks[2]), leader, 5, Vec::new(), &secret));
    for block in &blocks {
        store.write(block.digest().to_vec(), bincode::serialize(block).unwrap()).await;
    }
    let mut first = node_on(store.clone());
    first.update_high_qc(&qc_for(&blocks[3]));
    first.last_voted_round = 5;
    first.remember().await;

    let (name, secret) = keys().pop().unwrap();
    let (_tx_core, _rx_proposer, mut rx_commit) = core_on(name, secret, committee_with_base_port(17_400), store, 100);
    for expected in &blocks[..2] {
        let committed = timeout(Duration::from_secs(1), rx_commit.recv()).await;
        assert_eq!(committed.expect("nothing was replayed").unwrap(), *expected);
    }
    assert!(timeout(Duration::from_millis(50), rx_commit.recv()).await.is_err(), "a block without a commit proof");
}

#[tokio::test]
async fn r8_a_fresh_store_is_a_fresh_start() {
    let mut node = node_on(store_at(".db_test_r8_a_fresh_store_is_a_fresh_start"));
    assert!(!node.restore().await);
    assert_eq!((node.round, node.last_voted_round), (1, 0));
}

#[tokio::test]
async fn a_forged_transaction_is_neither_kept_nor_forwarded() {
    let committee = committee_with_base_port(17_300);
    let (name, secret) = keys().pop().unwrap();
    let peer = keys().remove(0).0;
    let mut received = frames(committee.address(&peer).unwrap(), 1);
    let store_path = ".db_test_a_forged_transaction_is_neither_kept_nor_forwarded";
    let (tx_core, mut rx_proposer, _rx_commit) = core(name, secret, committee.clone(), store_path);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });

    let real = signed_otx(1, 1, 0);
    let forged = Otx { data: [9; 32], ..real.clone() };
    tx_core.send(ConsensusMessage::Otx(forged)).await.unwrap();
    tx_core.send(ConsensusMessage::Otx(real.clone())).await.unwrap();

    match bincode::deserialize(&received.recv().await.unwrap()).unwrap() {
        ConsensusMessage::Otx(x) => assert_eq!(x, real),
        message => panic!("Unexpected message {:?}", message),
    }
}

#[tokio::test]
async fn a_transaction_of_an_abandoned_block_is_proposed_again() {
    // 2.1: block 1 holds x and gets certified, but the TC of round 2 does not report that QC and the chain goes on
    // from genesis. The QCs of blocks 3 and 4 commit block 3: block 1 is abandoned, and the leader of round 6, which
    // had counted x as included, proposes it again.
    let x = signed_otx(1, 1, 0);
    let (l1, l1_secret) = leader_keys(1);
    let b1 = Block::new_from_key_full(
        QC::genesis(),
        None,
        Vec::new(),
        vec![x.clone()],
        Vec::new(),
        l1,
        1,
        Vec::new(),
        &l1_secret,
    );
    let (l3, l3_secret) = leader_keys(3);
    let tc2 = tc_of(2, &QC::genesis(), &committee());
    let b3 = Block::new_from_key_with_tc(QC::genesis(), Some(tc2), l3, 3, Vec::new(), &l3_secret);
    let (l4, l4_secret) = leader_keys(4);
    let b4 = Block::new_from_key(qc_for(&b3), l4, 4, Vec::new(), &l4_secret);
    let (l5, l5_secret) = leader_keys(5);
    let b5 = Block::new_from_key(qc_for(&b4), l5, 5, Vec::new(), &l5_secret);
    let tc5 = tc_of(5, &qc_for(&b4), &committee());

    // Another member's timeout brings the QC of block 1: we hold the block, so it counts as certified here.
    let (name, secret) = leader_keys(6);
    let (other, other_secret) = keys().into_iter().find(|(k, _)| *k != name).unwrap();
    let timeout = Timeout::new_from_key(qc_for(&b1), 2, false, other, &other_secret);

    let store_path = ".db_test_a_transaction_of_an_abandoned_block_is_proposed_again";
    let (tx_core, mut rx_proposer, _rx_commit) = core(name, secret, committee(), store_path);
    let messages = vec![
        ConsensusMessage::Otx(x.clone()),
        ConsensusMessage::Propose(b1),
        ConsensusMessage::Timeout(timeout),
        ConsensusMessage::Propose(b3),
        ConsensusMessage::Propose(b4),
        ConsensusMessage::Propose(b5),
        ConsensusMessage::TC(tc5),
    ];
    tokio::spawn(async move {
        for message in messages {
            tx_core.send(message).await.unwrap();
        }
        std::future::pending::<()>().await; // the core stops if the channel closes
    });

    let proposed = tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            if let Some(ProposerMessage::Make { round: 6, otxs, .. }) = rx_proposer.recv().await {
                return otxs;
            }
        }
    });
    assert_eq!(proposed.await.expect("no proposal for round 6"), vec![x]);
}

#[test]
fn deferred_keeps_the_next_epoch_within_each_members_share() {
    // 8.9: a message of a later epoch than the next is not kept, or it could sit here for good; a member that uses up
    // its share of the bytes does not touch the others'; entering the epoch empties the buffer and restores the shares.
    let (a, b) = (keys()[0].0, keys()[1].0);
    let next = EPOCH + 1;
    let vote = |epoch, author| {
        let (hash, signature) = (Digest::default(), Signature::default());
        ConsensusMessage::Vote(Vote { hash, round: 5, epoch, author, signature })
    };
    let size = bincode::serialized_size(&vote(next, a)).unwrap() as usize;
    let members = MAX_DEFERRED_BYTES / (3 * size); // a share of three votes
    let mut deferred = Deferred::default();

    assert!(!deferred.add(next, members, a, vote(next + 1, a)));
    for _ in 0..3 {
        assert!(deferred.add(next, members, a, vote(next, a)));
    }
    assert!(!deferred.add(next, members, a, vote(next, a)));
    assert!(deferred.add(next, members, b, vote(next, b)));

    assert_eq!(deferred.take().len(), 4);
    assert!(deferred.add(next, members, a, vote(next, a)));
}

#[tokio::test]
async fn a_message_of_a_later_epoch_must_be_signed_by_a_member() {
    // 8.9: a vote of a later epoch makes us ask the voter for its block, and it would be kept. A forged one gets
    // nothing, so the first thing the voter hears from us is the request for the block of the signed vote after it.
    let committee = committee_with_base_port(17_100);
    let mut members = keys();
    let (name, secret) = members.remove(0);
    let (voter, voter_secret) = members.remove(0);
    let (forged_hash, hash) = (Digest([8; 32]), Digest([9; 32]));
    let vote = |hash, signature| Vote { hash, round: 5, epoch: EPOCH + 1, author: voter, signature };
    let forged = vote(forged_hash, Signature::default());
    let signature = Signature::new(&vote_digest(EPOCH + 1, &hash, 5), &voter_secret);
    let signed = vote(hash.clone(), signature);
    let expected = bincode::serialize(&ConsensusMessage::SyncRequest(hash, name)).unwrap();

    let mut received = frames(committee.address(&voter).unwrap(), 1);
    tokio::time::sleep(Duration::from_millis(20)).await;
    let store_path = ".db_test_a_message_of_a_later_epoch_must_be_signed_by_a_member";
    let (tx_core, mut rx_proposer, _rx_commit) = core(name, secret, committee.clone(), store_path);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    tx_core.send(ConsensusMessage::Vote(forged)).await.unwrap();
    tx_core.send(ConsensusMessage::Vote(signed)).await.unwrap();
    assert_eq!(received.recv().await.unwrap(), Bytes::from(expected));
}

#[tokio::test]
async fn a_block_of_a_far_epoch_still_asks_for_its_parent() {
    // 8.9: a node several epochs behind catches up by fetching blocks backwards from what it hears. A block more than
    // one epoch ahead is not kept, but it must still ask its author for its parent.
    let committee = committee_with_base_port(17_200);
    let mut members = keys();
    let (name, secret) = members.remove(0);
    let (author, author_secret) = members.remove(0);
    let parent = Digest([7; 32]);
    let epoch = EPOCH + 5;
    let qc = QC { hash: parent.clone(), round: 9, epoch, votes: Vec::new() };
    let mut block = Block::new_from_key(qc, author, 10, Vec::new(), &author_secret);
    block.epoch = epoch;
    block.signature = Signature::new(&block.digest(), &author_secret);
    let expected = bincode::serialize(&ConsensusMessage::SyncRequest(parent, name)).unwrap();

    let mut received = frames(committee.address(&author).unwrap(), 1);
    tokio::time::sleep(Duration::from_millis(20)).await;
    let store_path = ".db_test_a_block_of_a_far_epoch_still_asks_for_its_parent";
    let (tx_core, mut rx_proposer, _rx_commit) = core(name, secret, committee.clone(), store_path);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    tx_core.send(ConsensusMessage::Propose(block)).await.unwrap();
    assert_eq!(received.recv().await.unwrap(), Bytes::from(expected));
}

/// Whether `expected` is among the first frames a listener gets within two seconds (our own timeouts may come
/// first when the timer fires before the message is handled).
async fn asked(mut received: Receiver<Bytes>, expected: Bytes) -> bool {
    let found = async {
        while let Some(frame) = received.recv().await {
            if frame == expected {
                return true;
            }
        }
        false
    };
    timeout(Duration::from_secs(2), found).await.unwrap_or(false)
}

#[tokio::test]
async fn a_block_of_the_next_epoch_asks_the_signers_of_its_qc() {
    // A node that missed the terminal block or its child cannot enter the next epoch, nor vote in it, until it has
    // them. It asks a few signers of the QC, as the synchronizer does, not only the author of the block: one late
    // request or reply would hold its votes back for the whole delay.
    let committee = committee_with_base_port(17_500);
    let mut members = keys();
    let (name, secret) = members.remove(0);
    let parent = Digest([6; 32]);
    let qc = QC { hash: parent.clone(), round: 9, epoch: EPOCH, votes: signed_by(&members, parent.clone(), 9) };
    let signer = members[1].0;
    let (author, author_secret) = members.remove(0);
    let mut block = Block::new_from_key(qc, author, 10, Vec::new(), &author_secret);
    block.epoch = EPOCH + 1;
    block.signature = Signature::new(&block.digest(), &author_secret);
    let expected = bincode::serialize(&ConsensusMessage::SyncRequest(parent, name)).unwrap();

    let received = frames(committee.address(&signer).unwrap(), 4);
    tokio::time::sleep(Duration::from_millis(20)).await;
    let store_path = ".db_test_a_block_of_the_next_epoch_asks_the_signers_of_its_qc";
    let (tx_core, mut rx_proposer, _rx_commit) = core(name, secret, committee.clone(), store_path);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    tx_core.send(ConsensusMessage::Propose(block)).await.unwrap();
    assert!(asked(received, Bytes::from(expected)).await, "a signer of the QC is asked");
}

#[tokio::test]
async fn copies_of_a_block_of_the_next_epoch_ask_for_its_parent_once() {
    // Each reply to such a request is itself a block of the next epoch, and it comes from several signers: asking
    // again on every copy multiplied the requests into a storm that kept a lagging node behind.
    let committee = committee_with_base_port(17_700);
    let mut members = keys();
    let (name, secret) = members.remove(0);
    let parent = Digest([4; 32]);
    let qc = QC { hash: parent.clone(), round: 9, epoch: EPOCH, votes: signed_by(&members, parent.clone(), 9) };
    let signer = members[1].0;
    let (author, author_secret) = members.remove(0);
    let mut block = Block::new_from_key(qc, author, 10, Vec::new(), &author_secret);
    block.epoch = EPOCH + 1;
    block.signature = Signature::new(&block.digest(), &author_secret);
    let expected = Bytes::from(bincode::serialize(&ConsensusMessage::SyncRequest(parent, name)).unwrap());

    let mut received = frames(committee.address(&signer).unwrap(), 16);
    tokio::time::sleep(Duration::from_millis(20)).await;
    let store_path = ".db_test_copies_of_a_block_of_the_next_epoch_ask_for_its_parent_once";
    let (tx_core, mut rx_proposer, _rx_commit) = core(name, secret, committee.clone(), store_path);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    for _ in 0..3 {
        tx_core.send(ConsensusMessage::Propose(block.clone())).await.unwrap();
    }
    let mut asks = 0;
    let _ = timeout(Duration::from_millis(500), async {
        while let Some(frame) = received.recv().await {
            if frame == expected {
                asks += 1;
            }
        }
    })
    .await;
    assert_eq!(asks, 1);
}

#[tokio::test]
async fn a_node_missing_an_older_block_enters_on_the_commit_proof() {
    // H1' and H3 (DESIGN.md §15.10): the next table is known an epoch ahead, so a node that holds the terminal block
    // (B10, epochs of 10 rounds), its child and the commit proof enters the next epoch although B9 never came and its
    // ledger cannot reach B10. Its next timeout is of the new epoch; before, it stayed in the old one.
    let committee = committee_with_base_port(17_900);
    let at = |qc: QC, round: Round| {
        let (author, secret) = leader_keys(round);
        Block::new_from_key(qc, author, round, Vec::new(), &secret)
    };
    let b9 = at(QC::genesis(), 9);
    let b10 = at(qc_for(&b9), 10);
    let b11 = at(qc_for(&b10), 11);
    let mut b12 = at(qc_for(&b11), 12);
    b12.epoch = EPOCH + 1;
    b12.signature = Signature::new(&b12.digest(), &leader_keys(12).1);

    let mut members = keys();
    let (name, secret) = members.remove(0);
    let peer = members[0].0;
    let mut received = all_frames(committee.address(&peer).unwrap());
    tokio::time::sleep(Duration::from_millis(20)).await;
    let store_path = ".db_test_a_node_missing_an_older_block_enters_on_the_commit_proof";
    let (tx_core, mut rx_proposer, _rx_commit) = core_with_epochs(name, secret, committee.clone(), store_path, 10);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    for block in [b10, b11, b12] {
        tx_core.send(ConsensusMessage::Propose(block)).await.unwrap();
    }
    let new_epoch = async {
        while let Some(frame) = received.recv().await {
            if let Ok(ConsensusMessage::Timeout(t)) = bincode::deserialize(&frame) {
                if t.epoch == EPOCH + 1 {
                    return true;
                }
            }
        }
        false
    };
    assert!(timeout(Duration::from_secs(2), new_epoch).await.unwrap_or(false), "no timeout of the new epoch");
}

#[tokio::test]
async fn the_commit_proof_before_the_terminal_block_still_enters() {
    // The commit proof can come first: the first block of the next epoch (B12, carrying the QC of B11) reaches the
    // node before the child of the terminal block, which comes only after the node's first timeout in round 12 (a
    // timeout repeated in the same round is resent, and processes nothing again). When B11 comes, the proof already
    // at hand must let it enter; B9 is still missing, so the ledger cannot get there.
    let committee = committee_with_base_port(18_000);
    let at = |qc: QC, round: Round| {
        let (author, secret) = leader_keys(round);
        Block::new_from_key(qc, author, round, Vec::new(), &secret)
    };
    let b9 = at(QC::genesis(), 9);
    let b10 = at(qc_for(&b9), 10);
    let b11 = at(qc_for(&b10), 11);
    let mut b12 = at(qc_for(&b11), 12);
    b12.epoch = EPOCH + 1;
    b12.signature = Signature::new(&b12.digest(), &leader_keys(12).1);

    let mut members = keys();
    let (name, secret) = members.remove(0);
    let peer = members[0].0;
    let mut received = all_frames(committee.address(&peer).unwrap());
    tokio::time::sleep(Duration::from_millis(20)).await;
    let store_path = ".db_test_the_commit_proof_before_the_terminal_block_still_enters";
    let (tx_core, mut rx_proposer, _rx_commit) = core_with_epochs(name, secret, committee.clone(), store_path, 10);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    tx_core.send(ConsensusMessage::Propose(b10)).await.unwrap();
    tx_core.send(ConsensusMessage::Propose(b12)).await.unwrap();
    tokio::time::sleep(Duration::from_millis(350)).await;
    tx_core.send(ConsensusMessage::Propose(b11)).await.unwrap();
    let new_epoch = async {
        while let Some(frame) = received.recv().await {
            if let Ok(ConsensusMessage::Timeout(t)) = bincode::deserialize(&frame) {
                if t.epoch == EPOCH + 1 {
                    return true;
                }
            }
        }
        false
    };
    assert!(timeout(Duration::from_secs(2), new_epoch).await.unwrap_or(false), "no timeout of the new epoch");
}

#[tokio::test]
async fn a_timeout_of_the_next_epoch_fetches_the_block_its_qc_certifies() {
    // The commit proof of the terminal block can reach a lagging node inside a timeout of the next epoch, when no
    // block comes (the round is stalling, and its vote may be the one missing). Without the block it certifies the
    // node cannot enter the epoch: it asks the signers of the QC for it at once.
    let committee = committee_with_base_port(17_600);
    let mut members = keys();
    let (name, secret) = members.remove(0);
    let hash = Digest([5; 32]);
    let high_qc = QC { hash: hash.clone(), round: 9, epoch: EPOCH, votes: signed_by(&members, hash.clone(), 9) };
    let signer = members[2].0;
    let (author, author_secret) = members.remove(0);
    let mut stalled = Timeout::new_from_key(high_qc, 10, false, author, &author_secret);
    stalled.epoch = EPOCH + 1;
    stalled.signature = Signature::new(&stalled.digest(), &author_secret);
    let expected = bincode::serialize(&ConsensusMessage::SyncRequest(hash, name)).unwrap();

    let received = frames(committee.address(&signer).unwrap(), 4);
    tokio::time::sleep(Duration::from_millis(20)).await;
    let store_path = ".db_test_a_timeout_of_the_next_epoch_fetches_the_block_its_qc_certifies";
    let (tx_core, mut rx_proposer, _rx_commit) = core(name, secret, committee.clone(), store_path);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    tx_core.send(ConsensusMessage::Timeout(stalled)).await.unwrap();
    assert!(asked(received, Bytes::from(expected)).await, "a signer of the QC is asked");
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

#[test]
fn split_brain_vote_window() {
    // DESIGN.md §15.15: an experiment switch; 0 leaves a bound open.
    let all = Faults::default();
    assert!(all.votes_in(1) && all.votes_in(1_000_000));
    let early = Faults { vote_until: 10, ..Faults::default() };
    assert!(early.votes_in(10) && !early.votes_in(11));
    let late = Faults { vote_from: 11, ..Faults::default() };
    assert!(!late.votes_in(10) && late.votes_in(11));
}

#[test]
fn parameter_check_keeps_the_class_cap_below_the_tolerated_share() {
    // The paper's defaults pass; a class cap at or above (1 - B_rep - L_max)/3 = 26.7% does not; no class cap passes.
    use crate::config::Parameters;
    assert!(Parameters::default().check().is_ok());
    assert_eq!(Parameters::default().class_cap_ppm, 250_000);
    assert!(Parameters { class_cap_ppm: 290_000, ..Parameters::default() }.check().is_err());
    assert!(Parameters { class_cap_ppm: 1_000_000, ..Parameters::default() }.check().is_ok());
}

/// The key of the leader of `round` in `epoch` (the fixture tables all have equal stakes). The first round of the
/// next epoch (12 with epochs of 10 rounds) keeps the old table's leader.
fn leader_in(epoch: EpochNumber, round: Round) -> (PublicKey, SecretKey) {
    if epoch == EPOCH || round == 12 {
        return leader_keys(round);
    }
    let leader = LeaderElector::new(Committee { epoch, ..committee() }).get_leader(round);
    keys().into_iter().find(|(key, _)| *key == leader).unwrap()
}

/// The QC of every member for `block`, in its epoch.
fn qc_in(block: &Block) -> QC {
    let digest = vote_digest(block.epoch, &block.digest(), block.round);
    let votes = keys().iter().map(|(key, secret)| (*key, Signature::new(&digest, secret))).collect();
    QC { hash: block.digest(), round: block.round, epoch: block.epoch, votes }
}

/// Block `round` of `epoch` on `qc` (and `tc`), naming the fixture table of its epoch, by the right leader.
fn block_in(qc: QC, tc: Option<TC>, round: Round, epoch: EpochNumber) -> Block {
    let (author, secret) = leader_in(epoch, round);
    let mut block = Block::new_from_key_with_tc(qc, tc, author, round, Vec::new(), &secret);
    block.epoch = epoch;
    block.table = table_at(epoch);
    block.signature = Signature::new(&block.digest(), &secret);
    block
}

/// The TC of `round` in `epoch` that every member makes, each reporting `high_qc`.
fn tc_in(round: Round, epoch: EpochNumber, high_qc: &QC) -> TC {
    let table = Committee { epoch, ..committee() };
    let mut aggregator = Aggregator::new();
    keys()
        .into_iter()
        .find_map(|(author, secret)| {
            let mut timeout =
                Timeout { high_qc: high_qc.clone(), round, epoch, nr: false, author, signature: Signature::default() };
            timeout.signature = Signature::new(&timeout.digest(), &secret);
            aggregator.add_timeout(timeout, &table).unwrap()
        })
        .unwrap()
}

/// Epochs of 10 rounds: B9 <- B10 (terminal) <- B11 (its child, the commit proof) <- B12 <- B13 <- B14, the last
/// three of the next epoch.
fn handover_chain() -> Vec<Block> {
    let b9 = block_in(QC::genesis(), None, 9, EPOCH);
    let b10 = block_in(qc_in(&b9), None, 10, EPOCH);
    let b11 = block_in(qc_in(&b10), None, 11, EPOCH);
    let b12 = block_in(qc_in(&b11), None, 12, EPOCH + 1);
    let b13 = block_in(qc_in(&b12), None, 13, EPOCH + 1);
    let b14 = block_in(qc_in(&b13), None, 14, EPOCH + 1);
    vec![b9, b10, b11, b12, b13, b14]
}

#[tokio::test]
async fn h4_the_child_of_the_terminal_block_stays_off_the_ledger() {
    // H4: B11 is committed (with B12 <- B13) but only certifies the terminal block B10: it is not on the ledger and
    // never reaches the application. The ledger goes B9, B10, B12.
    let blocks = handover_chain();
    let (b9, b10, b12) = (blocks[0].clone(), blocks[1].clone(), blocks[3].clone());
    let store_path = ".db_test_h4_the_child_of_the_terminal_block_stays_off_the_ledger";
    let (name, secret) = keys().pop().unwrap();
    let (tx_core, mut rx_proposer, mut rx_commit) =
        core_with_epochs(name, secret, committee_with_base_port(18_400), store_path, 10);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    // Read the commits as they come: the commit channel holds one block, and the core waits on it.
    let ledger = tokio::spawn(async move {
        let mut ledger = Vec::new();
        while ledger.len() < 3 {
            match timeout(Duration::from_secs(3), rx_commit.recv()).await {
                Ok(Some(block)) => ledger.push(block),
                _ => break,
            }
        }
        ledger
    });
    for block in blocks {
        tx_core.send(ConsensusMessage::Propose(block)).await.unwrap();
    }
    let ledger = ledger.await.unwrap();
    assert!(ledger == vec![b9, b10, b12], "{:?}", ledger.iter().map(|b| b.round).collect::<Vec<_>>());
}

#[tokio::test]
async fn h2_no_vote_for_a_block_of_the_new_epoch_off_the_terminal_block() {
    // H2: after entering the next epoch on B10, a block of that epoch must have B10 as an ancestor. B13' extends B9
    // (before B10) through a TC of round 12 whose signers report B9's QC: it passes the voting rule, but not H2, so
    // the node neither stores nor votes for it. The proper B13, extending B12, gets the vote of round 13.
    let committee = committee_with_base_port(18_500);
    let blocks = handover_chain();
    let b9 = blocks[0].clone();
    let good = blocks[4].clone();
    let bad = block_in(qc_in(&b9), Some(tc_in(12, EPOCH + 1, &qc_in(&b9))), 13, EPOCH + 1);
    assert!(extends_validly(bad.round, bad.qc.round, bad.tc.as_ref()));

    let next = leader_in(EPOCH + 1, 14).0;
    let mut received = all_frames(committee.address(&next).unwrap());
    tokio::time::sleep(Duration::from_millis(20)).await;
    let (name, secret) = keys().into_iter().find(|(key, _)| *key != next).unwrap();
    let store_path = ".db_test_h2_no_vote_for_a_block_of_the_new_epoch_off_the_terminal_block";
    let (tx_core, mut rx_proposer, mut rx_commit) = core_with_epochs(name, secret, committee.clone(), store_path, 10);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    tokio::spawn(async move { while rx_commit.recv().await.is_some() {} });
    for block in blocks[..4].iter().cloned().chain([bad.clone(), good.clone()]) {
        tx_core.send(ConsensusMessage::Propose(block)).await.unwrap();
    }
    let vote_13 = async {
        while let Some(frame) = received.recv().await {
            if let Ok(ConsensusMessage::Vote(vote)) = bincode::deserialize(&frame) {
                if vote.round == 13 {
                    return Some(vote.hash);
                }
            }
        }
        None
    };
    let voted = timeout(Duration::from_secs(2), vote_13).await.unwrap_or(None);
    assert!(voted != Some(bad.digest()), "voted for a block off the terminal block");
    assert_eq!(voted, Some(good.digest()));
}

#[tokio::test]
async fn h2_off_votes_for_a_block_of_the_new_epoch_off_the_terminal_block() {
    // The ablation of the test above (DESIGN.md §15.26): with H2 off, B13' passes the voting rule, so the node stores
    // it and gives it the vote of round 13 -- the check that keeps it out is H2 alone.
    let committee = committee_with_base_port(18_600);
    let blocks = handover_chain();
    let b9 = blocks[0].clone();
    let good = blocks[4].clone();
    let bad = block_in(qc_in(&b9), Some(tc_in(12, EPOCH + 1, &qc_in(&b9))), 13, EPOCH + 1);

    let next = leader_in(EPOCH + 1, 14).0;
    let mut received = all_frames(committee.address(&next).unwrap());
    tokio::time::sleep(Duration::from_millis(20)).await;
    let (name, secret) = keys().into_iter().find(|(key, _)| *key != next).unwrap();
    let store_path = ".db_test_h2_off_votes_for_a_block_of_the_new_epoch_off_the_terminal_block";
    let _ = fs::remove_dir_all(store_path);
    let faults = Faults { no_h2: true, ..Faults::default() };
    let (tx_core, mut rx_proposer, mut rx_commit) =
        core_on_with(name, secret, committee.clone(), Store::new(store_path).unwrap(), 10, faults);
    tokio::spawn(async move { while rx_proposer.recv().await.is_some() {} });
    tokio::spawn(async move { while rx_commit.recv().await.is_some() {} });
    for block in blocks[..4].iter().cloned().chain([bad.clone(), good.clone()]) {
        tx_core.send(ConsensusMessage::Propose(block)).await.unwrap();
    }
    let vote_13 = async {
        while let Some(frame) = received.recv().await {
            if let Ok(ConsensusMessage::Vote(vote)) = bincode::deserialize(&frame) {
                if vote.round == 13 {
                    return Some(vote.hash);
                }
            }
        }
        None
    };
    let voted = timeout(Duration::from_secs(2), vote_13).await.unwrap_or(None);
    assert_eq!(voted, Some(bad.digest()), "with H2 off the block off the terminal block should get the vote");
}

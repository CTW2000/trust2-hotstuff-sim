use super::*;
use crate::common::{chain, committee, committee_with_base_port, keys, listener};
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
    let leader_elector = LeaderElector::new(committee.clone());
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

    Core::spawn(
        name,
        committee,
        signature_service,
        store,
        leader_elector,
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
        ProposerMessage::Make(round, qc, tc) => {
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

/// A QC for `block` signed by every member.
fn qc_for(block: &Block) -> QC {
    let votes = keys()
        .iter()
        .map(|(key, secret)| {
            let vote = Vote::new_from_key(block.digest(), block.round, *key, secret);
            (vote.author, vote.signature)
        })
        .collect();
    QC { hash: block.digest(), round: block.round, votes }
}

#[tokio::test]
async fn commit_delivers_skipped_ancestors_oldest_first() {
    // Baseline fix, as in the prototype: after a gap in the chain one commit delivers every uncommitted ancestor, oldest
    // first (upstream delivered them newest first). In b1 <- b3 <- b4 <- b5 the 2-chain b3 <- b4 commits b3 and, with
    // it, b1.
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
    // Baseline fix, as in the prototype: a node commits as soon as it holds a commit proof, not when the next block
    // arrives. Here the proof for block 1, the QC of round 2, comes in another member's timeout, and no later block
    // does.
    let b1 = chain(vec![leader_keys(1)]).pop().unwrap();
    let (l2, l2_secret) = leader_keys(2);
    let b2 = Block::new_from_key(qc_for(&b1), l2, 2, Vec::new(), &l2_secret);

    let mut members = keys();
    let (name, secret) = members.pop().unwrap();
    let (other, other_secret) = members.pop().unwrap();
    let timeout = Timeout::new_from_key(qc_for(&b2), 3, other, &other_secret);

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

#[tokio::test]
async fn local_timeout_round() {
    let committee = committee_with_base_port(16_100);

    // Make the timeout vote we expect to send.
    let (public_key, secret_key) = leader_keys(3);
    let timeout = Timeout::new_from_key(QC::genesis(), 1, public_key, &secret_key);
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

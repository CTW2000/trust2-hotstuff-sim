use super::*;
use crate::common::{block, chain, committee, committee_with_base_port, keys, listener};
use std::fs;
use tokio::time::timeout;

#[tokio::test]
async fn get_existing_parent_block() {
    let mut chain = chain(keys());
    let block = chain.pop().unwrap();
    let b2 = chain.pop().unwrap();

    // Add the block b2 to the store.
    let path = ".db_test_get_existing_parent_block";
    let _ = fs::remove_dir_all(path);
    let mut store = Store::new(path).unwrap();
    let key = b2.digest().to_vec();
    let value = bincode::serialize(&b2).unwrap();
    let _ = store.write(key, value).await;

    // Make a new synchronizer.
    let (name, _) = keys().pop().unwrap();
    let (tx_loopback, _) = channel(10);
    let mut synchronizer = Synchronizer::new(
        name,
        committee(),
        store,
        tx_loopback,
        /* sync_retry_delay */ 10_000,
    );

    // Ask the predecessor of 'block' to the synchronizer.
    match synchronizer.get_parent_block(&block).await {
        Ok(Some(b)) => assert_eq!(b, b2),
        _ => assert!(false),
    }
}

#[tokio::test]
async fn get_genesis_parent_block() {
    // Make a new synchronizer.
    let path = ".db_test_get_genesis_parent_block";
    let _ = fs::remove_dir_all(path);
    let store = Store::new(path).unwrap();
    let (name, _) = keys().pop().unwrap();
    let (tx_loopback, _) = channel(1);
    let mut synchronizer = Synchronizer::new(
        name,
        committee(),
        store,
        tx_loopback,
        /* sync_retry_delay */ 10_000,
    );

    // Ask the predecessor of 'block' to the synchronizer.
    match synchronizer.get_parent_block(&block()).await {
        Ok(Some(b)) => assert_eq!(b, Block::genesis()),
        _ => assert!(false),
    }
}

// The synchronizer of `name` is asked for the parent of the last block of the chain, which it does not have:
// it must send a sync request to the signers of the QC certifying the parent (all three other signers here,
// as the fan-out is three) and loop the block back once the parent is stored.
async fn missing_parent(name: PublicKey, base_port: u16, store_path: &str) {
    let committee = committee_with_base_port(base_port);
    let mut chain = chain(keys());
    let block = chain.pop().unwrap();
    let parent_block = chain.pop().unwrap();

    // Make a new synchronizer.
    let _ = fs::remove_dir_all(store_path);
    let mut store = Store::new(store_path).unwrap();
    let (tx_loopback, mut rx_loopback) = channel(1);
    let mut synchronizer = Synchronizer::new(
        name,
        committee.clone(),
        store.clone(),
        tx_loopback,
        /* sync_retry_delay */ 10_000,
    );

    // Spawn listeners to receive our sync request: the other signers of the QC, which stored the parent
    // before voting for it (the author of the block may hold only the QC).
    let message = ConsensusMessage::SyncRequest(parent_block.digest(), name);
    let expected = Bytes::from(bincode::serialize(&message).unwrap());
    let targets: Vec<_> = block
        .qc
        .votes
        .iter()
        .filter(|(signer, _)| *signer != name)
        .map(|(signer, _)| committee.address(signer).unwrap())
        .collect();
    assert_eq!(targets.len(), SYNC_FANOUT);
    let listener_handles: Vec<_> = targets
        .into_iter()
        .map(|address| listener(address, Some(expected.clone())))
        .collect();

    // Ask for the parent of a block to the synchronizer. The store does not have the parent yet.
    let copy = block.clone();
    let handle = tokio::spawn(async move {
        let ret = synchronizer.get_parent_block(&copy).await;
        assert!(ret.is_ok());
        assert!(ret.unwrap().is_none());
    });

    // Ensure the listeners correctly received the sync request (well before any retry).
    for listener_handle in listener_handles {
        let received = timeout(Duration::from_secs(2), listener_handle).await;
        assert!(matches!(received, Ok(Ok(()))), "a signer of the QC was not asked");
    }

    // Ensure the synchronizer returns None, thus suspending the processing of the block.
    assert!(handle.await.is_ok());

    // Add the parent to the store.
    let key = parent_block.digest().to_vec();
    let value = bincode::serialize(&parent_block).unwrap();
    let _ = store.write(key, value).await;

    // Now that we have the parent, ensure the synchronizer loops back the block to the core
    // to resume processing.
    let delivered = rx_loopback.recv().await.unwrap();
    assert_eq!(delivered, block.clone());
}

#[tokio::test]
async fn get_missing_parent_block() {
    // The last block of the chain is authored by the last key; we are another node.
    let (name, _) = keys().remove(0);
    missing_parent(name, 12_000, ".db_test_get_missing_parent_block").await;
}

#[tokio::test]
async fn get_missing_parent_of_own_block() {
    // We authored the block ourselves (we proposed on a QC for a block we never received).
    let (name, _) = keys().pop().unwrap();
    missing_parent(name, 12_100, ".db_test_get_missing_parent_of_own_block").await;
}

#[test]
fn holders_are_other_signers_of_the_qc() {
    let committee = committee();
    let mut chain = chain(keys());
    let block = chain.pop().unwrap();
    let (name, _) = keys().remove(0);

    let mut expected: Vec<_> = block
        .qc
        .votes
        .iter()
        .filter(|(signer, _)| *signer != name)
        .map(|(signer, _)| committee.address(signer).unwrap())
        .collect();
    let mut got = holders(&block.qc, &committee, &name);
    expected.sort();
    got.sort();
    assert_eq!(got, expected);

    // No other signer (here: the genesis QC has none): ask everyone else.
    let all = committee.broadcast_addresses(&name).len();
    assert_eq!(holders(&QC::genesis(), &committee, &name).len(), all);
}

#[test]
fn holders_leave_out_members_that_did_not_sign() {
    // 12.9: a QC signed by all four cannot tell "its other signers" from "everyone else". With a QC signed by three
    // of the four, the fourth member is not asked: it may not hold the block at all.
    let committee = committee();
    let mut signers = keys();
    let (outsider, _) = signers.pop().unwrap();
    let name = signers[0].0;
    let mut expected: Vec<_> = signers[1..].iter().map(|(k, _)| committee.address(k).unwrap()).collect();
    let block = chain(signers).pop().unwrap();

    let mut got = holders(&block.qc, &committee, &name);
    expected.sort();
    got.sort();
    assert_eq!(got, expected);
    assert!(!got.contains(&committee.address(&outsider).unwrap()));
}

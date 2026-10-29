use crate::aggregator::{Accuser, Aggregator};
use crate::config::Committee;
use crate::consensus::{ConsensusMessage, Round};
use crate::epoch::{EpochConfig, Epochs};
use crate::error::{ConsensusError, ConsensusResult};
use crate::inclusion::Inclusion;
use crate::leader::leader;
use crate::mempool::MempoolDriver;
use crate::messages::{Accusation, Attestation, Block, OmitProof, Otx, Timeout, Vote, QC, TC};
use crate::proposer::ProposerMessage;
use crate::synchronizer::Synchronizer;
use crate::timer::Timer;
use async_recursion::async_recursion;
use bytes::Bytes;
use crypto::Hash as _;
use crypto::{Digest, PublicKey, SignatureService};
use log::{debug, error, info, warn};
use network::SimpleSender;
use std::cmp::max;
use std::collections::{HashSet, VecDeque};
use store::Store;
use tokio::sync::mpsc::{Receiver, Sender};
use std::time::Instant;

#[cfg(test)]
#[path = "tests/core_tests.rs"]
pub mod core_tests;

/// Messages of a later epoch wait here (bounded) until we enter that epoch.
const MAX_DEFERRED: usize = 2_000;

pub struct Core {
    name: PublicKey,
    epochs: Epochs,
    store: Store,
    signature_service: SignatureService,
    mempool_driver: MempoolDriver,
    synchronizer: Synchronizer,
    rx_message: Receiver<ConsensusMessage>,
    rx_loopback: Receiver<Block>,
    tx_proposer: Sender<ProposerMessage>,
    tx_commit: Sender<Block>,
    round: Round,
    last_voted_round: Round,
    last_committed_round: Round,
    high_qc: QC,
    // N6: highest round for which we hold a usable proposal (the leader's signed block and its payload).
    ready_round: Round,
    // R3: the timeout we signed for the current round, resent if the timer fires again in that round.
    last_timeout: Option<Timeout>,
    timer: Timer,
    aggregator: Aggregator,
    // G2: NR = 1 timeouts gathered into AT accusations, which go to the proposer for the ledger.
    accuser: Accuser,
    // G2: observed transactions, attestations and omission proofs; the highest QC round whose block we hold
    // and have marked certified.
    inclusion: Inclusion,
    last_certified: Round,
    network: SimpleSender,
    // Messages of later epochs, and those to handle again after entering a new epoch.
    deferred: Vec<ConsensusMessage>,
    replay: VecDeque<ConsensusMessage>,
    // Blocks of a later epoch already requested (cleared when we enter a new epoch).
    requested: HashSet<Digest>,
    // A proposal for the round held back until we have the block certified by our high QC.
    pending_proposal: Option<(Round, Option<TC>)>,
}

impl Core {
    #[allow(clippy::too_many_arguments)]
    pub fn spawn(
        name: PublicKey,
        committee: Committee,
        epoch_config: EpochConfig,
        inclusion: Inclusion,
        signature_service: SignatureService,
        store: Store,
        mempool_driver: MempoolDriver,
        synchronizer: Synchronizer,
        timeout_delay: u64,
        rx_message: Receiver<ConsensusMessage>,
        rx_loopback: Receiver<Block>,
        tx_proposer: Sender<ProposerMessage>,
        tx_commit: Sender<Block>,
    ) {
        tokio::spawn(async move {
            Self {
                name,
                epochs: Epochs::new(&committee, epoch_config),
                signature_service,
                store,
                mempool_driver,
                synchronizer,
                rx_message,
                rx_loopback,
                tx_proposer,
                tx_commit,
                round: 1,
                last_voted_round: 0,
                last_committed_round: 0,
                high_qc: QC::genesis(),
                ready_round: 0,
                last_timeout: None,
                timer: Timer::new(timeout_delay),
                aggregator: Aggregator::new(),
                accuser: Accuser::new(),
                inclusion,
                last_certified: 0,
                network: SimpleSender::new(),
                deferred: Vec::new(),
                replay: VecDeque::new(),
                requested: HashSet::new(),
                pending_proposal: None,
            }
            .run()
            .await
        });
    }

    async fn store_block(&mut self, block: &Block) {
        let key = block.digest().to_vec();
        let value = bincode::serialize(block).expect("Failed to serialize block");
        self.store.write(key, value).await;
    }

    async fn read_block(&mut self, digest: &Digest) -> ConsensusResult<Option<Block>> {
        match self.store.read(digest.to_vec()).await? {
            Some(bytes) => Ok(Some(bincode::deserialize(&bytes)?)),
            None => Ok(None),
        }
    }

    fn committee(&self) -> &Committee {
        self.epochs.current()
    }

    fn table(&self, epoch: u128) -> ConsensusResult<&Committee> {
        self.epochs.get(epoch).ok_or(ConsensusError::UnknownEpoch(epoch))
    }

    /// Certificates are verified against the weight table of their own epoch.
    fn verify_qc(&self, qc: &QC) -> ConsensusResult<()> {
        if *qc == QC::genesis() {
            return Ok(());
        }
        qc.verify(self.table(qc.epoch)?)
    }

    fn verify_tc(&self, tc: &TC) -> ConsensusResult<()> {
        tc.verify(self.table(tc.epoch)?)?;
        self.verify_qc(&tc.high_qc)
    }

    /// G2: add a verified timeout to the accuser; a new accusation goes to the proposer.
    async fn accuse(&mut self, timeout: &Timeout, committee: &Committee) {
        if let Some(accusation) = self.accuser.add(timeout, committee) {
            self.propose_accusation(accusation).await;
        }
    }

    /// G2: a verified TC whose NR = 1 reports alone exceed 2/3 is an accusation of its round.
    async fn accuse_from_tc(&mut self, tc: &TC) {
        if tc.round <= self.epochs.done() {
            return;
        }
        let accusation = match self.epochs.get(tc.epoch) {
            Some(committee) => Accusation::from_tc(tc, committee),
            None => None,
        };
        if let Some(accusation) = accusation {
            if self.accuser.note(&accusation) {
                self.propose_accusation(accusation).await;
            }
        }
    }

    /// G2: an observed transaction from a client or a node; forwarded to everyone on first receipt.
    async fn handle_otx(&mut self, otx: Otx) -> ConsensusResult<()> {
        if self.inclusion.receive(otx.clone(), Instant::now()) {
            let addresses = self
                .committee()
                .broadcast_addresses(&self.name)
                .into_iter()
                .map(|(_, x)| x)
                .collect();
            let message = bincode::serialize(&ConsensusMessage::Otx(otx))
                .expect("Failed to serialize observed transaction");
            self.network.broadcast(addresses, Bytes::from(message)).await;
        }
        Ok(())
    }

    /// G2: on entering a round, attest the observed transactions held for at least the guard.
    async fn attest_round(&mut self) {
        let otxs = self.inclusion.to_attest(Instant::now());
        if otxs.is_empty() {
            return;
        }
        let attestation = Attestation::new(
            self.round,
            self.epochs.epoch(),
            otxs,
            self.name,
            self.signature_service.clone(),
        )
        .await;
        debug!("Created {:?}", attestation);
        let addresses = self
            .committee()
            .broadcast_addresses(&self.name)
            .into_iter()
            .map(|(_, x)| x)
            .collect();
        let message = bincode::serialize(&ConsensusMessage::Attest(attestation.clone()))
            .expect("Failed to serialize attestation");
        self.network.broadcast(addresses, Bytes::from(message)).await;
        let proofs = self.inclusion.attest(attestation, self.epochs.current());
        self.propose_omissions(proofs).await;
    }

    async fn handle_attestation(&mut self, attestation: Attestation) -> ConsensusResult<()> {
        attestation.verify(self.committee())?;
        let proofs = self.inclusion.attest(attestation, self.epochs.current());
        self.propose_omissions(proofs).await;
        Ok(())
    }

    /// G2: a block we hold is certified; an omission it makes provable goes to the proposer.
    async fn certify(&mut self, block: &Block) {
        let proofs = match self.epochs.get(block.epoch) {
            Some(committee) => self.inclusion.certify(block, committee),
            None => return,
        };
        self.propose_omissions(proofs).await;
    }

    async fn propose_omissions(&mut self, proofs: Vec<OmitProof>) {
        for proof in proofs {
            debug!("Assembled {:?}", proof);
            self.tx_proposer
                .send(ProposerMessage::Omit(proof))
                .await
                .expect("Failed to send message to proposer");
        }
    }

    async fn propose_accusation(&mut self, accusation: Accusation) {
        debug!("Assembled {:?}", accusation);
        self.tx_proposer
            .send(ProposerMessage::Accuse(accusation))
            .await
            .expect("Failed to send message to proposer");
    }

    fn defer(&mut self, message: ConsensusMessage) {
        if self.deferred.len() < MAX_DEFERRED {
            self.deferred.push(message);
        }
    }

    /// Ask a node for a block we miss (its sync helper answers with a Propose message).
    async fn request_block(&mut self, digest: Digest, from: PublicKey) {
        if let Some(address) = self.committee().address(&from) {
            let message = bincode::serialize(&ConsensusMessage::SyncRequest(digest, self.name))
                .expect("Failed to serialize sync request");
            self.network.send(address, Bytes::from(message)).await;
        }
    }

    /// A QC (of an epoch we know) embedded in a message of a later epoch may be the commit proof of our
    /// terminal block: process it, which commits and enters the next epoch (H3).
    async fn catch_up(&mut self, qc: &QC) {
        if self.verify_qc(qc).is_ok() {
            self.process_qc(qc).await;
        }
    }

    /// H3: enter the next epoch once its terminal block is committed; messages of the new epoch that
    /// arrived early are handled again.
    fn enter_epoch(&mut self, terminal: &Block) {
        self.epochs.enter_next(terminal);
        info!(
            "Entered epoch {} at round {} (terminal block B{})",
            self.epochs.epoch(),
            self.round,
            terminal.round
        );
        let current = self.epochs.epoch();
        let (now, later): (Vec<_>, Vec<_>) = std::mem::take(&mut self.deferred)
            .into_iter()
            .filter(|m| epoch_of(m) >= current)
            .partition(|m| epoch_of(m) == current);
        self.replay.extend(now);
        self.deferred = later;
        self.requested.clear();
        self.accuser.cleanup(self.epochs.done() + 1);
        self.inclusion.cleanup(self.epochs.done() + 1);
    }

    fn increase_last_voted_round(&mut self, target: Round) {
        self.last_voted_round = max(self.last_voted_round, target);
    }

    async fn make_vote(&mut self, block: &Block) -> Option<Vote> {
        // H3: we sign no message of an epoch other than the current one.
        if block.epoch != self.epochs.epoch() {
            return None;
        }

        // Check if we can vote for this block.
        let safety_rule_1 = block.round > self.last_voted_round;
        let mut safety_rule_2 = block.qc.round + 1 == block.round;
        if let Some(ref tc) = block.tc {
            let mut can_extend = tc.round + 1 == block.round;
            can_extend &= block.qc.round >= *tc.high_qc_rounds().iter().max().expect("Empty TC");
            safety_rule_2 |= can_extend;
        }
        if !(safety_rule_1 && safety_rule_2) {
            return None;
        }

        // Ensure we won't vote for contradicting blocks.
        self.increase_last_voted_round(block.round);
        // TODO [issue #15]: Write to storage preferred_round and last_voted_round.
        Some(Vote::new(block, self.name, self.signature_service.clone()).await)
    }

    async fn commit(&mut self, block: Block) -> ConsensusResult<()> {
        if self.last_committed_round >= block.round {
            return Ok(());
        }

        // Ensure we commit the entire chain, oldest first. This is needed after view-change.
        let mut to_commit = VecDeque::new();
        let mut parent = block.clone();
        while self.last_committed_round + 1 < parent.round {
            let ancestor = self
                .synchronizer
                .get_parent_block(&parent)
                .await?
                .expect("We should have all the ancestors by now");
            if ancestor.round <= self.last_committed_round {
                break;
            }
            to_commit.push_front(ancestor.clone());
            parent = ancestor;
        }
        to_commit.push_back(block.clone());

        // Save the last committed block.
        self.last_committed_round = block.round;

        // Send all the newly committed blocks to the node's application layer.
        while let Some(block) = to_commit.pop_front() {
            // G2: the evidence on the ledger, up to and including the terminal block, decides the next table.
            self.epochs.record(&block);
            if !block.accusations.is_empty() {
                let keys = block.accusations.iter().map(|a| (a.epoch, a.round)).collect();
                self.tx_proposer
                    .send(ProposerMessage::Accused(keys))
                    .await
                    .expect("Failed to send message to proposer");
            }
            if !block.omissions.is_empty() {
                let keys = block.omissions.iter().map(|o| (o.epoch, o.round, o.otx.id())).collect();
                self.tx_proposer
                    .send(ProposerMessage::Omitted(keys))
                    .await
                    .expect("Failed to send message to proposer");
            }

            // H1/H3: committing the terminal block of the epoch moves us to the next epoch.
            if self.epochs.is_terminal(&block) {
                self.enter_epoch(&block);
            }

            for x in &block.otxs {
                // NOTE: This log entry is used to measure the inclusion delay of observed transactions.
                info!("Committed {} -> observed transaction {}", block, x.id());
            }
            if !block.payload.is_empty() {
                info!("Committed {}", block);

                #[cfg(feature = "benchmark")]
                for x in &block.payload {
                    // NOTE: This log entry is used to compute performance.
                    info!("Committed {} -> {:?}", block, x);
                }
            }
            debug!("Committed {:?}", block);
            if let Err(e) = self.tx_commit.send(block).await {
                warn!("Failed to send block through the commit channel: {}", e);
            }
        }
        Ok(())
    }

    fn update_high_qc(&mut self, qc: &QC) {
        if qc.round > self.high_qc.round {
            self.high_qc = qc.clone();
        }
    }

    async fn local_timeout_round(&mut self) -> ConsensusResult<()> {
        warn!("Timeout reached for round {}", self.round);

        // Increase the last voted round.
        self.increase_last_voted_round(self.round);

        // Make a timeout message. R3: sign at most one timeout per round; if the timer fires again in the
        // same round, resend the one we already signed. N6: NR when no usable proposal arrived this round.
        let epoch = self.epochs.epoch();
        let resent = matches!(&self.last_timeout, Some(t) if t.round == self.round && t.epoch == epoch);
        let timeout = match &self.last_timeout {
            Some(timeout) if resent => timeout.clone(),
            _ => {
                let timeout = Timeout::new(
                    self.high_qc.clone(),
                    self.round,
                    epoch,
                    /* nr */ self.ready_round < self.round,
                    self.name,
                    self.signature_service.clone(),
                )
                .await;
                debug!("Created {:?}", timeout);
                self.last_timeout = Some(timeout.clone());
                timeout
            }
        };

        // Reset the timer.
        self.timer.reset();

        // Broadcast the timeout message.
        debug!("Broadcasting {:?}", timeout);
        let addresses = self
            .committee()
            .broadcast_addresses(&self.name)
            .into_iter()
            .map(|(_, x)| x)
            .collect();
        let message = bincode::serialize(&ConsensusMessage::Timeout(timeout.clone()))
            .expect("Failed to serialize timeout message");
        self.network
            .broadcast(addresses, Bytes::from(message))
            .await;

        // Process our message (once: a resent timeout is already in our aggregator).
        if resent {
            return Ok(());
        }
        self.handle_timeout(&timeout).await
    }

    #[async_recursion]
    async fn handle_vote(&mut self, vote: &Vote) -> ConsensusResult<()> {
        debug!("Processing {:?}", vote);
        if vote.round < self.round {
            return Ok(());
        }

        // Ensure the vote is well formed.
        let committee = self.committee().clone();
        vote.verify(&committee)?;

        // Add the new vote to our aggregator and see if we have a quorum.
        if let Some(qc) = self.aggregator.add_vote(vote.clone(), &committee)? {
            debug!("Assembled {:?}", qc);

            // Process the QC (this may commit, and move us to the next epoch, before we propose).
            self.process_qc(&qc).await;

            // Make a new block if we are the next leader.
            if self.name == leader(self.committee(), self.round) {
                self.propose(None).await;
            }
        }
        Ok(())
    }

    async fn handle_timeout(&mut self, timeout: &Timeout) -> ConsensusResult<()> {
        debug!("Processing {:?}", timeout);
        if timeout.round < self.round {
            // G2: a late NR = 1 timeout still counts towards an accusation of its round.
            if timeout.nr && timeout.round > self.epochs.done() {
                let committee = self.committee().clone();
                timeout.verify(&committee)?;
                self.accuse(timeout, &committee).await;
            }
            return Ok(());
        }

        // Ensure the timeout is well formed.
        let committee = self.committee().clone();
        timeout.verify(&committee)?;
        self.verify_qc(&timeout.high_qc)?;
        self.accuse(timeout, &committee).await;

        // Process the QC embedded in the timeout.
        self.process_qc(&timeout.high_qc).await;
        if timeout.epoch != self.epochs.epoch() {
            return Ok(()); // the QC moved us to the next epoch
        }

        // Add the new vote to our aggregator and see if we have a quorum.
        if let Some(tc) = self.aggregator.add_timeout(timeout.clone(), &committee)? {
            debug!("Assembled {:?}", tc);

            // Try to advance the round.
            self.advance_round(tc.round).await;

            // Broadcast the TC.
            debug!("Broadcasting {:?}", tc);
            let addresses = self
                .committee()
                .broadcast_addresses(&self.name)
                .into_iter()
                .map(|(_, x)| x)
                .collect();
            let message = bincode::serialize(&ConsensusMessage::TC(tc.clone()))
                .expect("Failed to serialize timeout certificate");
            self.network
                .broadcast(addresses, Bytes::from(message))
                .await;

            // Make a new block if we are the next leader.
            if self.name == leader(self.committee(), self.round) {
                self.propose(Some(tc)).await;
            }
        }
        Ok(())
    }

    #[async_recursion]
    async fn advance_round(&mut self, round: Round) {
        if round < self.round {
            return;
        }
        // Reset the timer and advance round.
        self.timer.reset();
        self.round = round + 1;
        debug!("Moved to round {}", self.round);

        // Cleanup the vote aggregator.
        self.aggregator.cleanup(&self.round);

        self.attest_round().await;
    }

    /// Near the end of an epoch our high QC may be the commit proof of the terminal block, which we can
    /// only tell once we hold the block it certifies (votes can arrive before the block). Then propose
    /// only when that block is here, so that our block carries the right epoch; ask its author for it.
    async fn propose(&mut self, tc: Option<TC>) {
        let qc = self.high_qc.clone();
        let missing = matches!(self.read_block(&qc.hash).await, Ok(None));
        if self.epochs.may_end(qc.round) && missing {
            debug!("Proposal for round {} waits for {}", self.round, qc.hash);
            self.pending_proposal = Some((self.round, tc));
            if let Some(author) = self.epochs.get(qc.epoch).map(|c| leader(c, qc.round)) {
                self.request_block(qc.hash.clone(), author).await;
            }
            return;
        }
        self.generate_proposal(tc).await;
    }

    #[async_recursion]
    async fn generate_proposal(&mut self, tc: Option<TC>) {
        let committee = self.committee().clone();
        self.tx_proposer
            .send(ProposerMessage::Make {
                round: self.round,
                qc: self.high_qc.clone(),
                tc,
                committee,
                done: self.epochs.done(),
                otxs: self.inclusion.select(),
            })
            .await
            .expect("Failed to send message to proposer");
    }

    async fn cleanup_proposer(&mut self, b0: &Block, b1: &Block, block: &Block) {
        let digests = b0
            .payload
            .iter()
            .cloned()
            .chain(b1.payload.iter().cloned())
            .chain(block.payload.iter().cloned())
            .collect();
        self.tx_proposer
            .send(ProposerMessage::Cleanup(digests))
            .await
            .expect("Failed to send message to proposer");
    }

    #[async_recursion]
    async fn process_qc(&mut self, qc: &QC) {
        // G2: the block it certifies, if we hold it, before we attest in the next round.
        if qc.round > self.last_certified {
            if let Ok(Some(block)) = self.read_block(&qc.hash).await {
                self.last_certified = qc.round;
                self.certify(&block).await;
            }
        }
        self.advance_round(qc.round).await;
        self.update_high_qc(qc);
        if let Err(e) = self.try_commit_via_qc(qc).await {
            warn!("{}", e);
        }
    }

    /// Commit as soon as we hold a commit proof, a QC for b1 whose parent b0 is from the round just
    /// before (2-chain), rather than only when the next block is processed: a leader that assembles the
    /// commit proof of the terminal block then enters the next epoch before it proposes (H3).
    async fn try_commit_via_qc(&mut self, qc: &QC) -> ConsensusResult<()> {
        if qc.round <= self.last_committed_round + 1 {
            return Ok(());
        }
        let b1 = match self.read_block(&qc.hash).await? {
            Some(b1) if b1.qc != QC::genesis() => b1,
            _ => return Ok(()),
        };
        if let Some(b0) = self.read_block(&b1.qc.hash).await? {
            if b0.round + 1 == b1.round {
                self.mempool_driver.cleanup(b0.round).await;
                self.commit(b0).await?;
            }
        }
        Ok(())
    }

    #[async_recursion]
    async fn process_block(&mut self, block: &Block) -> ConsensusResult<()> {
        debug!("Processing {:?}", block);

        // We only get here once the block's payload is available (N6: the proposal is usable).
        self.ready_round = max(self.ready_round, block.round);

        // Let's see if we have the last three ancestors of the block, that is:
        //      b0 <- |qc0; b1| <- |qc1; block|
        // If we don't, the synchronizer asks for them to other nodes. It will
        // then ensure we process both ancestors in the correct order, and
        // finally make us resume processing this block.
        let (b0, b1) = match self.synchronizer.get_ancestors(block).await? {
            Some(ancestors) => ancestors,
            None => {
                debug!("Processing of {} suspended: missing parent", block.digest());
                return Ok(());
            }
        };

        // Store the block only if we have already processed all its ancestors.
        self.store_block(block).await;

        // G2: the block's QC certifies its parent.
        self.certify(&b1).await;

        // A block fetched by synchronization may complete the commit proof we already hold (for instance
        // the child of the terminal block when we catch up with a later epoch).
        let high_qc = self.high_qc.clone();
        if let Err(e) = self.try_commit_via_qc(&high_qc).await {
            warn!("{}", e);
        }

        // The block our held-back proposal was waiting for (we may have entered the next epoch meanwhile).
        if let Some((round, _)) = self.pending_proposal {
            if round != self.round {
                self.pending_proposal = None;
            } else if block.digest() == high_qc.hash {
                let (_, tc) = self.pending_proposal.take().unwrap();
                self.generate_proposal(tc).await;
            }
        }

        self.cleanup_proposer(&b0, &b1, block).await;

        // Check if we can commit the head of the 2-chain.
        // Note that we commit blocks only if we have all its ancestors.
        if b0.round + 1 == b1.round {
            self.mempool_driver.cleanup(b0.round).await;
            self.commit(b0).await?;
        }

        // Ensure the block's round is as expected.
        // This check is important: it prevents bad leaders from producing blocks
        // far in the future that may cause overflow on the round number.
        if block.round != self.round {
            return Ok(());
        }

        // See if we can vote for this block.
        if let Some(vote) = self.make_vote(block).await {
            debug!("Created {:?}", vote);
            let next_leader = leader(self.committee(), self.round + 1);
            if next_leader == self.name {
                self.handle_vote(&vote).await?;
            } else {
                debug!("Sending {:?} to {}", vote, next_leader);
                let address = self
                    .committee()
                    .address(&next_leader)
                    .expect("The next leader is not in the committee");
                let message = bincode::serialize(&ConsensusMessage::Vote(vote))
                    .expect("Failed to serialize vote");
                self.network.send(address, Bytes::from(message)).await;
            }
        }
        Ok(())
    }

    async fn handle_proposal(&mut self, block: &Block) -> ConsensusResult<()> {
        let digest = block.digest();

        // A block of a later epoch: its QC may be the commit proof of our terminal block (H3). Otherwise
        // keep it until we get there, and fetch its parent.
        if block.epoch > self.epochs.epoch() {
            self.catch_up(&block.qc).await;
            if block.epoch > self.epochs.epoch() {
                self.defer(ConsensusMessage::Propose(block.clone()));
                self.request_block(block.qc.hash.clone(), block.author).await;
                return Ok(());
            }
        }

        // A block of an epoch whose table we no longer keep is too old to matter.
        if self.epochs.get(block.epoch).is_none() {
            debug!("Dropping {} of old epoch {}", block, block.epoch);
            return Ok(());
        }

        // Ensure the block proposer is the right leader for the round (in the table of its epoch).
        let committee = self.table(block.epoch)?;
        ensure!(
            block.author == leader(committee, block.round),
            ConsensusError::WrongLeader {
                digest,
                leader: block.author,
                round: block.round
            }
        );

        // Check the block is correctly formed, and its certificates against the tables of their epochs.
        block.verify(committee)?;
        self.verify_qc(&block.qc)?;
        if let Some(ref tc) = block.tc {
            self.verify_tc(tc)?;
        }
        for accusation in &block.accusations {
            accusation.verify(self.table(accusation.epoch)?)?;
        }
        for omission in &block.omissions {
            omission.verify(self.table(omission.epoch)?)?;
        }

        // Process the QC. This may allow us to advance round.
        self.process_qc(&block.qc).await;

        // Process the TC (if any). This may also allow us to advance round. R6: adopt the QC it carries.
        if let Some(ref tc) = block.tc {
            self.accuse_from_tc(tc).await;
            self.process_qc(&tc.high_qc).await;
            self.advance_round(tc.round).await;
        }

        // Let's see if we have the block's data. If we don't, the mempool
        // will get it and then make us resume processing this block.
        if !self.mempool_driver.verify(block.clone()).await? {
            debug!("Processing of {} suspended: missing payload", digest);
            return Ok(());
        }

        // All check pass, we can process this block.
        self.process_block(block).await
    }

    async fn handle_tc(&mut self, tc: TC) -> ConsensusResult<()> {
        self.verify_tc(&tc)?;
        self.accuse_from_tc(&tc).await;
        if tc.round < self.round {
            return Ok(());
        }
        self.process_qc(&tc.high_qc).await;
        self.advance_round(tc.round).await;
        if self.name == leader(self.committee(), self.round) {
            self.propose(Some(tc)).await;
        }
        Ok(())
    }

    /// Votes, timeouts and TCs of the current epoch are handled; those of a later epoch wait (their QC is
    /// processed first, it may move us there); those of an older epoch are dropped (H3).
    async fn handle_message(&mut self, message: ConsensusMessage) -> ConsensusResult<()> {
        // Observed transactions carry no epoch.
        let message = match message {
            ConsensusMessage::Otx(otx) => return self.handle_otx(otx).await,
            message => message,
        };
        let epoch = epoch_of(&message);
        if epoch > self.epochs.epoch() {
            match &message {
                ConsensusMessage::Timeout(timeout) => self.catch_up(&timeout.high_qc.clone()).await,
                ConsensusMessage::TC(tc) => self.catch_up(&tc.high_qc.clone()).await,
                _ => (),
            }
        }
        match message {
            ConsensusMessage::Propose(block) => self.handle_proposal(&block).await,
            m if epoch > self.epochs.epoch() => {
                // Votes of the next epoch can reach us before the block they vote for (which carries the
                // commit proof that moves us there), and that block may be lost: ask the voter for it.
                if let ConsensusMessage::Vote(vote) = &m {
                    if self.requested.insert(vote.hash.clone()) {
                        self.request_block(vote.hash.clone(), vote.author).await;
                    }
                }
                self.defer(m);
                Ok(())
            }
            _ if epoch < self.epochs.epoch() => Ok(()),
            ConsensusMessage::Vote(vote) => self.handle_vote(&vote).await,
            ConsensusMessage::Timeout(timeout) => self.handle_timeout(&timeout).await,
            ConsensusMessage::TC(tc) => self.handle_tc(tc).await,
            ConsensusMessage::Attest(attestation) => self.handle_attestation(attestation).await,
            _ => panic!("Unexpected protocol message"),
        }
    }

    fn log_result(result: ConsensusResult<()>) {
        match result {
            Ok(()) => (),
            Err(ConsensusError::StoreError(e)) => error!("{}", e),
            Err(ConsensusError::SerializationError(e)) => error!("Store corrupted. {}", e),
            Err(e) => warn!("{}", e),
        }
    }

    pub async fn run(&mut self) {
        // Upon booting, generate the very first block (if we are the leader).
        // Also, schedule a timer in case we don't hear from the leader.
        self.timer.reset();
        if self.name == leader(self.committee(), self.round) {
            self.generate_proposal(None).await;
        }

        // This is the main loop: it processes incoming blocks and votes,
        // and receive timeout notifications from our Timeout Manager.
        loop {
            let result = tokio::select! {
                Some(message) = self.rx_message.recv() => self.handle_message(message).await,
                Some(block) = self.rx_loopback.recv() => self.process_block(&block).await,
                () = &mut self.timer => self.local_timeout_round().await,
            };
            Self::log_result(result);

            // Messages of an epoch we just entered.
            while let Some(message) = self.replay.pop_front() {
                let result = self.handle_message(message).await;
                Self::log_result(result);
            }
        }
    }
}

fn epoch_of(message: &ConsensusMessage) -> u128 {
    match message {
        ConsensusMessage::Propose(block) => block.epoch,
        ConsensusMessage::Vote(vote) => vote.epoch,
        ConsensusMessage::Timeout(timeout) => timeout.epoch,
        ConsensusMessage::TC(tc) => tc.epoch,
        ConsensusMessage::Attest(attestation) => attestation.epoch,
        ConsensusMessage::SyncRequest(..) | ConsensusMessage::Otx(..) => 0,
    }
}

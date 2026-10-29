use crate::config::{Committee, EpochNumber, Stake};
use crate::consensus::Round;
use crate::error::{ConsensusError, ConsensusResult};
use crypto::{Digest, Hash, PublicKey, Signature, SignatureService};
use ed25519_dalek::Digest as _;
use ed25519_dalek::Sha512;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::convert::TryInto;
use std::fmt;

#[cfg(test)]
#[path = "tests/messages_tests.rs"]
pub mod messages_tests;

#[derive(Serialize, Deserialize, Default, Clone)]
pub struct Block {
    pub qc: QC,
    pub tc: Option<TC>,
    pub author: PublicKey,
    pub round: Round,
    pub epoch: EpochNumber,
    pub payload: Vec<Digest>,
    pub signature: Signature,
}

impl Block {
    #[allow(clippy::too_many_arguments)]
    pub async fn new(
        qc: QC,
        tc: Option<TC>,
        author: PublicKey,
        round: Round,
        epoch: EpochNumber,
        payload: Vec<Digest>,
        mut signature_service: SignatureService,
    ) -> Self {
        let block = Self {
            qc,
            tc,
            author,
            round,
            epoch,
            payload,
            signature: Signature::default(),
        };
        let signature = signature_service.request_signature(block.digest()).await;
        Self { signature, ..block }
    }

    pub fn genesis() -> Self {
        Block::default()
    }

    pub fn parent(&self) -> &Digest {
        &self.qc.hash
    }

    pub fn verify(&self, committee: &Committee) -> ConsensusResult<()> {
        // Ensure the authority has voting rights.
        let voting_rights = committee.stake(&self.author);
        ensure!(
            voting_rights > 0,
            ConsensusError::UnknownAuthority(self.author)
        );
        check_epoch(self.epoch, committee)?;

        // Check the signature.
        self.signature.verify(&self.digest(), &self.author)?;

        // Check the embedded QC.
        if self.qc != QC::genesis() {
            self.qc.verify(committee)?;
        }

        // Check the TC embedded in the block (if any).
        if let Some(ref tc) = self.tc {
            tc.verify(committee)?;
        }
        Ok(())
    }
}

impl Hash for Block {
    /// R1: the block digest (signed by the author, voted on by everyone) commits to every field, including
    /// the epoch and the embedded TC, so that a vote for the block is also a signature on its TC.
    fn digest(&self) -> Digest {
        let mut hasher = Sha512::new();
        hasher.update(self.epoch.to_le_bytes());
        hasher.update(self.author.0);
        hasher.update(self.round.to_le_bytes());
        for x in &self.payload {
            hasher.update(x);
        }
        hasher.update(&self.qc.hash);
        hasher.update(self.qc.round.to_le_bytes());
        match &self.tc {
            None => hasher.update([0u8]),
            Some(tc) => {
                hasher.update([1u8]);
                hasher.update(tc.digest());
            }
        }
        Digest(hasher.finalize().as_slice()[..32].try_into().unwrap())
    }
}

impl fmt::Debug for Block {
    fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
        write!(
            f,
            "{}: B({}, {}, {:?}, {})",
            self.digest(),
            self.author,
            self.round,
            self.qc,
            self.payload.iter().map(|x| x.size()).sum::<usize>(),
        )
    }
}

impl fmt::Display for Block {
    fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
        write!(f, "B{}", self.round)
    }
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Vote {
    pub hash: Digest,
    pub round: Round,
    pub epoch: EpochNumber,
    pub author: PublicKey,
    pub signature: Signature,
}

impl Vote {
    pub async fn new(
        block: &Block,
        author: PublicKey,
        mut signature_service: SignatureService,
    ) -> Self {
        let vote = Self {
            hash: block.digest(),
            round: block.round,
            epoch: block.epoch,
            author,
            signature: Signature::default(),
        };
        let signature = signature_service.request_signature(vote.digest()).await;
        Self { signature, ..vote }
    }

    pub fn verify(&self, committee: &Committee) -> ConsensusResult<()> {
        // Ensure the authority has voting rights.
        ensure!(
            committee.stake(&self.author) > 0,
            ConsensusError::UnknownAuthority(self.author)
        );
        check_epoch(self.epoch, committee)?;

        // Check the signature.
        self.signature.verify(&self.digest(), &self.author)?;
        Ok(())
    }
}

impl Hash for Vote {
    fn digest(&self) -> Digest {
        vote_digest(self.epoch, &self.hash, self.round)
    }
}

/// The message signed by a vote (and checked in batch for a QC): (epoch, block digest, round).
pub fn vote_digest(epoch: EpochNumber, hash: &Digest, round: Round) -> Digest {
    let mut hasher = Sha512::new();
    hasher.update(epoch.to_le_bytes());
    hasher.update(hash);
    hasher.update(round.to_le_bytes());
    Digest(hasher.finalize().as_slice()[..32].try_into().unwrap())
}

/// The message signed by a timeout (rule R1): (epoch, round, round of the high QC, NR).
pub fn timeout_digest(epoch: EpochNumber, round: Round, high_qc_round: Round, nr: bool) -> Digest {
    let mut hasher = Sha512::new();
    hasher.update(epoch.to_le_bytes());
    hasher.update(round.to_le_bytes());
    hasher.update(high_qc_round.to_le_bytes());
    hasher.update([nr as u8]);
    Digest(hasher.finalize().as_slice()[..32].try_into().unwrap())
}

/// Messages of another epoch are rejected (rule R1, and H3 once the weight table changes per epoch).
fn check_epoch(epoch: EpochNumber, committee: &Committee) -> ConsensusResult<()> {
    ensure!(
        epoch == committee.epoch,
        ConsensusError::WrongEpoch {
            expected: committee.epoch,
            received: epoch
        }
    );
    Ok(())
}

impl fmt::Debug for Vote {
    fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
        write!(f, "V({}, {}, {}, {})", self.author, self.epoch, self.round, self.hash)
    }
}

#[derive(Clone, Serialize, Deserialize, Default)]
pub struct QC {
    pub hash: Digest,
    pub round: Round,
    pub epoch: EpochNumber,
    pub votes: Vec<(PublicKey, Signature)>,
}

impl QC {
    pub fn genesis() -> Self {
        QC::default()
    }

    pub fn timeout(&self) -> bool {
        self.hash == Digest::default() && self.round != 0
    }

    pub fn verify(&self, committee: &Committee) -> ConsensusResult<()> {
        check_epoch(self.epoch, committee)?;

        // Ensure the QC has a quorum.
        let mut weight = 0;
        let mut used = HashSet::new();
        for (name, _) in self.votes.iter() {
            ensure!(!used.contains(name), ConsensusError::AuthorityReuse(*name));
            let voting_rights = committee.stake(name);
            ensure!(voting_rights > 0, ConsensusError::UnknownAuthority(*name));
            used.insert(*name);
            weight += voting_rights;
        }
        ensure!(
            weight >= committee.quorum_threshold(),
            ConsensusError::QCRequiresQuorum
        );

        // Check the signatures.
        Signature::verify_batch(&self.digest(), &self.votes).map_err(ConsensusError::from)
    }
}

impl Hash for QC {
    fn digest(&self) -> Digest {
        vote_digest(self.epoch, &self.hash, self.round)
    }
}

impl fmt::Debug for QC {
    fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
        write!(f, "QC({}, {})", self.hash, self.round)
    }
}

impl PartialEq for QC {
    fn eq(&self, other: &Self) -> bool {
        self.hash == other.hash && self.round == other.round
    }
}

/// N6: `nr` is true when the author had no usable proposal for the round when its timer expired, that is,
/// it did not hold both the leader's signed block and the block's payload.
#[derive(Clone, Serialize, Deserialize)]
pub struct Timeout {
    pub high_qc: QC,
    pub round: Round,
    pub epoch: EpochNumber,
    pub nr: bool,
    pub author: PublicKey,
    pub signature: Signature,
}

impl Timeout {
    pub async fn new(
        high_qc: QC,
        round: Round,
        epoch: EpochNumber,
        nr: bool,
        author: PublicKey,
        mut signature_service: SignatureService,
    ) -> Self {
        let timeout = Self {
            high_qc,
            round,
            epoch,
            nr,
            author,
            signature: Signature::default(),
        };
        let signature = signature_service.request_signature(timeout.digest()).await;
        Self {
            signature,
            ..timeout
        }
    }

    pub fn verify(&self, committee: &Committee) -> ConsensusResult<()> {
        // Ensure the authority has voting rights.
        ensure!(
            committee.stake(&self.author) > 0,
            ConsensusError::UnknownAuthority(self.author)
        );
        check_epoch(self.epoch, committee)?;

        // Check the signature.
        self.signature.verify(&self.digest(), &self.author)?;

        // Check the embedded QC (R5: it is from an earlier round).
        ensure!(
            self.high_qc.round < self.round,
            ConsensusError::MalformedTimeout(self.author)
        );
        if self.high_qc != QC::genesis() {
            self.high_qc.verify(committee)?;
        }
        Ok(())
    }
}

impl Hash for Timeout {
    fn digest(&self) -> Digest {
        timeout_digest(self.epoch, self.round, self.high_qc.round, self.nr)
    }
}

impl fmt::Debug for Timeout {
    fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
        write!(
            f,
            "TV({}, {}, {}, {:?}, NR={})",
            self.author, self.epoch, self.round, self.high_qc, self.nr as u8
        )
    }
}

/// R2: the TC keeps, for every signer, the (round of its high QC, NR) it signed, and carries the highest of
/// the signers' QCs itself.
#[derive(Clone, Serialize, Deserialize)]
pub struct TC {
    pub round: Round,
    pub epoch: EpochNumber,
    pub votes: Vec<(PublicKey, Signature, Round, bool)>,
    pub high_qc: QC,
}

impl TC {
    pub fn verify(&self, committee: &Committee) -> ConsensusResult<()> {
        check_epoch(self.epoch, committee)?;

        // Ensure the TC has a quorum.
        let mut weight = 0;
        let mut used = HashSet::new();
        for (name, _, _, _) in self.votes.iter() {
            ensure!(!used.contains(name), ConsensusError::AuthorityReuse(*name));
            let voting_rights = committee.stake(name);
            ensure!(voting_rights > 0, ConsensusError::UnknownAuthority(*name));
            used.insert(*name);
            weight += voting_rights;
        }
        ensure!(
            weight >= committee.quorum_threshold(),
            ConsensusError::TCRequiresQuorum
        );

        // Check the signatures.
        for (author, signature, high_qc_round, nr) in &self.votes {
            let digest = timeout_digest(self.epoch, self.round, *high_qc_round, *nr);
            signature.verify(&digest, author)?;
        }

        // Check the embedded highest QC: it is the highest one the signers reported.
        let max_round = self.high_qc_rounds().into_iter().max().unwrap_or(0);
        ensure!(
            self.high_qc.round == max_round,
            ConsensusError::MalformedTC(self.round)
        );
        if self.high_qc != QC::genesis() {
            self.high_qc.verify(committee)?;
        }
        Ok(())
    }

    pub fn high_qc_rounds(&self) -> Vec<Round> {
        self.votes.iter().map(|(_, _, r, _)| r).cloned().collect()
    }

    /// Total stake of the signers that reported no usable proposal (N6; used for AT accusations).
    pub fn nr_weight(&self, committee: &Committee) -> Stake {
        self.votes
            .iter()
            .filter(|(_, _, _, nr)| *nr)
            .map(|(name, _, _, _)| committee.stake(name))
            .sum()
    }
}

impl Hash for TC {
    fn digest(&self) -> Digest {
        let mut hasher = Sha512::new();
        hasher.update(self.epoch.to_le_bytes());
        hasher.update(self.round.to_le_bytes());
        for (author, signature, high_qc_round, nr) in &self.votes {
            hasher.update(author.0);
            hasher.update(signature.flatten());
            hasher.update(high_qc_round.to_le_bytes());
            hasher.update([*nr as u8]);
        }
        hasher.update(self.high_qc.digest());
        Digest(hasher.finalize().as_slice()[..32].try_into().unwrap())
    }
}

impl fmt::Debug for TC {
    fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
        let nr: Vec<u8> = self.votes.iter().map(|(_, _, _, nr)| *nr as u8).collect();
        write!(
            f,
            "TC({}, {}, {:?}, NR={:?})",
            self.epoch,
            self.round,
            self.high_qc_rounds(),
            nr
        )
    }
}

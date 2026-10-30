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

/// At most this many AT accusations per block.
pub const MAX_ACCUSATIONS: usize = 32;
/// At most this many observed transactions per block; a full block is exempt from omissions.
pub const MAX_OTXS: usize = 16;
/// At most this many omission proofs per block.
pub const MAX_OMISSIONS: usize = 32;
/// At most this many pieces of G1 evidence per block.
pub const MAX_EVIDENCE: usize = 16;
/// At most this many observed transactions in one attestation. A node attests the small set of observed
/// transactions it is waiting to see included (DESIGN.md §12.4), so this bound is far above honest use; it
/// keeps a single attestation small and the omission proofs built from attestations under the network frame.
pub const MAX_ATTESTATION_OTXS: usize = 64;

#[derive(Serialize, Deserialize, Default, Clone)]
pub struct Block {
    pub qc: QC,
    pub tc: Option<TC>,
    /// G2: AT accusations of earlier rounds, put on the ledger by the proposer (DESIGN.md §12.2).
    pub accusations: Vec<Accusation>,
    /// G2: observed transactions included by the proposer, and omission proofs of earlier rounds (§12.4).
    pub otxs: Vec<Otx>,
    pub omissions: Vec<OmitProof>,
    /// G1 evidence (DESIGN.md §13).
    pub evidence: Vec<Evidence>,
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
        accusations: Vec<Accusation>,
        otxs: Vec<Otx>,
        omissions: Vec<OmitProof>,
        evidence: Vec<Evidence>,
        author: PublicKey,
        round: Round,
        epoch: EpochNumber,
        payload: Vec<Digest>,
        mut signature_service: SignatureService,
    ) -> Self {
        let block = Self {
            qc,
            tc,
            accusations,
            otxs,
            omissions,
            evidence,
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
        // Ensure the authority has voting rights, or leads the first round of the epoch for the old table
        // (it holds the commit proof of the last epoch, even if the new table suspends it).
        let voting_rights = committee.stake(&self.author);
        ensure!(
            voting_rights > 0 || committee.handover == Some((self.round, self.author)),
            ConsensusError::UnknownAuthority(self.author)
        );
        check_epoch(self.epoch, committee)?;

        // At most MAX_ACCUSATIONS accusations, of distinct earlier rounds.
        let mut rounds = HashSet::new();
        ensure!(
            self.accusations.len() <= MAX_ACCUSATIONS
                && self
                    .accusations
                    .iter()
                    .all(|a| a.round < self.round && rounds.insert((a.epoch, a.round))),
            ConsensusError::MalformedBlock(self.digest())
        );

        // At most MAX_OTXS observed transactions, no two conflicting; at most MAX_OMISSIONS omission proofs,
        // distinct and of earlier rounds.
        let mut keys = HashSet::new();
        let mut omitted = HashSet::new();
        ensure!(
            self.otxs.len() <= MAX_OTXS
                && self.otxs.iter().all(|x| keys.insert(x.key()))
                && self.omissions.len() <= MAX_OMISSIONS
                && self
                    .omissions
                    .iter()
                    .all(|o| o.round < self.round && omitted.insert((o.epoch, o.round, o.otx.id())))
                && self.evidence.len() <= MAX_EVIDENCE,
            ConsensusError::MalformedBlock(self.digest())
        );

        // Check the signature. The embedded QC and TC may belong to the previous epoch (the first block of
        // an epoch carries the commit proof of the last one): the caller verifies them, and the accusations,
        // against the table of their own epoch (Core::verify_qc, Core::verify_tc, Core::verify_accusation).
        self.signature.verify(&self.digest(), &self.author)?;
        Ok(())
    }
}

impl Hash for Block {
    /// R1: the block digest (signed by the author, voted on by everyone) commits to every field, including
    /// the epoch and the embedded TC, so that a vote for the block is also a signature on its TC.
    fn digest(&self) -> Digest {
        block_digest(
            self.epoch,
            &self.author,
            self.round,
            &self.payload,
            &self.qc.hash,
            self.qc.round,
            self.tc.as_ref(),
            self.accusations.iter().map(|a| a.digest()),
            self.otxs.iter().map(|x| x.id()),
            self.omissions.iter().map(|o| o.digest()),
            self.evidence.iter().map(|e| e.digest()),
        )
    }
}

/// What a piece of evidence keeps of the block it is about: the inputs of the block digest, with the block's
/// accusations, observed transactions, omission proofs and evidence given by their digests. It hashes to the
/// block's digest, so the culprit's vote still binds it, and it has every field the evidence checks -- but no
/// evidence of its own, so evidence never nests however often a block is reported inside another (N1).
#[derive(Serialize, Deserialize, Clone)]
pub struct BlockHeader {
    pub qc_hash: Digest,
    pub qc_round: Round,
    pub tc: Option<TC>,
    pub author: PublicKey,
    pub round: Round,
    pub epoch: EpochNumber,
    pub payload: Vec<Digest>,
    pub accusations: Vec<Digest>,
    pub otxs: Vec<Digest>,
    pub omissions: Vec<Digest>,
    pub evidence: Vec<Digest>,
}

impl Block {
    pub fn header(&self) -> BlockHeader {
        BlockHeader {
            qc_hash: self.qc.hash.clone(),
            qc_round: self.qc.round,
            tc: self.tc.clone(),
            author: self.author,
            round: self.round,
            epoch: self.epoch,
            payload: self.payload.clone(),
            accusations: self.accusations.iter().map(|a| a.digest()).collect(),
            otxs: self.otxs.iter().map(|x| x.id()).collect(),
            omissions: self.omissions.iter().map(|o| o.digest()).collect(),
            evidence: self.evidence.iter().map(|e| e.digest()).collect(),
        }
    }
}

impl Hash for BlockHeader {
    fn digest(&self) -> Digest {
        block_digest(
            self.epoch,
            &self.author,
            self.round,
            &self.payload,
            &self.qc_hash,
            self.qc_round,
            self.tc.as_ref(),
            self.accusations.iter().cloned(),
            self.otxs.iter().cloned(),
            self.omissions.iter().cloned(),
            self.evidence.iter().cloned(),
        )
    }
}

/// The block digest from its fields, the sub-messages given by their digests: Block and BlockHeader both hash
/// through here, so a block and its header always have the same digest.
#[allow(clippy::too_many_arguments)]
fn block_digest(
    epoch: EpochNumber,
    author: &PublicKey,
    round: Round,
    payload: &[Digest],
    qc_hash: &Digest,
    qc_round: Round,
    tc: Option<&TC>,
    accusations: impl ExactSizeIterator<Item = Digest>,
    otxs: impl ExactSizeIterator<Item = Digest>,
    omissions: impl ExactSizeIterator<Item = Digest>,
    evidence: impl ExactSizeIterator<Item = Digest>,
) -> Digest {
    fn list(hasher: &mut Sha512, digests: impl ExactSizeIterator<Item = Digest>) {
        hasher.update((digests.len() as u64).to_le_bytes());
        for digest in digests {
            hasher.update(digest);
        }
    }
    let mut hasher = Sha512::new();
    hasher.update(epoch.to_le_bytes());
    hasher.update(author.0);
    hasher.update(round.to_le_bytes());
    for x in payload {
        hasher.update(x);
    }
    hasher.update(qc_hash);
    hasher.update(qc_round.to_le_bytes());
    match tc {
        None => hasher.update([0u8]),
        Some(tc) => {
            hasher.update([1u8]);
            hasher.update(tc.digest());
        }
    }
    list(&mut hasher, accusations);
    list(&mut hasher, otxs);
    list(&mut hasher, omissions);
    list(&mut hasher, evidence);
    Digest(hasher.finalize().as_slice()[..32].try_into().unwrap())
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

        // R5: the embedded QC is from an earlier round. The caller verifies the QC itself against the table
        // of its own epoch.
        ensure!(
            self.high_qc.round < self.round,
            ConsensusError::MalformedTimeout(self.author)
        );
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

        // The embedded QC is the highest one the signers reported; the caller verifies the QC itself
        // against the table of its own epoch.
        let max_round = self.high_qc_rounds().into_iter().max().unwrap_or(0);
        ensure!(
            self.high_qc.round == max_round,
            ConsensusError::MalformedTC(self.round)
        );
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

/// An AT accusation (G2, DESIGN.md §12.2): timeouts of `round` that report no usable proposal (NR = 1), from
/// signers holding more than 2/3 of the weight of the table of `epoch`. Anyone holding such timeouts can
/// assemble it; the proposer puts it on the ledger.
#[derive(Clone, Serialize, Deserialize)]
pub struct Accusation {
    pub round: Round,
    pub epoch: EpochNumber,
    /// Signer, its timeout signature (on NR = 1) and the high-QC round it signed.
    pub votes: Vec<(PublicKey, Signature, Round)>,
}

impl Accusation {
    /// The NR = 1 reports of a TC, if they alone are above the threshold.
    pub fn from_tc(tc: &TC, committee: &Committee) -> Option<Self> {
        if tc.nr_weight(committee) < committee.quorum_threshold() {
            return None;
        }
        let votes = tc
            .votes
            .iter()
            .filter(|(_, _, _, nr)| *nr)
            .map(|(name, signature, high_qc_round, _)| (*name, signature.clone(), *high_qc_round))
            .collect();
        Some(Self { round: tc.round, epoch: tc.epoch, votes })
    }

    pub fn verify(&self, committee: &Committee) -> ConsensusResult<()> {
        check_epoch(self.epoch, committee)?;

        let mut weight = 0;
        let mut used = HashSet::new();
        for (name, _, _) in &self.votes {
            ensure!(used.insert(*name), ConsensusError::AuthorityReuse(*name));
            let voting_rights = committee.stake(name);
            ensure!(voting_rights > 0, ConsensusError::UnknownAuthority(*name));
            weight += voting_rights;
        }
        ensure!(
            weight >= committee.quorum_threshold(),
            ConsensusError::AccusationRequiresQuorum(self.round)
        );

        for (author, signature, high_qc_round) in &self.votes {
            let digest = timeout_digest(self.epoch, self.round, *high_qc_round, true);
            signature.verify(&digest, author)?;
        }
        Ok(())
    }
}

impl Hash for Accusation {
    fn digest(&self) -> Digest {
        let mut hasher = Sha512::new();
        hasher.update(self.epoch.to_le_bytes());
        hasher.update(self.round.to_le_bytes());
        for (author, signature, high_qc_round) in &self.votes {
            hasher.update(author.0);
            hasher.update(signature.flatten());
            hasher.update(high_qc_round.to_le_bytes());
        }
        Digest(hasher.finalize().as_slice()[..32].try_into().unwrap())
    }
}

impl fmt::Debug for Accusation {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "AT({}, {}, {} signers)", self.epoch, self.round, self.votes.len())
    }
}

/// An observed transaction (G2 inclusion attestations, DESIGN.md §12.4). Two with the same account and nonce
/// conflict: at most one of them is valid.
#[derive(Clone, Serialize, Deserialize, Debug, PartialEq, Eq)]
pub struct Otx {
    pub account: u64,
    pub nonce: u64,
    pub data: [u8; 32],
}

impl Otx {
    pub fn id(&self) -> Digest {
        let mut hasher = Sha512::new();
        hasher.update(self.account.to_le_bytes());
        hasher.update(self.nonce.to_le_bytes());
        hasher.update(self.data);
        Digest(hasher.finalize().as_slice()[..32].try_into().unwrap())
    }

    pub fn key(&self) -> (u64, u64) {
        (self.account, self.nonce)
    }
}

/// The message signed by an inclusion attestation: (tag, epoch, round, observed transactions).
pub fn attestation_digest(epoch: EpochNumber, round: Round, otxs: &[Digest]) -> Digest {
    let mut hasher = Sha512::new();
    hasher.update(b"ATT");
    hasher.update(epoch.to_le_bytes());
    hasher.update(round.to_le_bytes());
    for x in otxs {
        hasher.update(x);
    }
    Digest(hasher.finalize().as_slice()[..32].try_into().unwrap())
}

/// ATT_i(e, v, S_i): the observed transactions that i held for at least Δ_g, and saw in no certified block,
/// when it entered round v. Broadcast by i directly (not through the leader), only if the list is not empty.
#[derive(Clone, Serialize, Deserialize)]
pub struct Attestation {
    pub round: Round,
    pub epoch: EpochNumber,
    pub otxs: Vec<Digest>,
    pub author: PublicKey,
    pub signature: Signature,
}

impl Attestation {
    pub async fn new(
        round: Round,
        epoch: EpochNumber,
        otxs: Vec<Digest>,
        author: PublicKey,
        mut signature_service: SignatureService,
    ) -> Self {
        let attestation = Self {
            round,
            epoch,
            otxs,
            author,
            signature: Signature::default(),
        };
        let signature = signature_service.request_signature(attestation.digest()).await;
        Self { signature, ..attestation }
    }

    pub fn verify(&self, committee: &Committee) -> ConsensusResult<()> {
        ensure!(
            committee.stake(&self.author) > 0,
            ConsensusError::UnknownAuthority(self.author)
        );
        check_epoch(self.epoch, committee)?;
        // The list is bounded and free of duplicates: a bounded list keeps the attestation (and the omission
        // proofs built from it) small; distinct entries make "the weight listing x" the same whether counted
        // per entry (Inclusion::omissions) or per author (OmitProof::verify).
        let mut seen = HashSet::new();
        ensure!(
            self.otxs.len() <= MAX_ATTESTATION_OTXS && self.otxs.iter().all(|x| seen.insert(x)),
            ConsensusError::MalformedAttestation(self.round)
        );
        self.signature.verify(&self.digest(), &self.author)?;
        Ok(())
    }
}

impl Hash for Attestation {
    fn digest(&self) -> Digest {
        attestation_digest(self.epoch, self.round, &self.otxs)
    }
}

impl fmt::Debug for Attestation {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "ATT({}, {}, {}, {} otxs)", self.author, self.epoch, self.round, self.otxs.len())
    }
}

/// An omission proof (G2, DESIGN.md §12.4): attestations of round `round` from signers holding more than 2/3
/// of the weight of the table of `epoch` all list `otx`, and the certified block `block` of that round left
/// it out. Whether the block is on the chain, leaves `otx` out and is not exempt is checked on the ledger.
#[derive(Clone, Serialize, Deserialize)]
pub struct OmitProof {
    pub round: Round,
    pub epoch: EpochNumber,
    pub block: Digest,
    pub otx: Otx,
    /// Signer, signature and the list it signed.
    pub attestations: Vec<(PublicKey, Signature, Vec<Digest>)>,
}

impl OmitProof {
    pub fn verify(&self, committee: &Committee) -> ConsensusResult<()> {
        check_epoch(self.epoch, committee)?;

        let id = self.otx.id();
        let mut weight = 0;
        let mut used = HashSet::new();
        for (name, _, list) in &self.attestations {
            ensure!(used.insert(*name), ConsensusError::AuthorityReuse(*name));
            let voting_rights = committee.stake(name);
            ensure!(voting_rights > 0, ConsensusError::UnknownAuthority(*name));
            ensure!(list.contains(&id), ConsensusError::MalformedOmission(self.round));
            weight += voting_rights;
        }
        ensure!(
            weight >= committee.quorum_threshold(),
            ConsensusError::OmissionRequiresQuorum(self.round)
        );

        for (author, signature, list) in &self.attestations {
            signature.verify(&attestation_digest(self.epoch, self.round, list), author)?;
        }
        Ok(())
    }
}

impl Hash for OmitProof {
    fn digest(&self) -> Digest {
        let mut hasher = Sha512::new();
        hasher.update(self.epoch.to_le_bytes());
        hasher.update(self.round.to_le_bytes());
        hasher.update(&self.block);
        hasher.update(self.otx.id());
        for (author, signature, list) in &self.attestations {
            hasher.update(author.0);
            hasher.update(signature.flatten());
            hasher.update((list.len() as u64).to_le_bytes());
            for x in list {
                hasher.update(x);
            }
        }
        Digest(hasher.finalize().as_slice()[..32].try_into().unwrap())
    }
}

impl fmt::Debug for OmitProof {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "OMIT({}, {}, {}, {} signers)", self.epoch, self.round, self.otx.id(), self.attestations.len())
    }
}

/// A timeout as a piece of evidence: what its author signed (rule R1), without the QC itself.
#[derive(Clone, Serialize, Deserialize, Debug)]
pub struct SignedTimeout {
    pub author: PublicKey,
    pub signature: Signature,
    pub epoch: EpochNumber,
    pub round: Round,
    pub high_qc_round: Round,
    pub nr: bool,
}

impl SignedTimeout {
    fn verify(&self) -> ConsensusResult<()> {
        let digest = timeout_digest(self.epoch, self.round, self.high_qc_round, self.nr);
        self.signature.verify(&digest, &self.author)?;
        Ok(())
    }
}

impl From<&Timeout> for SignedTimeout {
    fn from(timeout: &Timeout) -> Self {
        Self {
            author: timeout.author,
            signature: timeout.signature.clone(),
            epoch: timeout.epoch,
            round: timeout.round,
            high_qc_round: timeout.high_qc.round,
            nr: timeout.nr,
        }
    }
}

/// G1 evidence (DESIGN.md §13.1; theory §2.3, NR extension 1.1): transferable proofs made of the culprit's own
/// signatures, which honest nodes never produce (rules R1-R6).
#[derive(Clone, Serialize, Deserialize)]
pub enum Evidence {
    /// E1: two votes of one signer for the same (epoch, round) and different blocks.
    DoubleVote(Vote, Vote),
    /// E2: a vote for a block that breaks the voting rule: its round is neither the one after its QC nor
    /// justified by its TC (structural check; the certificates' signatures are not needed). The block is given
    /// by its header, which hashes to the digest the vote signs.
    InvalidBlock(Vote, BlockHeader),
    /// E3: a vote at round v1 for a block certifying round j, and a timeout of the same signer at a round
    /// v2 >= v1 reporting a high QC below j. The block is given by its header.
    Regression(Vote, BlockHeader, SignedTimeout),
    /// NR self-contradiction: a vote and an NR = 1 timeout of one signer for the same (epoch, round).
    NrContradiction(Vote, SignedTimeout),
}

impl Evidence {
    fn vote(&self) -> &Vote {
        match self {
            Evidence::DoubleVote(vote, _)
            | Evidence::InvalidBlock(vote, _)
            | Evidence::Regression(vote, _, _)
            | Evidence::NrContradiction(vote, _) => vote,
        }
    }

    pub fn culprit(&self) -> PublicKey {
        self.vote().author
    }

    /// The epoch the culprit signed in.
    pub fn epoch(&self) -> EpochNumber {
        self.vote().epoch
    }

    /// E1-E3 are safety evidence, the NR self-contradiction liveness evidence.
    pub fn is_safety(&self) -> bool {
        !matches!(self, Evidence::NrContradiction(..))
    }

    pub fn verify(&self) -> ConsensusResult<()> {
        let vote = self.vote();
        ensure!(self.holds(), ConsensusError::MalformedEvidence(vote.author));
        vote.signature.verify(&vote.digest(), &vote.author)?;
        match self {
            Evidence::DoubleVote(_, other) => other.signature.verify(&other.digest(), &other.author)?,
            Evidence::Regression(_, _, timeout) | Evidence::NrContradiction(_, timeout) => timeout.verify()?,
            Evidence::InvalidBlock(..) => (),
        }
        Ok(())
    }

    /// Whether the messages contradict each other as claimed (signatures aside).
    pub fn holds(&self) -> bool {
        match self {
            Evidence::DoubleVote(a, b) => {
                a.author == b.author && a.epoch == b.epoch && a.round == b.round && a.hash != b.hash
            }
            Evidence::InvalidBlock(vote, block) => {
                let adjacent = block.qc_round + 1 == block.round;
                let justified = block.tc.as_ref().map_or(false, |tc| {
                    tc.round + 1 == block.round
                        && block.qc_round >= tc.high_qc_rounds().into_iter().max().unwrap_or(0)
                });
                vote.hash == block.digest()
                    && vote.round == block.round
                    && vote.epoch == block.epoch
                    && (block.qc_round >= block.round || !(adjacent || justified))
            }
            Evidence::Regression(vote, block, timeout) => {
                vote.hash == block.digest()
                    && vote.round == block.round
                    && timeout.author == vote.author
                    && timeout.epoch == vote.epoch
                    && timeout.round >= vote.round
                    && timeout.high_qc_round < block.qc_round
            }
            Evidence::NrContradiction(vote, timeout) => {
                timeout.author == vote.author
                    && timeout.epoch == vote.epoch
                    && timeout.round == vote.round
                    && timeout.nr
            }
        }
    }
}

impl Hash for Evidence {
    fn digest(&self) -> Digest {
        let mut hasher = Sha512::new();
        let vote = self.vote();
        hasher.update(vote.author.0);
        hasher.update(vote.signature.flatten());
        hasher.update(vote.digest());
        match self {
            Evidence::DoubleVote(_, other) => {
                hasher.update([1u8]);
                hasher.update(other.signature.flatten());
                hasher.update(other.digest());
            }
            Evidence::InvalidBlock(_, block) => {
                hasher.update([2u8]);
                hasher.update(block.digest());
            }
            Evidence::Regression(_, block, timeout) => {
                hasher.update([3u8]);
                hasher.update(block.digest());
                hasher.update(timeout.signature.flatten());
                hasher.update(timeout_digest(timeout.epoch, timeout.round, timeout.high_qc_round, timeout.nr));
            }
            Evidence::NrContradiction(_, timeout) => {
                hasher.update([4u8]);
                hasher.update(timeout.signature.flatten());
                hasher.update(timeout_digest(timeout.epoch, timeout.round, timeout.high_qc_round, timeout.nr));
            }
        }
        Digest(hasher.finalize().as_slice()[..32].try_into().unwrap())
    }
}

impl fmt::Debug for Evidence {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        let what = match self {
            Evidence::DoubleVote(..) => "E1",
            Evidence::InvalidBlock(..) => "E2",
            Evidence::Regression(..) => "E3",
            Evidence::NrContradiction(..) => "NR",
        };
        write!(f, "{}({}, {}, {})", what, self.culprit(), self.epoch(), self.vote().round)
    }
}

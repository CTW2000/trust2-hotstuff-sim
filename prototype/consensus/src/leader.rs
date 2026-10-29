use crate::config::Committee;
use crate::consensus::Round;
use crypto::PublicKey;

pub type LeaderElector = RRLeaderElector;

/// Round robin over the members with weight in the given table that may lead (members suspended or evicted
/// in an epoch have no weight in its table; members excluded by the G2 leader rule still vote but do not
/// lead).
pub fn leader(committee: &Committee, round: Round) -> PublicKey {
    if let Some((first, leader)) = committee.handover {
        if round == first {
            return leader;
        }
    }
    let mut keys: Vec<_> = committee
        .authorities
        .iter()
        .filter(|(_, a)| a.stake > 0 && a.leader)
        .map(|(name, _)| *name)
        .collect();
    keys.sort();
    keys[round as usize % keys.len()]
}

pub struct RRLeaderElector {
    committee: Committee,
}

impl RRLeaderElector {
    pub fn new(committee: Committee) -> Self {
        Self { committee }
    }

    pub fn get_leader(&self, round: Round) -> PublicKey {
        leader(&self.committee, round)
    }
}

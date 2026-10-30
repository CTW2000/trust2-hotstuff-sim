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
    // If the leader rule has barred everyone (G1 suspensions plus G2 exclusions covering all of the weight),
    // fall back to the full membership so the round still gets a deterministic leader, rather than dividing by
    // zero and halting every node at once (and again on every replay of the same ledger).
    if keys.is_empty() {
        keys = committee.authorities.keys().copied().collect();
    }
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

#[cfg(test)]
mod leader_tests {
    use super::*;
    use crate::common::committee;
    use std::collections::HashSet;

    #[test]
    fn falls_back_when_all_members_are_barred() {
        // 6.1: if the leader rule bars every member (all weight suspended or excluded), leader() still returns
        // a deterministic member instead of dividing by zero and halting every node at once.
        let mut committee = committee();
        for authority in committee.authorities.values_mut() {
            authority.stake = 0;
        }
        let members: HashSet<_> = committee.authorities.keys().copied().collect();
        for round in [0u64, 1, 7, 42] {
            let chosen = leader(&committee, round);
            assert!(members.contains(&chosen));
            assert_eq!(chosen, leader(&committee, round)); // deterministic across nodes
        }
    }
}

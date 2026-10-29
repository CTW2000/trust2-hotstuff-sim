use super::*;

const JSON: &str = r#"{
    "addresses": {"127.0.0.1:9000": 0, "127.0.0.1:9001": 1, "127.0.0.1:9004": 1},
    "base_ms": [[0.0, 50.0], [50.0, 0.0]],
    "jitter_ms": 10.0,
    "bandwidth_mbps": 1000.0
}"#;

#[test]
fn delay_follows_the_table() {
    let delays = Delays::from_json(JSON, 0).unwrap();
    let to_1: SocketAddr = "127.0.0.1:9001".parse().unwrap();
    for _ in 0..100 {
        // 50 ms base, up to 10 ms jitter, 1,000,000 bytes at 1 Gbps = 8 ms.
        let d = delays.of(&to_1, 1_000_000).unwrap().as_secs_f64() * 1e3;
        assert!((58.0..68.0).contains(&d), "{}", d);
    }
    // Another port of the same node (its mempool, say) has the same delay; unknown addresses and ourselves none.
    assert!(delays.of(&"127.0.0.1:9004".parse().unwrap(), 0).is_some());
    assert!(delays.of(&"127.0.0.1:9000".parse().unwrap(), 0).is_none());
    assert!(delays.of(&"127.0.0.1:9999".parse().unwrap(), 0).is_none());
}

#[test]
fn late_messages_get_the_extra_delay() {
    // Only messages to the listed (consensus) addresses can be late.
    let json = JSON.replace(
        "\"bandwidth_mbps\": 1000.0",
        "\"bandwidth_mbps\": 1000.0, \"late_p\": 1.0, \"late_ms\": 5000.0, \"late_to\": [\"127.0.0.1:9001\"]",
    );
    let delays = Delays::from_json(&json, 0).unwrap();
    let d = delays.of(&"127.0.0.1:9001".parse().unwrap(), 0).unwrap().as_secs_f64() * 1e3;
    assert!((5050.0..5060.0).contains(&d), "{}", d);
    let d = delays.of(&"127.0.0.1:9004".parse().unwrap(), 0).unwrap().as_secs_f64() * 1e3;
    assert!(d < 60.0, "{}", d);
}

#[test]
fn queue_stays_in_due_order() {
    // Without a table (no environment) a message is due now; the queue keeps due order, first in first out on ties.
    let to: SocketAddr = "127.0.0.1:9001".parse().unwrap();
    assert!(due(&to, 10) <= Instant::now());
    let t = Instant::now();
    let mut queue: std::collections::VecDeque<(Instant, u8)> = std::collections::VecDeque::new();
    for (offset, tag) in [(30, 1), (10, 2), (30, 3), (20, 4)] {
        let at = t + Duration::from_millis(offset);
        let index = position(&queue, at, |(due, _)| *due);
        queue.insert(index, (at, tag));
    }
    assert_eq!(queue.iter().map(|(_, tag)| *tag).collect::<Vec<_>>(), vec![2, 4, 1, 3]);
}

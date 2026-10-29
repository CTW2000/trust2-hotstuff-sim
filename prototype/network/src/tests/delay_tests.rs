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
fn messages_of_a_link_keep_their_order() {
    // Without a table (no environment) a message is due now, but never before the one queued ahead of it.
    let to: SocketAddr = "127.0.0.1:9001".parse().unwrap();
    let later = Instant::now() + Duration::from_millis(100);
    assert_eq!(due(&to, 10, Some(later)), later);
    assert!(due(&to, 10, None) <= Instant::now());
}

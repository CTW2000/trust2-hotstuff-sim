use super::*;
use std::fs;

#[tokio::test]
async fn create_store() {
    // Create new store.
    let path = ".db_test_create_store";
    let _ = fs::remove_dir_all(path);
    let store = Store::new(path);
    assert!(store.is_ok());
}

#[tokio::test]
async fn read_write_value() {
    // Create new store.
    let path = ".db_test_read_write_value";
    let _ = fs::remove_dir_all(path);
    let mut store = Store::new(path).unwrap();

    // Write value to the store.
    let key = vec![0u8, 1u8, 2u8, 3u8];
    let value = vec![4u8, 5u8, 6u8, 7u8];
    store.write(key.clone(), value.clone()).await;

    // Read value.
    let result = store.read(key).await;
    assert!(result.is_ok());
    let read_value = result.unwrap();
    assert!(read_value.is_some());
    assert_eq!(read_value.unwrap(), value);
}

#[tokio::test]
async fn read_unknown_key() {
    // Create new store.
    let path = ".db_test_read_unknown_key";
    let _ = fs::remove_dir_all(path);
    let mut store = Store::new(path).unwrap();

    // Try to read unknown key.
    let key = vec![0u8, 1u8, 2u8, 3u8];
    let result = store.read(key).await;
    assert!(result.is_ok());
    assert!(result.unwrap().is_none());
}

#[tokio::test]
async fn read_notify() {
    // Create new store.
    let path = ".db_test_read_notify";
    let _ = fs::remove_dir_all(path);
    let mut store = Store::new(path).unwrap();

    // Try to read a kew that does not yet exist. Then write a value
    // for that key and check that notify read returns the result.
    let key = vec![0u8, 1u8, 2u8, 3u8];
    let value = vec![4u8, 5u8, 6u8, 7u8];

    // Try to read a missing value.
    let mut store_copy = store.clone();
    let key_copy = key.clone();
    let value_copy = value.clone();
    let handle = tokio::spawn(async move {
        match store_copy.notify_read(key_copy).await {
            Ok(v) => assert_eq!(v, value_copy),
            _ => assert!(false),
        }
    });

    // Write the missing value and ensure the handle terminates correctly.
    store.write(key, value).await;
    assert!(handle.await.is_ok());
}

#[tokio::test]
async fn a_synced_write_can_be_read() {
    let path = ".db_test_a_synced_write_can_be_read";
    let _ = fs::remove_dir_all(path);
    let mut store = Store::new(path).unwrap();
    store.write_sync(vec![1], vec![2]).await;
    assert_eq!(store.read(vec![1]).await.unwrap(), Some(vec![2]));
}

#[tokio::test]
async fn a_synced_write_wakes_a_waiting_reader() {
    let path = ".db_test_a_synced_write_wakes_a_waiting_reader";
    let _ = fs::remove_dir_all(path);
    let mut store = Store::new(path).unwrap();
    let mut reader = store.clone();
    let waiting = tokio::spawn(async move { reader.notify_read(vec![1]).await });
    // Let the reader's command reach the store first (an unknown key: the store answers with None at once).
    assert_eq!(store.read(vec![9]).await.unwrap(), None);
    for _ in 0..10 {
        tokio::task::yield_now().await;
    }
    store.write_sync(vec![1], vec![2]).await;
    assert_eq!(waiting.await.unwrap().unwrap(), vec![2]);
}

#[tokio::test]
async fn a_lossy_store_loses_what_was_not_synced() {
    // What the files hold while the store is open is what a loss of power would leave: the synced record is there,
    // the plain one of a lossy store is not.
    let (path, image) = (".db_test_a_lossy_store_loses", ".db_test_a_lossy_store_loses_image");
    let _ = fs::remove_dir_all(path);
    let mut store = Store::new_lossy(path).unwrap();
    store.write(b"plain".to_vec(), vec![1]).await;
    store.write_sync(b"synced".to_vec(), vec![2]).await;
    assert_eq!(store.read(b"plain".to_vec()).await.unwrap(), Some(vec![1]), "the running store has both");
    crash_image(path, image).unwrap();

    let mut after = Store::new(image).unwrap();
    assert_eq!(after.read(b"synced".to_vec()).await.unwrap(), Some(vec![2]));
    assert_eq!(after.read(b"plain".to_vec()).await.unwrap(), None);
}

#[tokio::test]
async fn an_ordinary_store_keeps_its_log_across_a_crash_of_the_process() {
    // Without the switch a plain write is in the log (not synced): the files hold it, so a crash of the process, which
    // leaves the page cache alone, does not lose it.
    let (path, image) = (".db_test_an_ordinary_store_keeps", ".db_test_an_ordinary_store_keeps_image");
    let _ = fs::remove_dir_all(path);
    let mut store = Store::new(path).unwrap();
    store.write(b"plain".to_vec(), vec![1]).await;
    assert_eq!(store.read(b"plain".to_vec()).await.unwrap(), Some(vec![1]));
    crash_image(path, image).unwrap();

    let mut after = Store::new(image).unwrap();
    assert_eq!(after.read(b"plain".to_vec()).await.unwrap(), Some(vec![1]));
}

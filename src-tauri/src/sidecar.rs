use std::future::Future;
use std::time::Duration;

use tokio::time::sleep;

// Only used by lib.rs's `#[cfg(not(debug_assertions))]` release-only sidecar path,
// so dev builds see these as unused -- silence that rather than cfg-gating them,
// since the tests below exercise them in all build modes.
#[allow(dead_code)]
#[derive(Debug, PartialEq)]
pub struct TimeoutError;

#[allow(dead_code)]
#[derive(Debug, PartialEq)]
pub enum ShutdownOutcome {
    GracefulExit,
    ForcedKill,
}

/// Poll `check` on a fixed `interval` until it returns true or `timeout` elapses.
/// The check itself is injected so this is unit-testable without a real HTTP call.
#[allow(dead_code)]
pub async fn poll_until_healthy<F, Fut>(
    check: F,
    timeout: Duration,
    interval: Duration,
) -> Result<(), TimeoutError>
where
    F: Fn() -> Fut,
    Fut: Future<Output = bool>,
{
    let deadline = tokio::time::Instant::now() + timeout;
    loop {
        if check().await {
            return Ok(());
        }
        if tokio::time::Instant::now() >= deadline {
            return Err(TimeoutError);
        }
        sleep(interval).await;
    }
}

/// Ask the sidecar to shut down gracefully (`post_shutdown`); if it doesn't confirm
/// success within `timeout`, fall back to `kill`. Both side effects are injected
/// closures so this is unit-testable without a real process or window.
#[allow(dead_code)]
pub async fn graceful_shutdown<P, Fut, K>(
    post_shutdown: P,
    kill: K,
    timeout: Duration,
) -> ShutdownOutcome
where
    P: FnOnce() -> Fut,
    Fut: Future<Output = bool>,
    K: FnOnce(),
{
    let ok = tokio::time::timeout(timeout, post_shutdown())
        .await
        .unwrap_or(false);
    if ok {
        ShutdownOutcome::GracefulExit
    } else {
        kill();
        ShutdownOutcome::ForcedKill
    }
}

/// Send `heartbeat()` on a fixed `interval`, forever. No cancellation plumbing (spec D6) --
/// callers spawn this as a background task and let it get dropped along with the whole tokio
/// runtime when the app process exits; a few heartbeats landing on an already-shutting-down
/// backend during the ~3s graceful-shutdown window are harmless no-ops.
pub async fn heartbeat_loop<F, Fut>(heartbeat: F, interval: Duration) -> !
where
    F: Fn() -> Fut,
    Fut: Future<Output = ()>,
{
    loop {
        sleep(interval).await;
        heartbeat().await;
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicU32, Ordering};
    use std::sync::Arc;

    use super::*;

    #[tokio::test]
    async fn poll_until_healthy_succeeds_after_a_few_failures() {
        let attempts = Arc::new(AtomicU32::new(0));
        let a = attempts.clone();
        let check = move || {
            let a = a.clone();
            async move {
                let n = a.fetch_add(1, Ordering::SeqCst);
                n >= 2 // succeeds on the 3rd call (n=0,1,2)
            }
        };
        let result =
            poll_until_healthy(check, Duration::from_millis(200), Duration::from_millis(1)).await;
        assert!(result.is_ok());
        assert!(attempts.load(Ordering::SeqCst) >= 3);
    }

    #[tokio::test]
    async fn poll_until_healthy_times_out_when_never_healthy() {
        let check = || async { false };
        let result =
            poll_until_healthy(check, Duration::from_millis(20), Duration::from_millis(5)).await;
        assert_eq!(result, Err(TimeoutError));
    }

    #[tokio::test]
    async fn graceful_shutdown_does_not_kill_when_post_succeeds() {
        let killed = Arc::new(AtomicU32::new(0));
        let k = killed.clone();
        let post = || async { true };
        let kill = move || {
            k.fetch_add(1, Ordering::SeqCst);
        };
        let outcome = graceful_shutdown(post, kill, Duration::from_millis(50)).await;
        assert_eq!(outcome, ShutdownOutcome::GracefulExit);
        assert_eq!(killed.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn graceful_shutdown_kills_when_post_fails() {
        let killed = Arc::new(AtomicU32::new(0));
        let k = killed.clone();
        let post = || async { false };
        let kill = move || {
            k.fetch_add(1, Ordering::SeqCst);
        };
        let outcome = graceful_shutdown(post, kill, Duration::from_millis(50)).await;
        assert_eq!(outcome, ShutdownOutcome::ForcedKill);
        assert_eq!(killed.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn heartbeat_loop_calls_heartbeat_repeatedly_on_interval() {
        let calls = Arc::new(AtomicU32::new(0));
        let c = calls.clone();
        let heartbeat = move || {
            let c = c.clone();
            async move {
                c.fetch_add(1, Ordering::SeqCst);
            }
        };
        let handle = tokio::spawn(heartbeat_loop(heartbeat, Duration::from_millis(5)));
        // Wall-clock margin: Windows timer resolution often can't deliver ~11 ticks in 55ms.
        sleep(Duration::from_millis(120)).await;
        handle.abort();
        let n = calls.load(Ordering::SeqCst);
        assert!(n >= 5, "expected several heartbeat calls in 120ms at 5ms interval, got {n}");
    }

    #[tokio::test]
    async fn heartbeat_loop_does_not_call_heartbeat_before_first_interval_elapses() {
        let calls = Arc::new(AtomicU32::new(0));
        let c = calls.clone();
        let heartbeat = move || {
            let c = c.clone();
            async move {
                c.fetch_add(1, Ordering::SeqCst);
            }
        };
        let handle = tokio::spawn(heartbeat_loop(heartbeat, Duration::from_secs(60)));
        sleep(Duration::from_millis(10)).await;
        handle.abort();
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
}

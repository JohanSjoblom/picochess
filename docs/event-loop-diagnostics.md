# Diagnosing delayed board moves

For a temporary diagnostic run, add these settings to `picochess.ini` and restart:

```ini
event-loop-diagnostics = true
log-level = debug
log-file = picochess.log
```

Reproduce the delayed move and note the move number and wall-clock time. Keep
`logs/picochess.log` and its rotated copies (`picochess.log.1`, etc.) from the
same run, including startup. Set `event-loop-diagnostics = false` and restart
after collecting the evidence; asyncio debug mode adds overhead.

Timer records identify the callback, timer instance and generation. The stages are:

- `start-dispatch`: start request to execution of the loop's task-creation callback.
- `task-start`: task creation to execution of the timer coroutine.
- `first-expiry`: total lateness relative to the original start request plus the
  configured interval. This includes both handoffs and the sleep.
- `stop-dispatch`: stop request to execution of the loop's cancellation callback.

These records use monotonic timestamps; the log prefix gives wall-clock time.
Delays of at least 0.5 seconds are warnings. Shorter handoffs appear at debug level.
The existing `event-loop timer late` record measures the sleep wakeup separately.
Asyncio's `Executing ... took ... seconds` warnings identify individual task steps
or callbacks that occupy the loop for at least 0.5 seconds. Many shorter callbacks
can still cause a queue delay without an individual slow-callback warning.

Stopping a timer invalidates its generation before the queued cancellation runs.
A stopped generation that has not entered its callback is discarded. This cannot
undo a callback that has already begun executing.

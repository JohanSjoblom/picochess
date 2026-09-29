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

Modern UCI engines with MultiPV greater than 1 parse output in batches of up to
eight lines or approximately 5 ms of work, then yield to the shared loop.
Single-PV output uses the original parser directly. When switching back to
single-PV, any queued output drains first to preserve response ordering.
No analysis lines are filtered by
depth or dropped. A single expensive line can exceed the time budget. In debug
mode, `engine output queued ... pending_bytes=...` warnings identify output that
has waited at least 0.5 seconds, with the engine/Tutor role. Slow parser task
warnings use the name `uci-input:<role>`. Yielding improves scheduling fairness;
it does not reduce the total parsing workload or guarantee that an input backlog
will disappear.

When the deep PicoTutor search is stopped, the Tutor has already taken its
evaluation snapshot. Its remaining queued `info` lines are discarded so the
`bestmove` response can complete promptly. Other engines and active searches
still receive every analysis line.

Stopping a timer invalidates its generation before the queued cancellation runs.
A stopped generation that has not entered its callback is discarded. This cannot
undo a callback that has already begun executing.

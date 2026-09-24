# Availability objective and queue load gate

The scheduled-scan path has two measurable objectives:

- At 1,000 tenants firing in one scheduling window, accepted tasks have an enqueue p99 of at most 20 ms on the supported local SQLite deployment.
- After an immediate scheduler-process restart, 100% of accepted but unfinished tasks remain recoverable.

The original in-memory APScheduler-to-runner path cannot meet the second objective: a process exit has no durable record of accepted work. `SCALE-401` therefore separates cron dispatch from execution with `DurableTaskQueue`; workers claim, retry and complete tasks independently. Claims use a configurable visibility timeout, so work held by a crashed worker is returned to the queue. The default service embeds one worker for simple deployments, while the queue contract remains process-safe.

Run the acceptance load/restart test with:

```bash
make load-test
```

The command exits non-zero when either the p99 or recovery objective is missed. `TASK_QUEUE_ENABLED=false` is a documented rollback switch to the legacy direct execution path.

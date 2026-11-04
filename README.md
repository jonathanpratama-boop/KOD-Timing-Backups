# KOD timing cloud safeguards

Private recovery copies for the 30-slot 4–9 November 2026 timing experiment. This repository does not deploy or change KOD collector code.

- `HEALTH.json`: latest server heartbeat, slot status, source and plan checks, and latest archive pointer.
- `snapshots/*.tar.gz`: immutable named recovery archives of source, plan, scheduler, receipts and original market evidence. Each contains `MANIFEST.json` with original absolute paths and SHA-256 hashes. Restore into a temporary directory first; never extract blindly over a running experiment.
- `CLOCK-CORRECTIONS.json`: separately versioned correction derived from retained raw chrony evidence. Originals remain unchanged. Legacy offset fields in the frozen collector are known to be wrong.
- `ops/`: safeguard implementation, units and tests.

The server checks every five minutes, deferring while the collector is active or within two minutes of a scheduled slot. Evidence changes and new health problems are pushed; unchanged healthy state sends a heartbeat at least hourly under normal operation. No personal key or general GitHub token is installed on the server. Its dedicated deploy key has write access only to this repository.

GitHub checks every push and independently at minute 23 each hour during 4–10 November. An assigned issue alerts the owner about failures, incomplete slots, archive verification errors, or a heartbeat older than two hours. GitHub runner scheduling and notifications can be delayed. Email depends on the owner’s settings. Repeated failures update the open issue; recovery closes it.

Collector schedule ends 9 November at 16:00 WIB. Guard checks end after 10 November (UTC); watchdog alert evaluation ends 10 November at 10:00 UTC. The annual cron expression has a year cutoff in code, so future years do not evaluate or notify. Backups remain as repository files until deleted; this is not an expiring Actions artifact. No new paid subscription was enabled; GitHub account usage limits still apply.

These snapshots protect against server loss after the last successful push. They do not cover a simultaneous GitHub/account loss or observations not yet copied. A failed safeguard can prevent fresh snapshots, which the independent heartbeat check detects after two hours plus GitHub scheduling delay. Original collector failure behavior remains unchanged: unexpected failures halt and require operator review, not automatic replay.

Rollback: disable `kod-guard.timer` and stop `kod-guard.service`; revoke this repository’s deploy key. Do not stop or change `kod-observe.timer`.

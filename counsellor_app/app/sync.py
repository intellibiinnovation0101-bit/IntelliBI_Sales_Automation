"""
The write-behind worker. It runs in a background thread and does two jobs:

  1. Drain the store's journal to Google Sheets in small batches (the counsellor
     already got an instant ack; this is the durable follow-through). Failures
     stay 'pending' and are retried on the next tick with exponential backoff,
     so a transient Sheets/API hiccup never loses a write.

  2. Periodically reconcile — re-read the sheet — to catch any edits made outside
     the app, while preserving writes that haven't synced yet.

Because the app is the single writer to the Active tab, the sheet converges to
exactly what the app has, usually within a couple of seconds.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from .config import Settings
from .store import Store


class SyncWorker:
    def __init__(self, settings: Settings, store: Store, logger=None):
        self.s = settings
        self.store = store
        self.log = logger
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._backoff = 0.0
        self._last_sync_ts = 0.0
        self._last_reconcile_ts = 0.0
        self.synced_total = 0
        self.failed_cycles = 0

    # ---- lifecycle ----
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sync-worker",
                                        daemon=True)
        self._thread.start()

    def stop(self, flush: bool = True, timeout: float = 10.0):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        if flush:
            # best-effort final drain so nothing is left un-synced on shutdown
            try:
                self._drain_once()
            except Exception:
                pass

    def _log(self, msg: str):
        if self.log:
            self.log.info("[sync] %s", msg)

    # ---- main loop ----
    def _run(self):
        while not self._stop.is_set():
            now = time.time()
            # backoff after a failure
            if self._backoff and now < self._last_sync_ts + self._backoff:
                self._sleep_tick()
                continue
            try:
                n = self._drain_once()
                if n:
                    self.synced_total += n
                    self._log(f"synced {n} write(s)")
                self._backoff = 0.0
            except Exception as e:      # noqa: BLE001
                self.failed_cycles += 1
                self._backoff = min(60.0, (self._backoff or 1.0) * 2)
                self._log(f"sync failed ({e}); backing off {self._backoff:.0f}s")
            self._last_sync_ts = time.time()

            # periodic reconcile
            if time.time() - self._last_reconcile_ts >= self.s.reconcile_seconds:
                if self.store.reconcile():
                    self._log("reconciled with sheet")
                self._last_reconcile_ts = time.time()

            self._sleep_tick()

    def _sleep_tick(self):
        self._stop.wait(self.s.sync_tick_seconds)

    def _drain_once(self) -> int:
        """Push one batch of pending writes to the sheet. Applies them one by one
        in order; the first failure stops the batch (so ordering per mobile is
        preserved) and leaves the rest pending for the next tick."""
        batch = self.store.drain_pending(self.s.sync_batch_max)
        if not batch:
            return 0
        done = []
        for seq, op in batch:
            self.store.gw.apply_save(op)   # may raise -> caught by caller
            done.append(seq)
        self.store.mark_synced(done)
        return len(done)

    # ---- introspection for /health ----
    def status(self) -> dict:
        return {
            "pending": self.store.pending_count(),
            "synced_total": self.synced_total,
            "failed_cycles": self.failed_cycles,
            "backoff_s": round(self._backoff, 1),
        }

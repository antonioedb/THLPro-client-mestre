from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable


@dataclass
class WorkerSpec:
    name: str
    target: Callable[[], None]


class WatchdogSupervisor:
    def __init__(self, logger: logging.Logger, workers: list[WorkerSpec]):
        self.logger = logger
        self.workers = workers
        self.threads: dict[str, threading.Thread] = {}
        self.stop_event = threading.Event()

    def _start_worker(self, spec: WorkerSpec) -> None:
        th = threading.Thread(target=spec.target, name=spec.name, daemon=True)
        th.start()
        self.threads[spec.name] = th
        self.logger.info("Worker iniciado: %s", spec.name)

    def start_all(self):
        for spec in self.workers:
            self._start_worker(spec)

    def stop(self):
        self.stop_event.set()

    def run_watchdog(self):
        while not self.stop_event.is_set():
            for spec in self.workers:
                th = self.threads.get(spec.name)
                if th and not th.is_alive():
                    self.logger.error("Worker %s caiu. Reiniciando automaticamente.", spec.name)
                    self._start_worker(spec)
            self.stop_event.wait(2.0)

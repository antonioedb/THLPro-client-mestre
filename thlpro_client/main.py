from __future__ import annotations


import argparse
import os
import platform
import threading
import time


from thlpro_client.api_client import APIError, THLProAPIClient
from thlpro_client.app_paths import CLIENT_MUTEX_NAME, ensure_app_dirs
from thlpro_client.capture_service import CaptureService
from thlpro_client.compat_windows import create_single_instance_lock, release_single_instance_lock
from thlpro_client.config import ConfigStore
from thlpro_client.config_poller import ConfigPollerService
from thlpro_client.dedup_cache import QuoteDeduplicator
from thlpro_client.logger import configure_logging
from thlpro_client.queue_store import OfflineQueue
from thlpro_client.rtd_client import create_rtd_client
from thlpro_client.sender_service import SenderService
from thlpro_client.supervisor import WatchdogSupervisor, WorkerSpec
from thlpro_client.tk_config_window import ConfigWindow
from thlpro_client.tray_ui import TrayApp


VERSION = "0.4.0"


def run_client(simulate_override: bool | None = None, no_gui: bool = False) -> int:
    paths = ensure_app_dirs()
    logger = configure_logging(str(paths["logs"] / "thlpro_client.log"))

    lock_obj, already_running = create_single_instance_lock(CLIENT_MUTEX_NAME)
    if already_running:
        logger.error("Já existe uma instância do THLPro Client em execução.")
        return 2

    store = ConfigStore(paths["config"])
    config = store.load()
    runtime_password = ""
    running = True
    capture_started = True

    def on_save(updated, password):
        nonlocal config, runtime_password
        config = updated
        runtime_password = password
        store.save(config)

    try:
        if (not config.email or not config.server_url) and not no_gui:
            cfg_window = ConfigWindow(config, on_save=on_save)
            cfg_window.run()

        if simulate_override is not None:
            config.simulate = simulate_override

        if not config.computer_name:
            config.computer_name = platform.node() or "COMPUTADOR"
            store.save(config)

        api = THLProAPIClient(config.server_url)

        if runtime_password:
            api.login(config.email, runtime_password)
            reg = api.register_client(config.client_name, config.computer_name, VERSION)
            store.set_api_key(config, reg["api_key"])
            logger.info("Cliente registrado com id=%s", reg["client_id"])

        api_key = store.read_api_key(config)
        if not api_key:
            raise RuntimeError("API key não encontrada. Abra o app com interface e faça login.")
        api.api_key = api_key

        cfg_payload = api.get_config()
        logger.info(
            "Configuração recebida: %s séries ativas",
            len(cfg_payload.get("active_series", [])),
        )

        rtd_mode = (
            "simulate"
            if config.simulate or os.getenv("SIMULATE", "0") == "1"
            else os.getenv("RTD_MODE", "com")
        )

        rtd = create_rtd_client(
            rtd_mode,
            logger,
            server_url=config.server_url,
            api_key=api_key,
        )

        queue = OfflineQueue(paths["queue"])
        dedup = QuoteDeduplicator(min_interval_ms=config.min_send_interval_ms)

        capture = CaptureService(
            logger=logger,
            rtd_client=rtd,
            deduplicator=dedup,
            queue_enqueue=queue.enqueue_many,
            simulation_mode=(rtd_mode == "simulate"),
        )

        sender = SenderService(
            logger=logger,
            api_client=api,
            queue=queue,
            heartbeat_seconds=config.heartbeat_seconds,
        )

        poller = ConfigPollerService(
            logger=logger,
            api_client=api,
            on_config=lambda c: capture.set_pending_config(c),
            interval_seconds=config.poll_config_seconds,
        )

        workers = [
            WorkerSpec(name="capture_worker", target=capture.run_forever),
            WorkerSpec(name="sender_worker", target=sender.run_forever),
            WorkerSpec(name="config_poller_worker", target=poller.run_forever),
        ]

        supervisor = WatchdogSupervisor(logger, workers)
        supervisor.start_all()

        watchdog_thread = threading.Thread(
            target=supervisor.run_watchdog,
            name="watchdog",
            daemon=True,
        )
        watchdog_thread.start()

        # Enfileira as séries para assinatura progressiva.
        # O capture_worker assina os lotes no mesmo thread do Excel/RTD.
        capture.set_pending_config(cfg_payload)

        # Inicia a captura imediatamente.
        capture.start_capture()

        def open_config_window():
            if no_gui:
                logger.info("UI desabilitada (modo no-gui).")
                return

            cfg_window = ConfigWindow(config, on_save=on_save)
            cfg_window.run()

        def toggle_capture():
            nonlocal capture_started
            capture_started = not capture_started

            if capture_started:
                capture.start_capture()
                logger.info("Captura iniciada pela bandeja")
            else:
                capture.stop_capture()
                logger.info("Captura pausada pela bandeja")

        def stop_everything():
            nonlocal running
            running = False
            capture.stop()
            sender.stop()
            poller.stop()
            supervisor.stop()
            logger.info("Encerrando serviços do cliente")

        if not no_gui:
            tray = TrayApp(
                logger=logger,
                on_open=open_config_window,
                on_toggle_capture=toggle_capture,
                on_exit=stop_everything,
            )

            tray_thread = threading.Thread(
                target=tray.run,
                name="tray",
                daemon=True,
            )
            tray_thread.start()

        logger.info(
            "Cliente THLPro iniciado. Modo simulação: %s",
            rtd_mode == "simulate",
        )

        oneshot_raw = os.getenv("THLPRO_ONESHOT_SECONDS")
        oneshot_seconds = (
            int(oneshot_raw)
            if oneshot_raw and oneshot_raw.isdigit()
            else 0
        )

        elapsed = 0

        while running:
            time.sleep(1)
            elapsed += 1

            if oneshot_seconds and elapsed >= oneshot_seconds:
                logger.info(
                    "Modo oneshot atingido (%ss). Encerrando.",
                    oneshot_seconds,
                )
                stop_everything()
                break

        return 0

    except (APIError, RuntimeError) as exc:
        logger.error("Falha de inicialização: %s", exc)
        return 1

    except KeyboardInterrupt:
        logger.info("Encerrando cliente por teclado")
        return 0

    finally:
        release_single_instance_lock(lock_obj)


def parse_args():
    parser = argparse.ArgumentParser(description="THLPro Client")
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Força modo simulação",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Executa sem abrir janela",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_client(
        simulate_override=True if args.simulate else None,
        no_gui=args.no_gui,
    )


if __name__ == "__main__":
    raise SystemExit(main())
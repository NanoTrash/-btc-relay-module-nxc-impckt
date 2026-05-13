"""CLI entry point and orchestrator lifecycle."""
from __future__ import annotations

import signal
import sys
import time
from pathlib import Path
from typing import Optional

import click

from btc_relay_module_nxc_impckt.config import AppConfig
from btc_relay_module_nxc_impckt.controller.ntlmrelayx_ctrl import NtlmrelayxController
from btc_relay_module_nxc_impckt.controller.nxc_ctrl import NxcController
from btc_relay_module_nxc_impckt.logger import get_logger, setup_logging
from btc_relay_module_nxc_impckt.pipeline.coerce import CoercePipeline
from btc_relay_module_nxc_impckt.pipeline.post_auth import PostAuthPipeline
from btc_relay_module_nxc_impckt.session import SessionRegistry, SessionStatus

logger = get_logger()


class Orchestrator:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.registry = SessionRegistry()
        self.ntlm = NtlmrelayxController(cfg, self.registry)
        self.coerce = CoercePipeline(cfg, self.registry)
        self.post_auth = PostAuthPipeline(cfg, self.registry)
        self._shutdown = False

    def start(self) -> None:
        setup_logging(self.cfg.log_level, self.cfg.output_jsonl)
        logger.info("=== btc-relay-module-nxc-impckt starting ===")

        # Start ntlmrelayx background container
        self.ntlm.start()
        time.sleep(2)
        if not self.ntlm.is_running():
            logger.error("ntlmrelayx failed to start; aborting")
            sys.exit(1)

        # Run coercion campaign (blocking until done)
        self.coerce.run()

        # Main loop: watch registry for relay successes and dispatch post-auth
        logger.info("Entering main watch loop")
        while not self._shutdown:
            for session in self.registry.by_status(SessionStatus.RELAY_SUCCESS):
                self.registry.transition(session.id, SessionStatus.POST_AUTH)
                self.post_auth.run_for_session(session)

            # Print periodic summary
            summary = self.registry.summary()
            if summary:
                logger.debug(f"Session summary: {summary}")
            time.sleep(2)

    def stop(self) -> None:
        self._shutdown = True
        logger.info("=== Shutting down ===")
        self.ntlm.stop()
        logger.info(f"Final session summary: {self.registry.summary()}")


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.option("-c", "--config", default="config.yaml", help="Path to YAML config")
def start(config: str) -> None:
    cfg = AppConfig.from_yaml(config)
    orch = Orchestrator(cfg)

    def _sig_handler(signum: int, _frame: Optional[object]) -> None:
        logger.info(f"Received signal {signum}")
        orch.stop()

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    try:
        orch.start()
    except Exception:
        logger.exception("Fatal error in orchestrator")
        orch.stop()
        raise click.ClickException("Orchestrator crashed")


@cli.command()
def status() -> None:
    """Quick status check of running ntlmrelayx container."""
    from btc_relay_module_nxc_impckt.utils.docker_helpers import get_client
    client = get_client()
    try:
        container = client.containers.get("btc-relay-ntlmrelayx")
        container.reload()
        click.echo(f"ntlmrelayx container status: {container.status}")
    except Exception:
        click.echo("ntlmrelayx container not found")


@cli.command()
def stop() -> None:
    """Stop running ntlmrelayx container."""
    from btc_relay_module_nxc_impckt.controller.ntlmrelayx_ctrl import CONTAINER_NAME
    from btc_relay_module_nxc_impckt.utils.docker_helpers import get_client, stop_container
    client = get_client()
    stop_container(client, CONTAINER_NAME)
    click.echo("Stopped ntlmrelayx container")


if __name__ == "__main__":
    cli()

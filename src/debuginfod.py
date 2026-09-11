"""Debuginfod service representation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import ops

from util import file_copy, run_check, run_ret

if TYPE_CHECKING:
    from ops.model import Unit

    from config import Config


basedir = Path(__file__).parent.parent
logger = logging.getLogger(__name__)


class Debuginfod:
    """Service for debuginfod."""

    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path

    def storage_attached(self, unit: Unit) -> None:
        # fresh debug symbol storage
        pass

    def storage_meta_attached(self, unit: Unit) -> None:
        # TODO: this means the meta-database must be started fresh?
        pass

    def install(self, unit: Unit) -> None:
        unit.status = ops.MaintenanceStatus("Installing debuginfod...")

        # libarchive-tools provides bsdtar for deb archive extraction
        run_check("apt-get install -y debuginfod libarchive-tools sqlite3")

        unit.status = ops.MaintenanceStatus("Setting up debuginfod...")

        changed = file_copy(
            basedir / "etc/debuginfod.service",
            self.root_path / "etc/systemd/system/debuginfod.service",
        )
        changed |= file_copy(basedir / "etc/default-debuginfod", self.root_path / "etc/default/debuginfod")
        if changed:
            run_check("systemctl daemon-reload")

        unit.status = ops.ActiveStatus("Ready")

    def configure(self, unit: Unit, config: Config) -> None:
        pass

    def restart(self, config: Config) -> None:
        run_check("systemctl enable debuginfod.service")
        run_check("systemctl restart debuginfod.service")

    def stop(self, config: Config) -> None:
        run_check("systemctl disable --now debuginfod.service")

    def is_running(self) -> bool:
        return 0 == run_ret("systemctl is-active debuginfod.service")

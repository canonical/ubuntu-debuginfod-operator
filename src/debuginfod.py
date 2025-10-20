"""Debuginfod service representation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import ops
from charmlibs import pathops

from util import file_copy, run_check, run_ret

if TYPE_CHECKING:
    from ops.model import Unit

    from config import Config


basedir = Path(__file__).parent.parent
logger = logging.getLogger(__name__)


class Debuginfod:
    """Service for debuginfod."""

    def __init__(self, root_path: pathops.LocalPath) -> None:
        self.root_path = root_path

    def storage_attached(self, unit: Unit) -> None:
        # fresh debug symbol storage
        pass

    def storage_meta_attached(self, unit: Unit) -> None:
        # TODO: this means the meta-database must be started fresh?
        pass

    def install(self, unit: Unit) -> None:
        unit.status = ops.MaintenanceStatus("Installing debuginfod...")

        run_check("apt install -y debuginfod")

        unit.status = ops.MaintenanceStatus("Setting up debuginfod...")

        file_copy(
            basedir / "etc/debuginfod.service",
            self.root_path / "etc/systemd/system/debuginfod.service",
        )
        file_copy(basedir / "etc/default-debuginfod", self.root_path / "etc/default/debuginfod")

        unit.status = ops.ActiveStatus("Ready")

    def configure(self, config: Config) -> None:
        pass

    def restart(self, config: Config) -> None:
        run_check("systemctl enable debuginfod.service")
        run_check("systemctl restart debuginfod.service")

    def stop(self, config: Config) -> None:
        run_check("systemctl disable --now debuginfod.service")

    def is_running(self) -> bool:
        return 0 == run_ret("systemctl is-active debuginfod.service")

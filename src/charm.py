#!/usr/bin/env python3
#
# Copyright 2025 Jonas Jelten <jonas.jelten@canonical.com>
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Charm for debuginfod.

Useful for distributions to provide debugging symbols for their packages
to debuggers (e.g. GDB) run by on distro users.
"""

import logging
from typing import cast

import ops

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)


class DebuginfodCharm(ops.CharmBase):
    """Charmed operator for debuginfod."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)

        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.upgrade_charm, self._on_install)
        framework.observe(self.on.update_status, self._on_update_status)

        framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_start(self, event: ops.StartEvent):
        raise NotImplementedError()
    def _on_install(self, event: ops.InstallEvent):
        raise NotImplementedError()
    def _on_update_status(self, event: ops.UpdateStatusEvent):
        self.unit.status = ops.MaintenanceStatus("TODO implementation is pending")

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        """Handle a charm configuration updatede.

        config docs: https://juju.is/docs/sdk/config
        """
        config_value = cast(str, self.model.config["config-value"]).lower()

        if config_value == "todo":
            self.unit.status = ops.ActiveStatus()
        else:
            self.unit.status = ops.BlockedStatus(f"invalid config-value: '{config_value}'")


if __name__ == "__main__":  # pragma: nocover
    ops.main(DebuginfodCharm)

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

# event order is:
# setup:
# - storage-attached
# - install
# - relation-changed
# - leader-settings/leader-elected
# - config-changed
# - start
#
# operation:
# - upgrade-charm
# - config-changed
# - start
#
# teardown:
# - relation-broken
# - storage-detached
# - stop
# - remove

from __future__ import annotations

import logging

import ops
from charmlibs import pathops

import config
from debuginfod import Debuginfod
from ubuntu_debuginfod import UbuntuDebuginfod
from util import run_check

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)


class UbuntuDebuginfodCharm(ops.CharmBase):
    """Charmed operator for debuginfod.

    Beware: This class is instanced for every call of the obseserved hooks!
    """

    _stored = ops.StoredState()

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        logger.info("creating charm instance...")

        root = pathops.LocalPath('/')

        # executed in this order after installation/upgrade
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.upgrade_charm, self._on_upgrade)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.update_status, self._on_update_status)
        framework.observe(self.on.debugsyms_storage_attached, self._on_debugsyms_storage_attached)
        framework.observe(self.on.debuginfoddb_storage_attached,
                          self._on_debuginfoddb_storage_attached)

        self._ubuntu_debuginfod = UbuntuDebuginfod(root)
        self._debuginfod = Debuginfod(root)

    def _load_cfg(self) -> config.Config:
        expected = set(config.Config.model_fields.keys())
        given = self.config.keys()

        secret_options: list[str] = []
        for cfgkey in expected:
            cfgmeta = self.meta.config.get(cfgkey)
            if cfgmeta and cfgmeta.type == 'secret':
                secret_options.append(cfgkey)

        # secret options must be defaulted to None in our config.
        expected -= set(secret_options)

        if expected - given:
            self.unit.status = ops.BlockedStatus(f"missing config settings: {expected - given}")
            raise Exception(f"not all required charm config values set: {expected=}, {given=}")

        # secrets as config parameters are only provided using load_config conveniently.
        return self.load_config(config.Config)

    def _on_debugsyms_storage_attached(self, event: ops.StorageAttachedEvent):
        self._ubuntu_debuginfod.storage_attached(self.unit)
        self._debuginfod.storage_attached(self.unit)

    def _on_debuginfoddb_storage_attached(self, event: ops.StorageAttachedEvent):
        self._debuginfod.storage_meta_attached(self.unit)

    def _on_install(self, event: ops.InstallEvent):
        self._install()

    def _on_upgrade(self, event: ops.UpgradeCharmEvent):
        self._install()
        # not sure: according to https://github.com/canonical/charm-events
        # start is issued after upgrade
        # but in my test start wasn't issued after upgrade.
        self._start()

    def _on_config_changed(self, _: ops.ConfigChangedEvent):
        cfg = self._load_cfg()
        if not cfg:
            logger.info("charm config is empty.")
            return
        logger.info("charm config changed...")

        self._ubuntu_debuginfod.configure(cfg)
        self._debuginfod.configure(cfg)
        self.unit.set_ports(8002)  # set in etc/default-debuginfod

    def _on_start(self, event: ops.StartEvent):
        self._start()

    def _on_update_status(self, event: ops.UpdateStatusEvent):
        self._check_status()

    def _install(self):
        logger.info("installing charm...")
        # ensure automatic system security upgrades
        run_check("apt install -y needrestart unattended-upgrades")

        self._ubuntu_debuginfod.install(self.unit)
        self._debuginfod.install(self.unit)

    def _start(self) -> None:
        cfg = self._load_cfg()
        logger.info("starting charm...")
        self.unit.status = ops.WaitingStatus("starting services...")
        self._ubuntu_debuginfod.restart(self.unit, cfg)
        self._debuginfod.restart(cfg)
        self.unit.status = ops.ActiveStatus()
        self._check_status()

    def _check_status(self):
        # check if debuginfod is running
        if not self._ubuntu_debuginfod.is_running():
            self.unit.status = ops.BlockedStatus("ubuntu-debuginfod not running")
            return

        if not self._debuginfod.is_running():
            self.unit.status = ops.BlockedStatus("debuginfod not running")
            return

        self.unit.status = ops.ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    ops.main(UbuntuDebuginfodCharm)

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
import os
from pathlib import Path

import ops
from charmlibs import pathops
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

import config
from debuginfod import Debuginfod
from ubuntu_debuginfod import UbuntuDebuginfod
from util import file_copy, file_link, file_remove, run_check, run_ret

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)
basedir = Path(__file__).parent.parent

# tcp port where debuginfod listens. set in etc/default-debuginfod
debuginfod_port = 8002


class UbuntuDebuginfodCharm(ops.CharmBase):
    """Charmed operator for debuginfod.

    Beware: This class is instanced for every call of the obseserved hooks!
    """

    _stored = ops.StoredState()

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        logger.info("creating charm instance...")

        # so we can test in a tmp dir.
        if raw_root := os.environ.get("JUJU_CHARM_PREFIX"):
            self._root = Path(raw_root)
        else:
            self._root = pathops.LocalPath('/')

        if http_proxy := os.environ.get("JUJU_CHARM_HTTP_PROXY"):
            os.environ["http_proxy"] = http_proxy
        if https_proxy := os.environ.get("JUJU_CHARM_HTTPS_PROXY"):
            os.environ["https_proxy"] = https_proxy

        # Initialize ingress wiring in __init__, as each Juju hook runs in a fresh process.
        ingress_port = 80 if self.config.get("use_reverse_proxy", False) else debuginfod_port
        self._ingress = IngressPerAppRequirer(
            self,
            port=ingress_port,
            strip_prefix=True,
            relation_name="debuginfod-http-ingress",
        )

        # executed in this order after installation/upgrade
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.upgrade_charm, self._on_upgrade)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.stop, self._on_stop)
        framework.observe(self.on.update_status, self._on_update_status)
        framework.observe(self.on.debugsyms_storage_attached, self._on_debugsyms_storage_attached)
        framework.observe(self.on.debuginfoddb_storage_attached,
                          self._on_debuginfoddb_storage_attached)

        # triggers when the ingress url changes
        framework.observe(self._ingress.on.ready, self._on_ingress_ready)
        framework.observe(self._ingress.on.revoked, self._on_ingress_revoked)

        self._ubuntu_debuginfod = UbuntuDebuginfod(self._root)
        self._debuginfod = Debuginfod(self._root)

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

        # ingress is initialized in __init__ from current config.
        ingress_port = 80 if cfg.use_reverse_proxy else debuginfod_port

        # Configure nginx if reverse proxy is enabled
        self._configure_nginx(cfg.use_reverse_proxy)

        # Refresh ingress requirements immediately when config changes.
        self._ingress.provide_ingress_requirements(port=ingress_port)

        self._ubuntu_debuginfod.configure(cfg)
        self._debuginfod.configure(cfg)

        # Open exactly one externally exposed port based on mode.
        self.unit.close_port("tcp", 80)
        self.unit.close_port("tcp", debuginfod_port)
        self.unit.open_port("tcp", ingress_port)
        self._update_ingress_status()

    def _on_ingress_ready(self, event: ops.RelationEvent):
        """Handle ingress becoming ready."""
        logger.info(f"Ingress ready at: {self._ingress.url}")
        self._update_ingress_status()

    def _on_ingress_revoked(self, event: ops.RelationEvent):
        """Handle ingress being revoked."""
        logger.info("Ingress revoked")
        self._update_ingress_status()

    def _update_ingress_status(self):
        """Update unit status with ingress information."""
        if self._ingress:
            logger.info(f"charm ingress url value: {self._ingress.url}")

    def _on_start(self, event: ops.StartEvent):
        self._start()

    def _on_stop(self, event: ops.StopEvent):
        self._stop()

    def _on_update_status(self, event: ops.UpdateStatusEvent):
        self._check_status()

    def _install(self):
        logger.info("installing charm...")
        # ensure automatic system security upgrades
        run_check("apt install -y needrestart unattended-upgrades")
        run_check("dpkg-reconfigure unattended-upgrades")

        # nginx will be installed/configured if needed by _configure_nginx() in config-changed
        self._ubuntu_debuginfod.install(self.unit)
        self._debuginfod.install(self.unit)

    def _configure_nginx(self, use_reverse_proxy: bool):
        """Install and configure nginx reverse proxy."""
        if not use_reverse_proxy:
            logger.info("disabling nginx reverse proxy...")
            # nginx may not be installed yet; avoid failing the hook in that case.
            run_ret("systemctl disable --now nginx")
            return

        logger.info("configuring nginx reverse proxy...")
        run_check("apt install -y nginx-light")
        changed = file_copy(
            basedir / "etc/nginx-site-debuginfod.conf",
            self._root / "etc/nginx/sites-available/debuginfod.conf",
        )
        changed |= file_link(
            Path("../sites-available/debuginfod.conf"),
            self._root / "etc/nginx/sites-enabled/debuginfod.conf",
        )
        changed |= file_remove(self._root / "etc/nginx/sites-enabled/default")

        run_check("systemctl enable --now nginx")
        if changed:
            logger.info("nginx config changed, restarting...")
            run_check("systemctl restart nginx")

    def _start(self) -> None:
        cfg = self._load_cfg()
        logger.info("starting charm...")
        self.unit.status = ops.WaitingStatus("starting services...")
        self._ubuntu_debuginfod.restart(self.unit, cfg)
        self._debuginfod.restart(cfg)
        self.unit.status = ops.ActiveStatus()
        self._check_status()

    def _stop(self) -> None:
        cfg = self._load_cfg()
        logger.info("stopping charm...")
        self.unit.status = ops.WaitingStatus("stopping services...")
        self._ubuntu_debuginfod.stop(self.unit, cfg)
        self._debuginfod.stop(cfg)
        self.unit.status = ops.BlockedStatus("service stopped")

    def _check_status(self):
        cfg = self._load_cfg()

        # check if launchpad processing is running
        if not cfg.testmode and not self._ubuntu_debuginfod.is_running():
            self.unit.status = ops.BlockedStatus("ubuntu-debuginfod not running")
            return

        if not self._debuginfod.is_running():
            self.unit.status = ops.BlockedStatus("debuginfod not running")
            return

        self.unit.status = ops.ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    ops.main(UbuntuDebuginfodCharm)

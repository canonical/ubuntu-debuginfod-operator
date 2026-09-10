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
import shutil
from pathlib import Path

import ops
from charmlibs import pathops
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

import config
from debuginfod import Debuginfod
from ubuntu_debuginfod import UbuntuDebuginfod
from util import file_copy, file_ensure_content, file_link, file_remove, run_check, run_ret

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)
basedir = Path(__file__).parent.parent

# tcp port where debuginfod listens. set in etc/default-debuginfod
debuginfod_port = 8002
package_resource_names = (
    "ubuntu-debuginfod-deb",
    "python3-ubuntu-debuginfod-deb",
)


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
        framework.observe(self.on.secret_changed, self._on_secret_changed)
        framework.observe(self.on.debugsyms_storage_attached, self._on_debugsyms_storage_attached)
        framework.observe(self.on.debuginfoddb_storage_attached,
                          self._on_debuginfoddb_storage_attached)
        framework.observe(self.on.debugdb_storage_attached,
                          self._on_debugdb_storage_attached)
        framework.observe(self.on.debugtmp_storage_attached,
                          self._on_debugtmp_storage_attached)

        # triggers when the ingress url changes
        framework.observe(self._ingress.on.ready, self._on_ingress_ready)
        framework.observe(self._ingress.on.revoked, self._on_ingress_revoked)
        # triggers when the ingress is joined
        framework.observe(
            self.on["debuginfod-http-ingress"].relation_joined,
            self._on_ingress_relation_joined
        )

        self._ubuntu_debuginfod = UbuntuDebuginfod(self._root)
        self._debuginfod = Debuginfod(self._root)

    def _load_cfg(self) -> config.Config:
        # load_config fills missing options from their pydantic defaults; only
        # block on options that have no default and aren't supplied.
        # (a charm upgrade adding a config option must not break existing
        # deployments where juju doesn't supply the new key yet.)
        return self.load_config(config.Config)

    def _on_debugsyms_storage_attached(self, event: ops.StorageAttachedEvent):
        self._ubuntu_debuginfod.storage_attached(self.unit)
        self._debuginfod.storage_attached(self.unit)

    def _on_debuginfoddb_storage_attached(self, event: ops.StorageAttachedEvent):
        self._debuginfod.storage_meta_attached(self.unit)

    def _on_debugdb_storage_attached(self, event: ops.StorageAttachedEvent):
        # storage may attach after install; move the cluster now that it exists.
        self._ubuntu_debuginfod.relocate_postgres_storage()

    def _on_debugtmp_storage_attached(self, event: ops.StorageAttachedEvent):
        # storage may attach after configure; re-apply the TMPDIR drop-ins.
        cfg = self._load_cfg()
        if self._ubuntu_debuginfod.installed():
            self._configure(cfg)

    def _on_install(self, event: ops.InstallEvent):
        self._install(self._load_cfg())

    def _on_upgrade(self, event: ops.UpgradeCharmEvent):
        cfg = self._load_cfg()
        self._install(cfg)
        self._configure(cfg)
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

        # config-changed can fire before install; the packages and their
        # systemd units don't exist yet, so configuration would fail.
        # start (emitted after install) applies the full configuration.
        if not self._ubuntu_debuginfod.installed():
            logger.info("install not finished yet, deferring configuration to start.")
            self.unit.status = ops.WaitingStatus("waiting for install")
            return

        self._configure(cfg)

    def _configure(self, cfg: config.Config) -> None:
        """Apply charm and service configuration."""

        # Configure nginx if reverse proxy is enabled
        self._configure_nginx(cfg.use_reverse_proxy)

        # Proxy drop-ins for the managed systemd units (outbound Launchpad access).
        self._configure_proxy(cfg)
        tmpdir_changed = self._configure_tmpdir()

        # Ingress is initialized in __init__ from current config.
        # Refresh ingress requirements immediately when config changes.
        ingress_port = self._setup_ingress(cfg)

        if self._needs_lp_credentials(cfg):
            self.unit.status = ops.BlockedStatus("missing config: lp_credentials secret")
            return

        # a TMPDIR drop-in change needs a worker restart to take effect.
        self._ubuntu_debuginfod.configure(
            self.unit,
            cfg,
            force_restart=tmpdir_changed,
            proxy_url=self._proxy_url(cfg),
            no_proxy=os.environ.get("JUJU_CHARM_NO_PROXY") or None,
        )
        self._debuginfod.configure(self.unit, cfg)

        # Open exactly one externally exposed port based on mode.
        self.unit.close_port("tcp", 80)
        self.unit.close_port("tcp", debuginfod_port)
        self.unit.open_port("tcp", ingress_port)
        self._update_ingress_status()
        self._check_status()

    def _on_ingress_relation_joined(self, event: ops.RelationJoinedEvent):
        """Ensure relation data is published the moment a new relation is established."""
        cfg = self._load_cfg()
        self._setup_ingress(cfg)

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

    @staticmethod
    def _needs_lp_credentials(cfg: config.Config) -> bool:
        # the service config hardcodes private PPAs, which require launchpad auth.
        return not cfg.testmode and cfg.lp_credentials is None

    def _on_start(self, event: ops.StartEvent):
        self._start()

    def _on_stop(self, event: ops.StopEvent):
        self._stop()

    def _on_update_status(self, event: ops.UpdateStatusEvent):
        self._check_status()

    def _on_secret_changed(self, event: ops.SecretChangedEvent):
        cfg = self._load_cfg()
        if cfg.lp_credentials is None or cfg.lp_credentials.id != event.secret.id:
            return
        self._configure(cfg)
        self._check_status()

    def _install(self, cfg: config.Config):
        logger.info("installing charm...")
        # ensure automatic system security upgrades
        run_check("apt-get install -y needrestart unattended-upgrades")
        run_check("dpkg-reconfigure unattended-upgrades")

        # nginx will be installed/configured if needed by _configure_nginx() in config-changed
        package_resources = None
        if cfg.package_source == "resource":
            package_resources = tuple(
                self.model.resources.fetch(resource_name)
                for resource_name in package_resource_names
            )

        self._ubuntu_debuginfod.install(self.unit, package_resources)
        self._debuginfod.install(self.unit)

    def _configure_nginx(self, use_reverse_proxy: bool):
        """Install and configure nginx reverse proxy."""
        if not self._ubuntu_debuginfod.installed():
            logger.info("install not finished yet, skipping nginx setup.")
            return

        if not use_reverse_proxy:
            logger.info("disabling nginx reverse proxy...")
            # nginx may not be installed yet; avoid failing the hook in that case.
            run_ret("systemctl disable --now nginx")
            return

        logger.info("configuring nginx reverse proxy...")
        run_check("apt-get install -y nginx-light")
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

    def _proxy_url(self, cfg: config.Config) -> str | None:
        """Resolve the effective proxy URL, or None for no proxy."""
        if cfg.proxy == "none":
            return None
        if cfg.proxy:
            return cfg.proxy
        return os.environ.get("JUJU_CHARM_HTTPS_PROXY") or os.environ.get("JUJU_CHARM_HTTP_PROXY") or None

    def _configure_proxy(self, cfg: config.Config):
        """Write/remove the proxy systemd drop-in for debuginfod.service.

        debuginfod itself doesn't go through the ubuntu-debuginfod CLI, so it
        has no config.toml to read; the drop-in is its only proxy source.
        The ubuntu-debuginfod services get their proxy from config.toml
        (rendered in _configure), which also covers manual CLI invocations.
        """
        url = self._proxy_url(cfg)
        services = ("debuginfod.service",)
        changed = False
        for service in services:
            dropin = self._root / f"etc/systemd/system/{service}.d/proxy.conf"
            if url is None:
                changed |= file_remove(dropin)
                continue
            no_proxy = os.environ.get("JUJU_CHARM_NO_PROXY", "")
            lines = [
                "[Service]",
                f'Environment="HTTP_PROXY={url}"',
                f'Environment="HTTPS_PROXY={url}"',
            ]
            if no_proxy:
                lines.append(f'Environment="NO_PROXY={no_proxy}"')
            changed |= file_ensure_content(dropin, content="\n".join(lines) + "\n")

        if changed:
            run_check("systemctl daemon-reload")

    def _configure_tmpdir(self) -> bool:
        """Write the TMPDIR drop-ins for the downloader workers and debuginfod.

        Downloads stage in tempfile.NamedTemporaryFile and source extraction
        in tempfile.TemporaryDirectory, which default to /tmp (a small tmpfs);
        multi-hundred-MB ddebs fill it and take down apt and the juju agent
        with it. Stage on the fast debugtmp volume when attached, else on the
        debugsyms volume.

        Returns whether a drop-in changed, so callers can restart the workers
        (a running process never re-reads its environment).
        """
        # staging lives at the fixed path /srv/debug-mirror/tmp: a symlink to
        # the debugtmp volume when attached (juju forbids nesting its mount
        # under the debugsyms mount), else a plain dir on the debugsyms volume.
        tmp_root = self._root / "srv/debug-mirror/tmp"
        nvme_tmp = self._root / "srv/debug-tmp"
        if os.path.ismount(nvme_tmp):
            if tmp_root.is_symlink():
                if tmp_root.resolve() != nvme_tmp:
                    tmp_root.unlink()
                    tmp_root.symlink_to(nvme_tmp)
            else:
                if tmp_root.exists():
                    shutil.rmtree(tmp_root)
                tmp_root.symlink_to(nvme_tmp)
        else:
            if tmp_root.is_symlink():
                tmp_root.unlink()
            tmp_root.mkdir(parents=True, exist_ok=True)

        download_tmpdir = tmp_root / "download"
        download_tmpdir.mkdir(parents=True, exist_ok=True)
        # mirror-owned: tempfile silently falls back to /var/tmp when its
        # TMPDIR candidate isn't writable, staging on the root disk instead.
        shutil.chown(download_tmpdir, user="mirror", group="mirror")
        # debuginfod (DynamicUser) extracts archives via TMPDIR too; it cannot
        # write the mirror-owned downloader staging dir, so it gets its own.
        # 1777: the dynamic user must create entries; the sticky bit keeps
        # workers from unlinking each other's staging. debuginfod's fdcache
        # grooms this dir itself (fdcache tmpdir min%), so no cleaner needed.
        debuginfod_tmpdir = tmp_root / "debuginfod"
        debuginfod_tmpdir.mkdir(parents=True, exist_ok=True)
        debuginfod_tmpdir.chmod(0o1777)

        # drop the tmpfiles config from earlier charm revisions;
        # systemd-tmpfiles --clean recursively walks the extraction trees
        # (openjdk, ...) and hangs for hours on slow storage, blocking apt and
        # needrestart.
        file_remove(self._root / "etc/tmpfiles.d/ubuntu-debuginfod.conf")

        changed = False
        for service in (
            "ubuntu-debuginfod-launchpad-downloader.service",
            "ubuntu-debuginfod-launchpad-downloader@.service",
        ):
            changed |= file_ensure_content(
                self._root / f"etc/systemd/system/{service}.d/tmpdir.conf",
                content=f'[Service]\nEnvironment="TMPDIR={download_tmpdir}"\n',
            )
        changed |= file_ensure_content(
            self._root / "etc/systemd/system/debuginfod.service.d/tmpdir.conf",
            content=f'[Service]\nEnvironment="TMPDIR={debuginfod_tmpdir}"\n',
        )
        if changed:
            run_check("systemctl daemon-reload")
        return changed

    def _setup_ingress(self, cfg: config.Config) -> int:
        logger.info("setting up ingress relation parameters...")
        ingress_port = 80 if cfg.use_reverse_proxy else debuginfod_port
        self._ingress.provide_ingress_requirements(port=ingress_port)
        return ingress_port

    def _start(self) -> None:
        cfg = self._load_cfg()
        logger.info("starting charm...")
        if self._needs_lp_credentials(cfg):
            self.unit.status = ops.BlockedStatus("missing config: lp_credentials secret")
            return

        self.unit.status = ops.WaitingStatus("starting services...")
        # config-changed may have been skipped before install finished;
        # apply the full configuration now. ubuntu-debuginfod.configure restarts
        # as needed; debuginfod.configure is a no-op, so start it explicitly.
        self._configure(cfg)
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

        if self._needs_lp_credentials(cfg):
            self.unit.status = ops.BlockedStatus("missing config: lp_credentials secret")
            return

        # check if launchpad processing is running
        if not cfg.testmode and not self._ubuntu_debuginfod.is_running(cfg):
            self.unit.status = ops.BlockedStatus("ubuntu-debuginfod not running")
            return

        if not self._debuginfod.is_running():
            self.unit.status = ops.BlockedStatus("debuginfod not running")
            return

        polling = "polling launchpad" if cfg.sync_launchpad else "polling disabled"
        if cfg.download:
            downloading = f"downloading with {cfg.downloader_workers} worker(s)"
        else:
            downloading = "downloading disabled"
        self.unit.status = ops.ActiveStatus(f"serving debug symbols; {polling}; {downloading}")


if __name__ == "__main__":  # pragma: nocover
    ops.main(UbuntuDebuginfodCharm)

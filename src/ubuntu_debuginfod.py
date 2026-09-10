"""Ubuntu's debuginfod service representation."""

from __future__ import annotations

import logging
import os
import pwd
import shlex
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import ops
import tomli_w

from util import file_ensure_content, file_link, file_remove, run_check, run_out, run_ret

if TYPE_CHECKING:
    from ops.model import Unit

    from config import Config


basedir = Path(__file__).parent.parent
logger = logging.getLogger(__name__)



POSTGRES_DATA_DIR = "var/lib/postgresql"
DEBUGDB_STORAGE_DIR = "srv/debug-db"

DOWNLOADER_SERVICE = "ubuntu-debuginfod-launchpad-downloader.service"
DOWNLOADER_SERVICE_TEMPLATE = "ubuntu-debuginfod-launchpad-downloader@{worker}.service"
DOWNLOADER_SERVICE_PREFIX = "ubuntu-debuginfod-launchpad-downloader@"

# private PPAs whose debug symbols are mirrored (require launchpad auth).
PPAS = (
    {"user": "ubuntu-esm", "name": "esm-infra-security", "private": True},
    {"user": "ubuntu-esm", "name": "esm-infra-updates", "private": True},
    {"user": "ubuntu-esm", "name": "esm-apps-security", "private": True},
    {"user": "ubuntu-esm", "name": "esm-apps-updates", "private": True},
    {"user": "ubuntu-advantage", "name": "realtime-updates", "private": True},
)


def _ubuntu_debuginfod_config(
    proxy_url: str | None,
    no_proxy: str | None,
    mirror_arches: list[str],
    tmpdir: str | None,
) -> str:
    """Render the upstream config.toml from a data structure.

    The proxy goes into the central config.toml so the ubuntu-debuginfod
    services and manual CLI invocations (import-current, ...) all get the
    same egress routing.
    """
    settings: dict[str, Any] = {"mirror_dir": "/srv/debug-mirror"}
    if proxy_url is not None:
        settings["proxy"] = proxy_url
    if no_proxy:
        settings["no_proxy"] = no_proxy
    if mirror_arches:
        settings["mirror_arches"] = mirror_arches
    if tmpdir is not None:
        # the cleaner prunes this staging dir (top-level entries only)
        settings["tmpdir"] = str(tmpdir)
    return tomli_w.dumps({"settings": settings, "ppas": list(PPAS)})


class UbuntuDebuginfod:
    """Service for ubuntu-debuginfod."""

    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path

    def _ensure_storage_layout(self, unit: Unit) -> None:
        """Make sure directories exist for debug symbol storage in /srv/debug-mirror."""
        storage_dirs = (
            "srv/debug-mirror/ddebs/",
            "srv/debug-mirror/ppas/",
            "srv/debug-mirror/private-ppas/",
            "srv/debug-mirror/tmpdir/",
            "srv/debug-mirror/metadata/",
        )

        for directory in storage_dirs:
            # create directories needed for debuginfod.service ro/rw namespace.
            os.makedirs(self.root_path / directory, exist_ok=True)

        # if storage changed, but we already created the user during "install"
        try:
            pwd.getpwnam("mirror")
        except KeyError:
            # mirror user not known -> ubuntu-debuginfod not yet installed, that's fine.
            # when its installed, this function is called again.
            pass
        else:
            for directory in storage_dirs:
                shutil.chown(self.root_path / directory, user="mirror", group="mirror")

    def storage_attached(self, unit: Unit) -> None:
        self._ensure_storage_layout(unit)

    def _ensure_database(self) -> None:
        role_can_login = run_out(
            "runuser -u postgres -- psql -tAc \"select rolcanlogin from pg_roles where rolname = 'mirror'\" postgres"
        ).strip()
        if not role_can_login:
            run_check("runuser -u postgres -- createuser --login mirror")
        elif role_can_login != "t":
            run_check(
                "runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c \"alter role mirror login\" postgres"
            )

        database_exists = run_out(
            "runuser -u postgres -- psql -tAc "
            "\"select 1 from pg_database where datname = 'ubuntu-debuginfod'\" postgres"
        ).strip()
        if not database_exists:
            run_check("runuser -u postgres -- createdb --owner mirror ubuntu-debuginfod")

    def relocate_postgres_storage(self) -> None:
        """Move the postgres cluster onto the debugdb storage volume.

        The job database grows with the archive backfill and must not fill the
        small root disk. /var/lib/postgresql/<version>/main becomes a symlink
        to the volume, so postgres packaging (which assumes the conventional
        data_directory path) keeps working unmodified.
        """
        storage = self.root_path / DEBUGDB_STORAGE_DIR
        if run_ret(f"findmnt --mountpoint {shlex.quote(str(storage))}") != 0:
            logger.info("debugdb storage not attached; keeping postgres on the root disk.")
            return

        src_root = self.root_path / POSTGRES_DATA_DIR
        if not src_root.is_dir():
            # postgres not installed yet; install() relocates after apt-get.
            return

        clusters = [cluster for cluster in sorted(src_root.glob("*/main")) if not cluster.is_symlink()]
        if not clusters:
            return

        was_active = run_ret("systemctl is-active postgresql.service") == 0
        if was_active:
            run_check("systemctl stop postgresql.service")

        for cluster in clusters:
            # <version>/main directly on the volume, so a future postgres major
            # upgrade creates its cluster as a sibling (pg_upgradecluster).
            dst = storage / cluster.parent.name / cluster.name
            dst.mkdir(parents=True, exist_ok=True)
            run_check(f"rsync -aHAX {shlex.quote(str(cluster))}/ {shlex.quote(str(dst))}/")
            backup = cluster.with_name(cluster.name + ".pre-relocate")
            shutil.move(cluster, backup)
            file_link(dst, cluster)
            shutil.rmtree(backup)
            # postgres refuses to start when the data dir is group/world-accessible.
            shutil.chown(dst.parent, user="postgres", group="postgres")
            shutil.chown(dst, user="postgres", group="postgres")

        if was_active:
            run_check("systemctl start postgresql.service")

    @staticmethod
    def _downloader_services(config: Config) -> set[str]:
        return {
            DOWNLOADER_SERVICE_TEMPLATE.format(worker=worker)
            for worker in range(1, config.downloader_workers + 1)
        }

    @staticmethod
    def _enabled_downloader_services() -> set[str]:
        output = run_out("systemctl show multi-user.target --property=Wants --value")
        return {
            service
            for service in output.split()
            if service.startswith(DOWNLOADER_SERVICE_PREFIX) and service.endswith(".service")
        }

    def _stop_downloader_services(self, config: Config) -> None:
        services = self._enabled_downloader_services() | self._downloader_services(config)
        for service in sorted(services):
            run_ret(f"systemctl disable --now {service}")
        run_ret(f"systemctl disable --now {DOWNLOADER_SERVICE}")

    def install(self, unit: Unit, package_resources: tuple[Path, ...] | None = None) -> None:
        if package_resources is None:
            unit.status = ops.MaintenanceStatus("Installing ubuntu-debuginfod repo...")
            run_check("add-apt-repository -y ppa:ubuntu-debuginfod-devs/ubuntu-debuginfod")

        unit.status = ops.MaintenanceStatus("Installing PostgreSQL...")
        run_check("apt-get install -y postgresql")
        self.relocate_postgres_storage()
        run_check("systemctl enable --now postgresql.service")

        unit.status = ops.MaintenanceStatus("Installing ubuntu-debuginfod...")
        # no recommends, since we don't need toolchain/build-essentials (actually just dpkg-source)
        packages = [str(path) for path in package_resources] if package_resources else ["ubuntu-debuginfod"]
        run_check(shlex.join(["apt-get", "install", "-y", "--no-install-recommends", *packages]))
        # this creates the mirror:mirror user.
        # this also installs configs for:
        # /etc/default/ubuntu-debuginfod-launchpad-downloader
        # /etc/default/ubuntu-debuginfod-launchpad-poller

        self._ensure_storage_layout(unit)
        self._ensure_database()

        unit.status = ops.ActiveStatus("Ready")

    def installed(self) -> bool:
        """Whether the ubuntu-debuginfod package (and its systemd units) exist.

        config-changed can fire before install completes; configuring then would
        fail on the not-yet-present systemd units.
        """
        return run_ret("systemctl cat ubuntu-debuginfod-launchpad-poller.service") == 0

    def configure(
        self,
        unit: Unit,
        config: Config,
        force_restart: bool = False,
        proxy_url: str | None = None,
        no_proxy: str | None = None,
    ) -> None:
        """
        ubuntu-debuginfod setup configuration.
        """
        changed = force_restart

        # Deploy the launchpad access credentials secret file.
        lp_creds_path = self.root_path / "home/mirror/.config/ubuntu-debuginfod/lp.cred"
        lp_creds_secret = config.lp_credentials
        if lp_creds_secret is None:
            logger.info("launchpad secret configuration not given.")
            changed |= file_remove(lp_creds_path)
        else:
            try:
                secrets = lp_creds_secret.get_content(refresh=True)
            except Exception:
                logger.exception("failed to read lp_credentials secret")
                raise

            try:
                lp_creds = secrets["cred"]  # secret key name as set in `juju add-secret`
            except KeyError:
                logger.error(f"lp_credentials secret has no 'cred' key, has: {sorted(secrets)}")
                raise

            changed |= file_ensure_content(
                lp_creds_path,
                content=lp_creds,
                mkdir=True,
                owner="mirror:mirror",
                mode=0o600,
            )

        changed |= file_ensure_content(
            self.root_path / "home/mirror/.config/ubuntu-debuginfod/config.toml",
            content=_ubuntu_debuginfod_config(
                proxy_url,
                no_proxy,
                config.mirror_architectures,
                tmpdir=str(self.root_path / "srv/debug-mirror/tmp/download"),
            ),
            mkdir=True,
            owner="mirror",
        )

        # The schema migration is idempotent and cheap when nothing
        # changed; run it on every configure so a broken migration fails
        # the hook instead of leaving the services to crash-loop.
        run_check(
            "runuser -u mirror -- /usr/bin/python3 -I -m ubuntu_debuginfod.cli "
            "--config /home/mirror/.config/ubuntu-debuginfod/config.toml db migrate"
        )

        if config.testmode:
            self.stop(unit, config)
            return

        poller_enabled = 0 == run_ret("systemctl is-enabled ubuntu-debuginfod-launchpad-poller.service")
        services_running = self.is_running(config)
        if not changed and poller_enabled == config.sync_launchpad and services_running:
            return

        self.restart(unit, config)
        if not config.sync_launchpad and poller_enabled:
            run_check("systemctl disable --now ubuntu-debuginfod-launchpad-poller.service")

    def restart(self, unit: Unit, config: Config) -> None:
        if config.testmode:
            # if testing, don't actually download stuff from launchpad
            # TODO: import just one package for testing.
            return

        # The downloader processes jobs produced by the poller.
        desired_downloaders = self._downloader_services(config) if config.download else set()
        for service in sorted(self._enabled_downloader_services() - desired_downloaders):
            run_check(f"systemctl disable --now {service}")
        run_ret(f"systemctl disable --now {DOWNLOADER_SERVICE}")
        for service in sorted(desired_downloaders):
            run_check(f"systemctl enable {service}")
            run_check(f"systemctl restart {service}")

        run_check("systemctl enable ubuntu-debuginfod-launchpad-cleaner.timer")
        run_check("systemctl restart ubuntu-debuginfod-launchpad-cleaner.timer")
        run_check("systemctl restart ubuntu-debuginfod-launchpad-cleaner.service")

        if not config.sync_launchpad:
            # no polling of launchpad, but we do process the pending queue.
            return

        # The poller continuously asks Launchpad for updates.
        run_check("systemctl enable ubuntu-debuginfod-launchpad-poller.service")
        run_check("systemctl restart ubuntu-debuginfod-launchpad-poller.service")

    def stop(self, unit: Unit, config: Config) -> None:
        run_ret("systemctl disable --now ubuntu-debuginfod-launchpad-poller.service")
        run_ret("systemctl disable --now ubuntu-debuginfod-launchpad-cleaner.timer")
        self._stop_downloader_services(config)
        run_ret("systemctl disable --now ubuntu-debuginfod-launchpad-cleaner.service")

    def is_running(self, config: Config) -> bool:
        desired_downloaders = self._downloader_services(config)
        if self._enabled_downloader_services() != desired_downloaders:
            return False
        if any(run_ret(f"systemctl is-active {service}") != 0 for service in desired_downloaders):
            return False
        if run_ret("systemctl is-active ubuntu-debuginfod-launchpad-cleaner.timer") != 0:
            return False
        if not config.download:
            return True
        return not config.sync_launchpad or run_ret(
            "systemctl is-active ubuntu-debuginfod-launchpad-poller.service"
        ) == 0

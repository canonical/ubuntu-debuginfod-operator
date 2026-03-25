"""Ubuntu's debuginfod service representation."""

from __future__ import annotations

import logging
import os
import pwd
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import ops

from util import file_ensure_content, run_check, run_out, run_ret

if TYPE_CHECKING:
    from ops.model import Unit

    from config import Config


basedir = Path(__file__).parent.parent
logger = logging.getLogger(__name__)


class UbuntuDebuginfod:
    """Service for ubuntu-debuginfod."""
    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path

    def _ensure_storage_layout(self, unit: Unit) -> None:
        """Make sure directories exist for debug symbol storage in /srv/debug-mirror."""
        storage_dirs = (
            "srv/debug-mirror/ddebs/",
            "srv/debug-mirror/private-ppas/",
            "srv/debug-mirror/ubuntu-archive-dbg/",
            "srv/debug-mirror/tmpdir/",
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

    def install(self, unit: Unit) -> None:
        unit.status = ops.MaintenanceStatus("Installing ubuntu-debuginfod repo...")

        run_check("add-apt-repository -y ppa:ubuntu-debuginfod-devs/ubuntu-debuginfod")

        unit.status = ops.MaintenanceStatus("Installing ubuntu-debuginfod...")
        # the postinst script does all the user & db setup
        # no recommends, since we don't need toolchain/build-essentials (actually just dpkg-source)
        run_check("apt install -y --no-install-recommends ubuntu-debuginfod")
        # this creates the mirror:mirror user.
        # this also installs configs for:
        # /etc/default/ubuntu-debuginfod-celery
        # /etc/default/ubuntu-debuginfod-launchpad-poller

        self._ensure_storage_layout(unit)

        # set rabbitmq: consumer_timeout = 10800000
        # because ubuntu-debuginfod/README says so.
        rabbit_cfg_path = self.root_path / "etc/rabbitmq/rabbitmq.conf"
        file_ensure_content(rabbit_cfg_path,
                            matcher=r"^(\s*consumer_timeout)\s*=(.*?)$",
                            replace=r"\g<1> = 10800000",
                            content="\nconsumer_timeout = 10800000\n")

        run_check("systemctl restart rabbitmq-server.service")

        # noble has vine 5.0.0 only (and dpkg-depends say so),
        # but celery 5.3.6-1 actually depends (by internal python wheel version check) on vine <6.0,>=5.1.0
        # hack around by installing the newer version...
        celery_version = run_out("dpkg-query --showformat='${Version}' --show python3-celery")
        if run_ret(f"dpkg --compare-versions {shlex.quote(celery_version)} le 5.3.6-1") == 0:
            vine_version = run_out("dpkg-query --showformat='${Version}' --show python3-vine")
            # check vine satisfies celery
            if run_ret(f"dpkg --compare-versions {shlex.quote(vine_version)} lt 5.1.0") == 0:
                with tempfile.TemporaryDirectory() as tmpdir:
                    # use version from 25.04/25.10
                    vine_update = "python3-vine_5.1.0+dfsg-1_all.deb"
                    run_check(f"wget -P {tmpdir}/ http://archive.ubuntu.com/ubuntu/pool/main/v/vine/{vine_update}")
                    run_check(f"apt install {tmpdir}/{vine_update}")

            # remove celery's "runtime" dependency for unused python3-tzdata
            # (which isn't in the archive anyway) to prevent another buggy startup crash.
            celery_py_version = run_out("python3 -c 'import celery; print(celery.__version__)'").strip()
            celery_patch_data = f"""
--- a/usr/lib/python3/dist-packages/celery-{celery_py_version}.dist-info/METADATA
+++ b/usr/lib/python3/dist-packages/celery-{celery_py_version}.dist-info/METADATA
@@ -37,7 +37,6 @@
 Requires-Dist: click <9.0,>=8.1.2
 Requires-Dist: kombu <6.0,>=5.3.4
 Requires-Dist: python-dateutil >=2.8.2
-Requires-Dist: tzdata >=2022.7
 Requires-Dist: vine <6.0,>=5.1.0
 Requires-Dist: importlib-metadata >=3.6 ; python_version < "3.8"
 Requires-Dist: backports.zoneinfo >=0.2.1 ; python_version < "3.9"
""".encode()
            ret = subprocess.run(["patch", "-d/", "-N", "-p1", "-r-"],
                                 capture_output=True, input=celery_patch_data, check=False)
            if ret.returncode != 0:
                # thank you "patch" for not providing a return code to detect already-applied patches.
                if b"previously applied" not in ret.stdout:
                    raise Exception("couldn't apply celery's tzdata removal patch")

        unit.status = ops.ActiveStatus("Ready")

    def configure(self, config: Config) -> None:
        """
        ubuntu-debuginfod setup configuration.
        """

        # Deploy the launchpad access credentials secret file.
        lp_creds_secret = config.lp_credentials
        if lp_creds_secret is None:
            logger.info("launchpad secret configuration not given.")
        else:
            try:
                secrets = lp_creds_secret.get_content(refresh=True)
                lp_creds = secrets["cred"]  # secret key name as set in `juju add-secret`
                file_ensure_content(self.root_path / "home/mirror/.config/ubuntu-debuginfod/lp.cred",
                                    content=lp_creds,
                                    mkdir=True,
                                    owner="mirror")

            except ops.SecretNotFoundError:
                logger.info("launchpad secret not set yet.")

        # set up custom PPAs to fetch
        # if we do anonymous login with ubuntu-debuginfod,
        # it looks in /home/mirror/.config/ubuntu-debuginfod/ppalist instead
        custom_private_ppas="""# private ppas to fetch debug symbols from
ppa:ubuntu-esm/esm-infra-security
ppa:ubuntu-esm/esm-infra-updates
ppa:ubuntu-esm/esm-apps-security
ppa:ubuntu-esm/esm-apps-updates
ppa:ubuntu-advantage/realtime-updates
"""
        file_ensure_content(self.root_path / "home/mirror/.config/ubuntu-debuginfod/ppalist-private",
                            content=custom_private_ppas,
                            mkdir=True,
                            owner="mirror")

    def restart(self, unit: Unit, config: Config) -> None:
        if config.testmode:
            # if testing, don't actually download stuff from launchpad
            # TODO: import just one package for testing.
            return

        # ubuntu-debuginfod-celery: launches downloaders for new debug symbols
        # tasks are generated by by poller
        # needs launchpad creds, which are not given in test mode.
        run_check("systemctl enable ubuntu-debuginfod-celery.service")
        run_check("systemctl restart ubuntu-debuginfod-celery.service")

        # needs ubuntu-debuginfod-celery.service
        run_check("systemctl restart ubuntu-debuginfod-launchpad-cleaner.timer")
        run_check("systemctl restart ubuntu-debuginfod-launchpad-cleaner.service")

        if not config.update_ddeb:
            # no updating of debug files, but we do process the pending queue.
            return

        # ubuntu-debuginfod-launchpad-poller: asks launchpad for updates
        #   this is services/launchpad-poller.py
        run_check("systemctl enable ubuntu-debuginfod-launchpad-poller.timer")
        run_check("systemctl restart ubuntu-debuginfod-launchpad-poller.timer")
        # initial polling
        run_check("systemctl restart ubuntu-debuginfod-launchpad-poller.service")

    def stop(self, unit: Unit, config: Config) -> None:
        run_check("systemctl disable --now ubuntu-debuginfod-launchpad-poller.timer")
        run_check("systemctl disable --now ubuntu-debuginfod-launchpad-cleaner.timer")
        run_check("systemctl disable --now ubuntu-debuginfod-celery.service")
        run_check("systemctl disable --now ubuntu-debuginfod-launchpad-poller.service")
        run_check("systemctl disable --now ubuntu-debuginfod-launchpad-cleaner.service")

    def is_running(self) -> bool:
        return 0 == run_ret("systemctl is-active ubuntu-debuginfod-celery.service")

# `ubuntu-debuginfod` Operator

Charmhub package name: `ubuntu-debuginfod`
More information: https://charmhub.io/ubuntu-debuginfod

Deploy `debuginfod` to serve debugging symbols of Ubuntu's distribution packages to debuggers like GDB.

## About

Entrypoint: [`src/charm.py`](src/charm.py).

When the Charm is installed, it:
- adds the [ubuntu-debuginfod PPA](https://launchpad.net/~ubuntu-debuginfod-devs/+archive/ubuntu/ubuntu-debuginfod)
- installs [`ubuntu-debuginfod`](https://launchpad.net/ubuntu-debuginfod)
- installs and sets up `systemd` services
  - `debuginfod.service`: provides files to debuggers via http (port 8002 default)
  - `ubuntu-debuginfod-launchpad-poller.service` & `.timer`: asks launchpad about new packages
  - `ubuntu-debuginfod-celery.service`: processes jobs and downloads debug symbols from archive

## Other resources

- [debuginfod upstream](https://sourceware.org/elfutils/Debuginfod.html)

- [Contributing](doc/contributing.md)

- See the [Juju SDK documentation](https://juju.is/docs/sdk) for more information about developing and improving charms.


## GitHub integration

We use some GitHub actions to test and release the charm code.

To retrieve the needed "`CHARMHUB_TOKEN`" for authentication (used by charmcraft via env [`CHARMCRAFT_AUTH`](https://documentation.ubuntu.com/charmcraft/latest/howto/manage-the-current-charmhub-user/#remote-environments), run:

```console
charmcraft login --export /tmp/charmcreds.auth --charm ubuntu-debuginfod --permission=package-manage-releases --permission=package-manage-revisions --channel=edge --ttl $((10 * 365 * 24 * 60 * 60))
```

Store the exported output text as a GitHub project secret under `CHARMHUB_TOKEN` (because that name is hardcoded in several "included" workflows).

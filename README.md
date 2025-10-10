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

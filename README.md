# `ubuntu-debuginfod` Operator

Charmhub package: [`ubuntu-debuginfod`](https://charmhub.io/ubuntu-debuginfod)

Deploy `ubuntu-debuginfod` and `debuginfod` to serve debugging symbols of Ubuntu's distribution packages to debuggers like GDB.


## About

Entrypoint: [`src/charm.py`](src/charm.py).

When the [Charm](https://juju.is/charms-architecture) is installed, it:
- adds the [ubuntu-debuginfod PPA](https://launchpad.net/~ubuntu-debuginfod-devs/+archive/ubuntu/ubuntu-debuginfod)
- installs [`ubuntu-debuginfod`](https://launchpad.net/ubuntu-debuginfod)
- installs and sets up `systemd` services
  - `debuginfod.service`: provides files to debuggers via http (port 8002 default)
  - `ubuntu-debuginfod-launchpad-poller.service` & `.timer`: asks launchpad about new packages
  - `ubuntu-debuginfod-celery.service`: processes jobs and downloads debug symbols from archive

## Other resources

- [documentation](doc/README.md)
- [debuginfod upstream](https://sourceware.org/elfutils/Debuginfod.html)
- [Contributing](doc/contributing.md)
- See the [Juju SDK documentation](https://juju.is/docs/sdk) for more information about developing and improving charms.


## GitHub integration

We use some GitHub actions to test and release the charm code.

To retrieve the needed "`CHARMHUB_TOKEN`" for authentication (used by charmcraft via env [`CHARMCRAFT_AUTH`](https://documentation.ubuntu.com/charmcraft/latest/howto/manage-the-current-charmhub-user/#remote-environments)), run:

```console
charmcraft login --export /tmp/charmcreds.auth --charm ubuntu-debuginfod --permission=package-view --permission=package-manage-revisions --permission=package-manage-releases --channel "latest/edge" --channel "latest/stable" --ttl $((10 * 365 * 24 * 60 * 60))
```

Store the exported output text as a GitHub project secret under `CHARMHUB_TOKEN` (because that name is hardcoded in several "included" workflows).


## Ingress integration

To integrate into enterprise-style infrastructure landscapes, this charm provides the `debuginfod-http-ingress` relation (interface: `ingress`).
This allows dynamically routing traffic via proxies to the `debuginfod` service.

In production, this is typically wired through an ingress provider chain (for example `ingress-configurator` -> offered machine-ingress).

To test locally with a simple ingress provider:

``` console
% charmcraft pack
% juju deploy ./ubuntu-debuginfod_*.charm ubuntu-debuginfod --config testmode=true

% juju deploy haproxy --channel 2.8/edge --config external-hostname=debuginfod.local
% juju deploy self-signed-certificates --channel 1/edge
% juju integrate haproxy:certificates self-signed-certificates:certificates

# ingress relation (auto-matched by ingress interface)
% juju integrate ubuntu-debuginfod haproxy

# proxy relay test for debuginfod API path
# you'll get a 404 not found for this unknown build id
% curl -i -k -H "Host: debuginfod.local" "https://$haproxy_ip/$model_name-ubuntu-debuginfod/buildid/0000000000000000000000000000000000000000/debuginfo"
```

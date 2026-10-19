# Contributing

To make contributions to this charm, you'll need a working [development setup](https://juju.is/docs/sdk/dev-setup).

Development tasks are run with [`just`](https://just.systems); run `just` to list them.

You can create an environment for development with `uv`:

``` console
just sync
# this creates .venv
```

## Testing

This project uses `pytest` testing.

``` console
# run unit tests
just test
# run integration tests (needs a Juju controller)
just test-integration
```

Extra arguments are passed to `pytest`, e.g. `just test -k is_running --log-cli-level=DEBUG --tb native`.

To test a prebuilt upstream snapshot instead of the production PPA, provide both binary packages from the same source build:

``` console
uv run pytest tests/integration \
	--ubuntu-debuginfod-deb=/path/to/ubuntu-debuginfod_VERSION_all.deb \
	--python3-ubuntu-debuginfod-deb=/path/to/python3-ubuntu-debuginfod_VERSION_all.deb
```

## Build the charm

You need the `charmcraft` snap.

To build the charm file in this git repository:

``` console
just pack
```

The `.charm` file is not rebuilt automatically: pack again before every `juju refresh --path`.

The same package resources can be used without pytest for a manual deployment:

``` console
juju deploy ./ubuntu-debuginfod_*.charm ubuntu-debuginfod \
	--config package_source=resource \
	--resource ubuntu-debuginfod-deb=/path/to/ubuntu-debuginfod_VERSION_all.deb \
	--resource python3-ubuntu-debuginfod-deb=/path/to/python3-ubuntu-debuginfod_VERSION_all.deb
```

To replace the snapshot on an existing local deployment, refresh the charm and both resources together:

``` console
juju refresh ubuntu-debuginfod \
	--path ./ubuntu-debuginfod_*.charm \
	--config package_source=resource \
	--resource ubuntu-debuginfod-deb=/path/to/ubuntu-debuginfod_VERSION_all.deb \
	--resource python3-ubuntu-debuginfod-deb=/path/to/python3-ubuntu-debuginfod_VERSION_all.deb \
	--force
```

To update only the packages on an existing deployment without touching the charm revision, attach new resource revisions and switch the package source:

``` console
juju attach-resource ubuntu-debuginfod ubuntu-debuginfod-deb=/path/to/ubuntu-debuginfod_VERSION_all.deb
juju attach-resource ubuntu-debuginfod python3-ubuntu-debuginfod-deb=/path/to/python3-ubuntu-debuginfod_VERSION_all.deb
juju config ubuntu-debuginfod package_source=resource
```

Note: changing `package_source` on an existing unit only affects the next install or upgrade hook;
`config-changed` alone does not reinstall the packages.
Use `juju refresh` as above to force reinstallation.

With the default `package_source=ppa`, neither resource is fetched and the charm installs the production PPA package.

## Style

We use `ruff` for style checking, `ty` for type checks.

``` console
# style linting and type checks
just lint
```

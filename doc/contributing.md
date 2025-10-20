# Contributing

To make contributions to this charm, you'll need a working [development setup](https://juju.is/docs/sdk/dev-setup).

You can create an environment for development with `uv`:

``` console
uv sync --all-extras --dev
# this creates .venv
```

## Testing

This project uses `pytest` testing.
that can be used for linting and formatting code when you're preparing contributions to the charm:

``` console
# run unit tests
uv run pytest --log-cli-level=DEBUG --tb native tests/unit
# run integrationt tests
uv run pytest --log-cli-level=DEBUG --tb native tests/integration
```

## Build the charm

You need the `charmcraft` snap.

To build the charm file in this git repository:

``` console
charmcraft pack
```

## Style

We use `ruff` for style checking, `mypy` for type checks.

``` console
# to run type checks
uv run mypy ./src
# code style linting
uv run ruff check
```

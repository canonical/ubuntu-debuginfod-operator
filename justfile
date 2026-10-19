# development tasks; AGENTS.md and doc/contributing.md refer to these

default:
    @just --list

# create or update .venv
sync:
    uv sync --locked --all-extras --dev

# style and type checks
lint:
    uv run ruff check
    uv run ty check

# unit tests; extra arguments go to pytest
test *args:
    uv run pytest tests/unit {{ args }}

# integration tests (needs a Juju controller); extra arguments go to pytest
test-integration *args:
    uv run pytest --tb native tests/integration {{ args }}

# what has to pass before a change is done
check: lint test

# build the .charm file (needs the charmcraft snap)
pack:
    charmcraft pack

"""Integration test configuration."""

import subprocess
from pathlib import Path

import jubilant
import pytest
import yaml

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())


def pytest_addoption(parser):
    parser.addoption(
        "--charm-file", help="instead of charmcraft pack, use this .charm file"
    )


@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest):
    """Create a temporary juju model for testing."""
    with jubilant.temp_model() as juju:
        yield juju

        if request.session.testsfailed:
            log = juju.debug_log(limit=2000)
            print("tests failed, here's juju debug-log.")
            print(log, end="")


@pytest.fixture(scope="session")
def charm(request: pytest.FixtureRequest) -> Path:
    """Build the charm for integration testing."""
    charm_file = request.config.getoption("--charm-file")
    if charm_file:
        return Path(charm_file)

    # charmcraft pack apparently can't tell the output filename.
    subprocess.check_call(["charmcraft", "pack", "--verbose"])
    # TODO: charmcraft should provide a way to set the output name...
    return next(Path(".").glob("*.charm"))


@pytest.fixture(scope="module")
def app(juju: jubilant.Juju, charm: Path):
    """Deploy ubuntu-debuginfod charm."""

    app_name = METADATA["name"]

    # juju expects leading ./ or / for charm files...
    charm_path = str(charm) if charm.is_absolute() else f"./{charm}"

    # refresh if already exists
    if app_name in juju.status().apps:
        juju.refresh(app_name, path=charm_path, force=True)

    else:
        juju.deploy(charm_path, app=app_name, config={"testmode": True})

    juju.wait(jubilant.all_active,
              timeout=200.0)

    yield app_name

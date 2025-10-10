"""Integration test configuration."""

import subprocess
from pathlib import Path

import jubilant
import pytest
import yaml

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())

@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest):
    """Create a temporary juju model for testing."""
    with jubilant.temp_model() as juju:
        yield juju

        if request.session.testsfailed:
            log = juju.debug_log(limit=1000)
            print("tests failed, here's juju debug-log.")
            print(log, end="")


@pytest.fixture(scope="session")
def charm(request: pytest.FixtureRequest) -> Path:
    """Build the charm for integration testing."""
    charm_file = request.config.getoption("--charm-file")
    if charm_file:
        return charm_file

    # charmcraft pack apparently can't tell the output filename.
    subprocess.check_call(["charmcraft", "pack", "--verbose"])
    # TODO: there has to be a better way than globbing for the output...
    return next(Path(".").glob("*.charm"))


@pytest.fixture(scope="module")
def app(juju: jubilant.Juju, charm: Path):
    """Deploy ubuntu-debuginfod charm."""
    juju.deploy(f"./{charm}", config={"testmode": True})
    juju.wait(jubilant.all_active,
              timeout=120.0)

    yield METADATA["name"]

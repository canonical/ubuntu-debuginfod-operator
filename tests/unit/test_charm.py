# Copyright 2025 Jonas Jelten <jonas.jelten@canonical.com>
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from ops.testing import ActiveStatus, BlockedStatus, Context, State

from charm import UbuntuDebuginfodCharm

# Import the function to be tested
from util import file_ensure_content


@pytest.fixture
def ctx() -> Context:
    """Create a standard context for the charm."""
    return Context(
        UbuntuDebuginfodCharm,
        # TODO: get config (& meta, actions) from parsed charmcraft.yaml
        # just config overrides doesn't seem possible.
    )

@pytest.fixture
def base_state(ctx) -> State:
    """Create a base state for the charm."""
    return State(leader=True)


@patch("os.chown")
def test_install_success(
    mock_os_chown,
    fake_process,  # fixture from pytest-process
    ctx,
    base_state,
    tmp_path,
):
    """
    Test successful installation with valid config.
    """

    # any command can be called
    fake_process.register([fake_process.any()])
    # allow infinite calls
    fake_process.keep_last_process(True)

    # custom env var to signal testing environment basedir
    os.environ["JUJU_CHARM_PREFIX"] = str(tmp_path)

    # run juju install hook
    out = ctx.run(ctx.on.install(), base_state)

    assert isinstance(out.unit_status, ActiveStatus)

    installed_packages = [
        "debuginfod",
        "ubuntu-debuginfod",
    ]
    for pkg in installed_packages:
        assert fake_process.call_count(["apt", "install", "-y", fake_process.any(), pkg]) == 1

    assert fake_process.call_count(["add-apt-repository", "-y",
                                    fake_process.any(), "ppa:ubuntu-debuginfod-devs/ubuntu-debuginfod"]) == 1

def test_start_success(
    fake_process,  # fixture from pytest-process
    ctx,
    base_state,
    tmp_path,
):
    """
    Test successful start.
    """

    # any command can be called
    fake_process.register([fake_process.any()])
    # allow infinite calls
    fake_process.keep_last_process(True)

    # custom env var to signal testing environment basedir
    os.environ["JUJU_CHARM_PREFIX"] = str(tmp_path)

    # run juju install hook
    out = ctx.run(ctx.on.start(), base_state)

    assert isinstance(out.unit_status, ActiveStatus)

    started_services = [
        "debuginfod.service",
        "ubuntu-debuginfod-celery.service",
        "ubuntu-debuginfod-launchpad-cleaner.service",
        "ubuntu-debuginfod-launchpad-cleaner.timer",
    ]
    for pkg in started_services:
        assert fake_process.call_count(["systemctl", "restart", fake_process.any(), pkg]) == 1


def test_stop_success(
    fake_process,  # fixture from pytest-process
    ctx,
    base_state,
    tmp_path,
):
    """
    Test successful stop.
    """

    # any command can be called
    fake_process.register([fake_process.any()])
    # allow infinite calls
    fake_process.keep_last_process(True)

    # custom env var to signal testing environment basedir
    os.environ["JUJU_CHARM_PREFIX"] = str(tmp_path)

    # run juju install hook
    out = ctx.run(ctx.on.stop(), base_state)

    assert isinstance(out.unit_status, BlockedStatus)

    stopped_services = [
        "debuginfod.service",
        "ubuntu-debuginfod-celery.service",
        "ubuntu-debuginfod-launchpad-cleaner.timer",
        "ubuntu-debuginfod-launchpad-cleaner.service",
        "ubuntu-debuginfod-launchpad-poller.timer",
        "ubuntu-debuginfod-launchpad-poller.service",
    ]
    for pkg in stopped_services:
        assert fake_process.call_count(["systemctl", "disable", "--now", fake_process.any(), pkg]) == 1


def test_create_new_file_with_content(tmp_path: Path):
    """Tests creating a new file with the specified content."""
    file = tmp_path / "test.file"
    content = "Hai!"

    assert not file.exists()
    file_ensure_content(file, content)

    assert file.is_file()
    assert file.read_text() == content

def test_create_directory_and_file(tmp_path: Path):
    """Tests creating parent directories when mkdir=True."""
    file = tmp_path / "new_dir" / "test.file"
    content = "with directory"

    assert not file.parent.exists()
    file_ensure_content(file, content, mkdir=True)

    assert file.is_file()
    assert file.read_text() == content

def test_overwrite_existing_file_without_matcher(tmp_path: Path):
    """Tests overwriting a file when content differs and no matcher is used."""
    file = tmp_path / "test.file"
    file.write_text("Old content.")
    new_content = "New content!"

    file_ensure_content(file, new_content, append_missing=False)

    assert file.read_text() == new_content

def test_do_nothing_if_content_unchanged(tmp_path: Path):
    """Tests that the file is untouched if content already matches."""
    file = tmp_path / "test.file"
    content = "Content is correct."
    file.write_text(content)
    prev_mtime = file.stat().st_mtime

    file_ensure_content(file, content)

    assert file.read_text() == content
    assert prev_mtime == file.stat().st_mtime

def test_replace_content_with_matcher(tmp_path: Path):
    """Tests replacing a line that matches the regex."""
    file = tmp_path / "config.conf"
    initial_content = "user=chef\nlevel=2\n"
    file.write_text(initial_content)

    file_ensure_content(
        file,
        content="user=guest",  # used if matcher fails
        matcher=r"(?m)^user=.*$",
        replace="user=guest",
    )

    assert file.read_text() == "user=guest\nlevel=2\n"

def test_append_if_matcher_fails_and_append_is_true(tmp_path: Path):
    """Tests appending content if matcher doesn't find a match (default)."""
    file = tmp_path / "settings.file"
    initial_content = "mode=auto\n"
    file.write_text(initial_content)

    file_ensure_content(
        file,
        content="feature_enabled=true\n",
        matcher=r"^feature_enabled=.*$",
        replace="feature_enabled=true",
    )

    expected_content = "mode=auto\nfeature_enabled=true\n"
    assert file.read_text() == expected_content

def test_overwrite_if_matcher_fails_and_append_is_false(tmp_path: Path):
    """Tests overwriting the file if matcher fails and append_missing is False."""
    file = tmp_path / "settings.file"
    file.write_text("old_setting=old_value")

    new_content = "feature_enabled=true"

    file_ensure_content(
        file,
        content=new_content,
        matcher=r"^feature_enabled=.*$",
        replace="feature_enabled=true",
        append_missing=False,
    )

    assert file.read_text() == new_content

def test_matcher_without_replace_raises_error(tmp_path: Path):
    """Tests that matcher requires replace."""
    file = tmp_path / "test.file"
    file.write_text("some data")

    with pytest.raises(ValueError):
        file_ensure_content(file, "new data", matcher="some")

@patch('shutil.chown')
@patch('charmlibs.pathops.LocalPath.owner', return_value='root')
def test_chown_is_called_when_owner_differs(mock_owner, mock_chown, tmp_path):
    """Tests that shutil.chown is called if the file owner is different."""
    file = tmp_path / "test.file"
    file.touch()

    file_ensure_content(file, "content", owner="new_owner")

    mock_chown.assert_called_once_with(file, "new_owner")

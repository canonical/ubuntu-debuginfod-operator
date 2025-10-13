"""utility functionality."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess

from charmlibs import pathops


def run_check(cmd: str):
    """Execute a shell command, which must return 0."""
    subprocess.check_call(shlex.split(cmd))

def run_ret(cmd: str) -> int:
    """Execute a shell command and get its returncode."""
    return subprocess.run(shlex.split(cmd), check=False).returncode

def run_out(cmd: str) -> str:
    """Execute a shell command and get its output."""
    return subprocess.check_output(shlex.split(cmd)).decode()

def file_ensure_content(
    file_path: pathops.LocalPath,
    content: str,
    replace: str | None = None,
    matcher: str | None = None,
    mkdir: bool = False,
    append_missing: bool = True,
    owner: str | None = None,
) -> None:
    """For the given path, ensure content is present by replacing or adding.

    `matcher` is a regex searching for content to be updated and replaced by `replace`.
    when `matcher` does not match, instead append `new` to the file.
    """
    missing = True
    if file_path.is_file():
        with file_path.open("r") as hdl:
            current_content = hdl.read()

        if matcher is not None:
            if replace is None:
                raise Exception("when there's a matcher, you need to set replace.")
            find = re.compile(matcher)

            if find.match(current_content):
                missing = False
                new_cfg = re.sub(find, replace, current_content, count=1)

                if current_content != new_cfg:
                    # content needs updating
                    with file_path.open("w") as hdl:
                        hdl.write(new_cfg)
        elif current_content != content:
            with file_path.open("w") as hdl:
                hdl.write(content)
    elif mkdir:
        file_path.parent.mkdir(parents=True, exist_ok=True)

    if missing:
        # content is missing
        if append_missing:
            with file_path.open("a") as hdl:
                hdl.write(content)
        else:
            with file_path.open("w") as hdl:
                hdl.write(content)

    if owner is not None:
        if file_path.owner() != owner:
            shutil.chown(file_path, owner)

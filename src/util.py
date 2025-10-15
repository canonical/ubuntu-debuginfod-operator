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
    mkdir: bool = True,
    append_missing: bool = True,
    owner: str | None = None,
) -> None:
    """For the given path, ensure content is present by replacing or adding.

    `matcher` is a regex searching for content to be updated and replaced by `replace`.
    when `matcher` does not match, instead append/set `content` to the file
    (configured by `append_missing`).
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
        if file_path.is_file() and append_missing:
            with file_path.open("a") as hdl:
                hdl.write(content)
        else:
            with file_path.open("w") as hdl:
                hdl.write(content)

    if owner is not None:
        if file_path.owner() != owner:
            shutil.chown(file_path, owner)


def file_copy(src: pathops.Path, dest: pathops.Path, mkdirs: bool = True):
    if not src.is_file():
        raise ValueError(f"source file {src!r} doesn't exist")
    if mkdirs and not dest.parent.is_dir():
        dest.parent.mkdir(parents=True)
    shutil.copy(
        src,
        dest,
    )

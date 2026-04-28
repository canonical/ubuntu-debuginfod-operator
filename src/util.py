"""utility functionality."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from pathlib import Path


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
    file_path: Path,
    content: str,
    replace: str | None = None,
    matcher: str | None = None,
    mkdir: bool = True,
    append_missing: bool = True,
    owner: str | None = None,
) -> bool:
    """For the given path, ensure content is present by replacing or adding.

    `matcher` is a regex searching for content to be updated and replaced by `replace`.
    when `matcher` does not match, instead append/set `content` to the file
    (configured by `append_missing`).

    returns if file was changed.
    """
    changed = False
    missing = True
    if file_path.is_file():
        with file_path.open("r") as hdl:
            current_content = hdl.read()

        if matcher is not None:
            if replace is None:
                raise ValueError("when there's a matcher, you need to set replace.")
            find = re.compile(matcher)

            if find.match(current_content):
                missing = False
                new_cfg = re.sub(find, replace, current_content, count=1)

                if current_content != new_cfg:
                    # content needs updating
                    with file_path.open("w") as hdl:
                        hdl.write(new_cfg)
                        changed = True

        elif current_content == content:
            missing = False

    else:
        if mkdir:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        append_missing = False

    if missing:
        # content is missing
        if append_missing and file_path.is_file():
            with file_path.open("a") as hdl:
                hdl.write(content)
            changed = True
        else:
            with file_path.open("w") as hdl:
                hdl.write(content)
            changed = True

    if owner is not None:
        if file_path.owner() != owner:
            shutil.chown(file_path, owner)
            changed = True

    return changed


def file_copy(src: Path, dest: Path, mkdirs: bool = True) -> bool:
    if not src.is_file():
        raise ValueError(f"source file {src!r} doesn't exist")
    if dest.is_file():
        if src.read_bytes() == dest.read_bytes():
            return False
    if mkdirs and not dest.parent.is_dir():
        dest.parent.mkdir(parents=True)
    shutil.copy(
        src,
        dest,
    )
    return True


def file_link(target: Path, dest: Path, mkdirs: bool = True, relative: bool = False) -> bool:
    rel_target = dest.parent / target
    if not rel_target.exists():
        raise ValueError(f"link target {target!r} doesn't exist")

    if dest.is_symlink() and dest.parent / dest.readlink() == target:
        return False
    if mkdirs and not dest.parent.is_dir():
        dest.parent.mkdir(parents=True)

    if relative and str(target)[0] == "/":
        target = target.relative_to(dest.parent)
    dest.symlink_to(target)
    return True


def file_remove(path: Path, recurse: bool = False) -> bool:
    if not path.exists():
        # already removed
        return False

    if recurse:
        shutil.rmtree(path)
    else:
        path.unlink()

    return True

"""Charm configuration options."""

from __future__ import annotations

from typing import Literal

import ops
import pydantic


class Config(pydantic.BaseModel):
    """Config fields as defined in charmcraft.yaml, with values from juju."""

    # ops.model.Secret is not pydantic-compatible, so we can't actually nest it.
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    # poll launchpad for new debug ddebs and enqueue downloads
    sync_launchpad: bool = pydantic.Field()

    # run the downloader workers processing the download queue
    download: bool = pydantic.Field(default=True)

    # parallel downloader processes on this unit
    downloader_workers: int = pydantic.Field(default=1, ge=1)

    # package installation source
    package_source: Literal["ppa", "resource"] = pydantic.Field(default="ppa")

    # run in testmode
    testmode: bool = pydantic.Field()

    # use nginx reverse proxy
    use_reverse_proxy: bool = pydantic.Field()

    # launchpad secret
    lp_credentials: ops.model.Secret | None = pydantic.Field(default=None)

    # http(s) proxy URL for the services' outbound connections (e.g. to Launchpad).
    # empty -> fall back to the model's JUJU_CHARM_*_PROXY env; "none" -> no proxy.
    proxy: str = pydantic.Field(default="")

    # architectures whose debug symbols are downloaded (upstream mirror_arches).
    # space-separated in juju; empty -> all architectures (upstream default).
    mirror_architectures: list[str] = pydantic.Field(default_factory=list)

    @pydantic.field_validator("mirror_architectures", mode="before")
    @classmethod
    def _parse_arches(cls, value):
        # juju string options arrive as one space-separated string
        if isinstance(value, str):
            return value.split()
        return value

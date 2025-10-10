"""Charm configuration options."""

from __future__ import annotations

import ops
import pydantic


class Config(pydantic.BaseModel):
    """Config fields as defined in charmcraft.yaml, with values from juju."""

    # ops.model.Secret is not pydantic-compatible, so we can't actually nest it.
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    update_ddeb: bool = pydantic.Field()
    testmode: bool = pydantic.Field()
    lp_credentials: ops.model.Secret = pydantic.Field()

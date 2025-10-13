#!/usr/bin/env python3
# Copyright 2025 Jonas Jelten <jonas.jelten@canonical.com>
# See LICENSE file for licensing details.

import json
import logging
from pathlib import Path

import jubilant
import requests
import yaml

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())

logger = logging.getLogger(__name__)



def _address(juju_: jubilant.Juju, app_name: str):
    """Get the IP address of the application."""
    return juju_.status().apps[app_name].units[f"{app_name}/0"].public_address


def test_deploy_app(juju: jubilant.Juju, app: str):
    """
    Test if deployment itself works.
    The "app" parameter pulls in the deployment fixture.
    """
    assert app


def test_services_running(juju: jubilant.Juju, app: str):
    services_raw = juju.ssh(f"{app}/0", "systemctl list-units --type service --full --all --output json")
    services_list = json.loads(services_raw)
    services = {svc["unit"]: svc for svc in services_list}

    assert services["debuginfod.service"]["active"] == "active"


def test_application_is_up(juju: jubilant.Juju, app: str):
    response = requests.get(f"http://{_address(juju, app)}:8002")
    assert response.status_code == 200
    # TODO testmode to provide selected debug data
    buildid = "d11ba2e3311344ed7ce2745a3a7942c76a54fba8"
    response = requests.get(f"http://{_address(juju, app)}:8002/buildid/{buildid}/debuginfo")
    # assert response.status_code == 200

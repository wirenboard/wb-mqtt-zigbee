"""Common test fixtures: expose data for typical devices."""

import sys
from unittest.mock import MagicMock

# Stub wb_common before any project imports (not installed in dev environment)
if "wb_common" not in sys.modules:
    _wb = MagicMock()
    sys.modules["wb_common"] = _wb
    sys.modules["wb_common.mqtt_client"] = _wb.mqtt_client

import pytest

from wb.zigbee2mqtt.z2m.model import ExposeAccess, ExposeFeature


# ---------------------------------------------------------------------------
# Teststand option (must be in root conftest for pytest_addoption)
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--teststand-host", default=None,
        help="IP/hostname of the test stand with MQTT broker",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--teststand-host"):
        return
    skip = pytest.mark.skip(reason="need --teststand-host option to run")
    for item in items:
        if "teststand" in item.keywords:
            item.add_marker(skip)

# ---------------------------------------------------------------------------
# Raw expose dicts — reusable as both ExposeFeature.from_dict() input
# and as bridge/devices JSON payload fragments
# ---------------------------------------------------------------------------

RELAY_EXPOSE = {
    "type": "switch",
    "features": [
        {
            "type": "binary",
            "name": "state",
            "property": "state",
            "access": ExposeAccess.READ | ExposeAccess.WRITE | ExposeAccess.GET,
            "value_on": "ON",
            "value_off": "OFF",
        }
    ],
}

TEMP_SENSOR_EXPOSES = [
    {"type": "numeric", "name": "temperature", "property": "temperature", "access": ExposeAccess.READ, "unit": "°C"},
    {"type": "numeric", "name": "humidity", "property": "humidity", "access": ExposeAccess.READ, "unit": "%"},
    {"type": "numeric", "name": "battery", "property": "battery", "access": ExposeAccess.READ, "unit": "%"},
]

COLOR_LAMP_EXPOSES = [
    {
        "type": "light",
        "features": [
            {
                "type": "binary",
                "name": "state",
                "property": "state",
                "access": ExposeAccess.READ | ExposeAccess.WRITE | ExposeAccess.GET,
                "value_on": "ON",
                "value_off": "OFF",
            },
            {
                "type": "numeric",
                "name": "brightness",
                "property": "brightness",
                "access": ExposeAccess.READ | ExposeAccess.WRITE | ExposeAccess.GET,
                "value_min": 0,
                "value_max": 254,
            },
            {
                "type": "numeric",
                "name": "color_temp",
                "property": "color_temp",
                "access": ExposeAccess.READ | ExposeAccess.WRITE | ExposeAccess.GET,
                "value_min": 150,
                "value_max": 500,
                "unit": "mired",
            },
            {
                "type": "composite",
                "name": "color_hs",
                "property": "color",
                "features": [
                    {"type": "numeric", "name": "hue", "property": "", "access": ExposeAccess.READ | ExposeAccess.WRITE},
                    {"type": "numeric", "name": "saturation", "property": "", "access": ExposeAccess.READ | ExposeAccess.WRITE},
                ],
            },
        ],
    },
]

ENUM_EXPOSE = {
    "type": "enum",
    "name": "mode",
    "property": "mode",
    "access": ExposeAccess.READ | ExposeAccess.WRITE,
    "values": ["off", "auto", "heat", "cool"],
}

MULTISENSOR_EXPOSES = [
    {"type": "numeric", "name": "temperature", "property": "temperature", "access": ExposeAccess.READ, "unit": "°C"},
    {"type": "numeric", "name": "humidity", "property": "humidity", "access": ExposeAccess.READ, "unit": "%"},
    {"type": "numeric", "name": "illuminance_lux", "property": "illuminance_lux", "access": ExposeAccess.READ, "unit": "lx"},
    {
        "type": "binary",
        "name": "occupancy",
        "property": "occupancy",
        "access": ExposeAccess.READ,
        "value_on": "true",
        "value_off": "false",
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def relay_exposes():
    return [ExposeFeature.from_dict(RELAY_EXPOSE)]


@pytest.fixture
def temp_sensor_exposes():
    return [ExposeFeature.from_dict(e) for e in TEMP_SENSOR_EXPOSES]


@pytest.fixture
def color_lamp_exposes():
    return [ExposeFeature.from_dict(e) for e in COLOR_LAMP_EXPOSES]


@pytest.fixture
def enum_expose():
    return ExposeFeature.from_dict(ENUM_EXPOSE)


@pytest.fixture
def multisensor_exposes():
    return [ExposeFeature.from_dict(e) for e in MULTISENSOR_EXPOSES]

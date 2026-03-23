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
        "--teststand-host",
        default=None,
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
    {
        "type": "numeric",
        "name": "temperature",
        "property": "temperature",
        "access": ExposeAccess.READ,
        "unit": "°C",
    },
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
                    {
                        "type": "numeric",
                        "name": "hue",
                        "property": "",
                        "access": ExposeAccess.READ | ExposeAccess.WRITE,
                    },
                    {
                        "type": "numeric",
                        "name": "saturation",
                        "property": "",
                        "access": ExposeAccess.READ | ExposeAccess.WRITE,
                    },
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
    {
        "type": "numeric",
        "name": "temperature",
        "property": "temperature",
        "access": ExposeAccess.READ,
        "unit": "°C",
    },
    {"type": "numeric", "name": "humidity", "property": "humidity", "access": ExposeAccess.READ, "unit": "%"},
    {
        "type": "numeric",
        "name": "illuminance_lux",
        "property": "illuminance_lux",
        "access": ExposeAccess.READ,
        "unit": "lx",
    },
    {
        "type": "binary",
        "name": "occupancy",
        "property": "occupancy",
        "access": ExposeAccess.READ,
        "value_on": "true",
        "value_off": "false",
    },
]

CLIMATE_EXPOSES = [
    {
        "type": "climate",
        "features": [
            {
                "type": "numeric",
                "name": "occupied_heating_setpoint",
                "property": "occupied_heating_setpoint",
                "access": ExposeAccess.READ | ExposeAccess.WRITE | ExposeAccess.GET,
                "unit": "°C",
                "value_min": 7,
                "value_max": 30,
            },
            {
                "type": "numeric",
                "name": "local_temperature",
                "property": "local_temperature",
                "access": ExposeAccess.READ | ExposeAccess.GET,
                "unit": "°C",
            },
            {
                "type": "enum",
                "name": "system_mode",
                "property": "system_mode",
                "access": ExposeAccess.READ | ExposeAccess.WRITE | ExposeAccess.GET,
                "values": ["off", "heat", "cool", "auto"],
            },
            {
                "type": "enum",
                "name": "running_state",
                "property": "running_state",
                "access": ExposeAccess.READ,
                "values": ["idle", "heat", "cool"],
            },
        ],
    },
]

COVER_EXPOSES = [
    {
        "type": "cover",
        "features": [
            {
                "type": "numeric",
                "name": "position",
                "property": "position",
                "access": ExposeAccess.READ | ExposeAccess.WRITE | ExposeAccess.GET,
                "value_min": 0,
                "value_max": 100,
                "unit": "%",
            },
            {
                "type": "numeric",
                "name": "tilt",
                "property": "tilt",
                "access": ExposeAccess.READ | ExposeAccess.WRITE | ExposeAccess.GET,
                "value_min": 0,
                "value_max": 100,
            },
            {
                "type": "enum",
                "name": "state",
                "property": "state",
                "access": ExposeAccess.READ | ExposeAccess.WRITE,
                "values": ["OPEN", "CLOSE", "STOP"],
            },
        ],
    },
]

FAN_EXPOSES = [
    {
        "type": "fan",
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
                "type": "enum",
                "name": "mode",
                "property": "mode",
                "access": ExposeAccess.READ | ExposeAccess.WRITE,
                "values": ["low", "medium", "high", "auto"],
            },
        ],
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


@pytest.fixture
def climate_exposes():
    return [ExposeFeature.from_dict(e) for e in CLIMATE_EXPOSES]


@pytest.fixture
def cover_exposes():
    return [ExposeFeature.from_dict(e) for e in COVER_EXPOSES]


@pytest.fixture
def fan_exposes():
    return [ExposeFeature.from_dict(e) for e in FAN_EXPOSES]

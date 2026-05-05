"""
Common fixtures for integration tests.

Also provides a fallback stub for `wb_common.mqtt_client` if the package is
not installed in the current environment (it ships as a Wiren Board Debian
package and is not on PyPI). The stub class is used purely for type
annotations in production code; tests pass `FakeMqttClient` instances at
runtime, and there is no `isinstance(..., MQTTClient)` check anywhere in
the production code.
"""

import importlib.util
import sys
import types

if importlib.util.find_spec("wb_common") is None:
    _wb_common = types.ModuleType("wb_common")
    _wb_common.__path__ = []  # mark as package
    _mqtt_client_mod = types.ModuleType("wb_common.mqtt_client")

    class _StubMQTTClient:  # pylint: disable=too-few-public-methods
        """Stub for production type annotations only — never instantiated in tests"""

    _mqtt_client_mod.MQTTClient = _StubMQTTClient
    sys.modules["wb_common"] = _wb_common
    sys.modules["wb_common.mqtt_client"] = _mqtt_client_mod


import pytest  # noqa: E402

from .fakes.broker import FakeMqttBroker  # noqa: E402
from .fakes.client import FakeMqttClient  # noqa: E402
from .helpers.wb_observer import WbObserver  # noqa: E402
from .helpers.z2m_emulator import Z2mEmulator  # noqa: E402

DEFAULT_BASE_TOPIC = "zigbee2mqtt"
DEFAULT_BRIDGE_DEVICE_ID = "zigbee2mqtt"
DEFAULT_BRIDGE_DEVICE_NAME = "Zigbee2MQTT bridge"


@pytest.fixture
def fake_broker() -> FakeMqttBroker:
    """
    Fresh in-process MQTT broker mock per test
    """
    return FakeMqttBroker()


@pytest.fixture
def fake_mqtt_client(fake_broker: FakeMqttBroker) -> FakeMqttClient:
    """
    FakeMqttClient bound to the per-test broker
    """
    return FakeMqttClient(fake_broker)


@pytest.fixture
def wb_observer(fake_broker: FakeMqttBroker) -> WbObserver:
    """
    Helper to query messages observed on the broker
    """
    return WbObserver(fake_broker)


@pytest.fixture
def z2m_emu(fake_broker: FakeMqttBroker) -> Z2mEmulator:
    """
    Helper to publish z2m-shaped messages onto the broker
    """
    return Z2mEmulator(fake_broker, DEFAULT_BASE_TOPIC)

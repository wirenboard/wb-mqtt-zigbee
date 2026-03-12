from setuptools import setup


def get_version():
    with open("debian/changelog", "r", encoding="utf-8") as f:
        return f.readline().split()[1][1:-1].split("~")[0]


setup(
    name="wb-zigbee2mqtt",
    version=get_version(),
    maintainer="Wiren Board Team",
    maintainer_email="info@wirenboard.com",
    description="Wiren Board Zigbee2MQTT bridge v2",
    url="https://github.com/wirenboard/wb-zigbee2mqtt-v2",
    packages=["wb.zigbee2mqtt", "wb.zigbee2mqtt.z2m", "wb.zigbee2mqtt.wb_converter"],
    scripts=["bin/wb-zigbee2mqtt"],
    license="MIT",
)
# Other file (configuration):
# - Installed by debian/install file

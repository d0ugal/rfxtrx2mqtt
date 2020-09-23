import json
import logging
import sys
import time
from dataclasses import dataclass

import paho.mqtt.client as mqtt
import RFXtrx as rfxtrxmod
import RFXtrx.lowlevel as lowlevel
import yaml

LOG = logging.getLogger("rfxtrx2mqtt")
CLIENT_ID = "rfxtrx2mqtt"
UNKNOWN_DEVICE_SENSOR_TOPIC = "homeassistant/sensor/rfxtrx2mqtt_unknown_device/state"

_REGISTRY = {}
mqttc = mqtt.Client(client_id=CLIENT_ID)

UNIT_OF_MEASUREMENTS = {
    "Temperature": "°C",
    "Temperature2": "°C",
    "Humidity": "%",
    "Energy usage": "W",
    "Total usage": "W",
    "UV": "UV index",
    "Rssi numeric": "dBm",
}

DEVICE_CLASSES = {
    "Humidity": "humidity",
    "Temperature": "temperature",
    "Rssi numeric": "signal_strength",
    "Battery numeric": "battery",
}

SENSOR_STATUS_ON = [
    "Panic",
    "Motion",
    "Motion Tamper",
    "Light Detected",
    "Alarm",
    "Alarm Tamper",
]

SENSOR_STATUS_OFF = [
    "End Panic",
    "No Motion",
    "No Motion Tamper",
    "Dark Detected",
    "Normal",
    "Normal Tamper",
]


@dataclass
class Entity:
    domain: str
    id: str
    value_name: str

    @property
    def device_class(self):
        return DEVICE_CLASSES.get(self.value_name)

    @property
    def unit_of_measurement(self):
        return UNIT_OF_MEASUREMENTS.get(self.value_name, "")


def pkt_to_id(pkt):
    """Get a unique ID for a device from a packet"""
    return f"{pkt.packettype:x}-{pkt.subtype:x}-{pkt.id_string}"


def p(data):
    """Convert the payload to json"""
    return json.dumps(data)


def mqtt_publish(topic, payload):
    """Publich the payload to the MQTT topic"""
    LOG.debug(f"{topic}, {payload}")
    # mqttc.publish(topic, payload)


def bytes_to_pkt(bytes):
    pkt = lowlevel.parse(bytearray.fromhex(bytes))
    if pkt is None:
        raise Exception(f"Packet not valid? {pkt}")
    LOG.debug(pkt)
    return pkt


def pkt_to_event(pkt):
    """Parse a packet and convert it to a event"""

    if isinstance(pkt, lowlevel.SensorPacket):
        return rfxtrxmod.SensorEvent(pkt)
    elif isinstance(pkt, lowlevel.Status):
        return rfxtrxmod.StatusEvent(pkt)
    else:
        return rfxtrxmod.ControlEvent(pkt)


def get_event_domains(event):
    # we may want to support multiple domains in the future. Where a switch can
    # be both a binary_sensor and a switch
    domains = set()

    if isinstance(event, (rfxtrxmod.ControlEvent, rfxtrxmod.SensorEvent)):
        domains.add("sensor")
    if isinstance(event, rfxtrxmod.ControlEvent):
        domains.add("binary_sensor")
    elif isinstance(event, rfxtrxmod.SensorEvent) and event.values.get(
        "Sensor Status"
    ) in [
        *SENSOR_STATUS_ON,
        *SENSOR_STATUS_OFF,
    ]:
        domains.add("binary_sensor")

    return domains


def get_event_entities(event, config):
    for domain in get_event_domains(event):
        for name in event.values:
            entity = f"{config['name']} {name}".lower().replace(" ", "_")
            yield Entity(domain=domain, id=entity, value_name=name)


def setup_unknown_devices_sensor():
    topic = "homeassistant/sensor/rfxtrx2mqtt_unknown_device/config"
    payload = p(
        {
            "name": "RFXTRX2MQTT Unknown Device",
            "state_topic": UNKNOWN_DEVICE_SENSOR_TOPIC,
        }
    )
    mqtt_publish(topic, payload)


def event_callback(event):

    if not event.device.id_string:
        return

    if isinstance(event, (rfxtrxmod.StatusEvent, rfxtrxmod.ControlEvent)):
        return

    id = pkt_to_id(event.pkt)

    if id not in _REGISTRY:
        return

    LOG.debug(f"{_REGISTRY[id]}, {event.values}")

    if id not in _REGISTRY:

        topic = UNKNOWN_DEVICE_SENSOR_TOPIC
        payload = "ON"

    else:
        topic = "homeassistant/{domain}/{entity_id}/state"
        payload = "ON"

    mqtt_publish(topic, payload)


def setup_devices(config):

    for bytes, entity_config in config["devices"].items():

        pkt = bytes_to_pkt(bytes)
        event = pkt_to_event(pkt)
        id = pkt_to_id(pkt)

        if id in _REGISTRY:
            LOG.error(
                f"Found a device that appears to be a duplicate? From the packet; {bytes}"
            )
            continue

        if isinstance(entity_config, str):
            entity_config = {"name": entity_config}
        _REGISTRY[id] = entity_config

        for entity in get_event_entities(event, entity_config):

            topic = f"homeassistant/{entity.domain}/{entity.id}/config"
            payload = {
                "name": f"{entity_config['name']}",
                "unique_id": id,
                "state_topic": f"homeassistant/{entity.domain}/{entity.id}/state",
            }
            if entity.device_class:
                payload["device_class"] = entity.device_class
            if entity.unit_of_measurement:
                payload["unit_of_measurement"] = entity.unit_of_measurement
            mqtt_publish(topic, payload)


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def setup_logging(config):
    log = logging.getLogger()
    log.setLevel(logging.DEBUG if config.get("debug") else logging.INFO)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    ch.setFormatter(formatter)
    log.addHandler(ch)
    return log


def mqtt_connect(config):
    HOSTNAME = config["mqtt"]["host"]
    USERNAME = config["mqtt"]["username"]
    PASSWORD = config["mqtt"]["password"]

    mqttc.username_pw_set(USERNAME, PASSWORD)
    mqttc.connect(host=HOSTNAME)


def main():
    config = load_config()
    setup_logging(config)

    LOG.info("RFXTRX2MQTT")

    LOG.info("Setting up RFXTRX2MQTT")
    setup_unknown_devices_sensor()
    setup_devices(config)

    LOG.info("Waiting for events")
    device = "/dev/ttyUSB0"
    # Threads be running with this callback.
    rfx_object = rfxtrxmod.Connect(device, event_callback, debug=True)
    while rfx_object.transport.serial.is_open:
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except:
        LOG.exception("Crash")

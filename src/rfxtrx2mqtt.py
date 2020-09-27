import functools
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime

import paho.mqtt.client as mqtt
import RFXtrx as rfxtrxmod
import RFXtrx.lowlevel as lowlevel
import yaml

LOG = logging.getLogger("rfxtrx2mqtt")
CLIENT_ID = "rfxtrx2mqtt"
UNKNOWN_DEVICE_STATE_TOPIC = "sensor/rfxtrx2mqtt_unknown_device/state"
UNKNOWN_DEVICE_CONFIG_TOPIC = "sensor/rfxtrx2mqtt_unknown_device/config"

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


def _battery_convert(value):
    """Battery is given as a value between 0 and 9."""
    if value is None:
        return None
    return value * 10


def _rssi_convert(value):
    """Rssi is given as dBm value."""
    if value is None:
        return None
    return f"{value*8-120}"


STATE_TRANSFORMATION = {
    "Battery numeric": _battery_convert,
    "Rssi numeric": _rssi_convert,
}


@dataclass
class Entity:
    domain: str
    id: str
    value_name: str
    state: str

    @property
    def device_class(self):
        return DEVICE_CLASSES.get(self.value_name)

    @property
    def unit_of_measurement(self):
        return UNIT_OF_MEASUREMENTS.get(self.value_name, "")

    @property
    def config_topic(self):
        return f"{self.domain}/{self.id}/config"

    @property
    def state_topic(self):
        return f"{self.domain}/{self.id}/state"


def pkt_to_id(pkt):
    """Get a unique ID for a device from a packet"""
    return f"{pkt.packettype:x}-{pkt.subtype:x}-{pkt.id_string}"


def mqtt_publish(topic_prefix, topic, payload):
    """Publich the payload to the MQTT topic"""
    if not isinstance(payload, str):
        payload = json.dumps(payload)
    full_topic = f"{topic_prefix}/{topic}"
    LOG.debug(f"\n\tTOPIC   : {full_topic}\n\tPAYLOAD : {payload}")
    r = mqttc.publish(full_topic, payload, retain=True)
    if r.rc > 0:
        raise Exception(mqtt.error_string(r.rc))


def bytes_to_pkt(bytes):
    pkt = lowlevel.parse(bytearray.fromhex(bytes))
    if pkt is None:
        raise Exception(f"Packet not valid? {pkt}")
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
        for name, state in event.values.items():
            entity = f"{config['name']} {name}".lower().replace(" ", "_")

            if name in STATE_TRANSFORMATION:
                state = STATE_TRANSFORMATION[name](state)

            yield Entity(domain=domain, id=entity, value_name=name, state=state)


def setup_unknown_devices_sensor(config):
    if not config.get("publish_unknown"):
        LOG.info(
            "Unknown devices will be ignored. "
            "Set publish_unknown to True to process them"
        )
        return
    mqtt_publish(
        config["mqtt"]["prefix"],
        UNKNOWN_DEVICE_CONFIG_TOPIC,
        {
            "name": "RFXTRX2MQTT Unknown Device",
            "state_topic": f"{config['mqtt']['prefix']}/{UNKNOWN_DEVICE_STATE_TOPIC}",
        },
    )


def handle_unknown_devices(config, event):
    if not config.get("publish_unknown"):
        return
    event_str = "".join(f"{x:02x}" for x in event.data)
    LOG.info(
        f"Unknown device with event '{event_str}'. "
        f"Device: {event.device}. Values: {event.values}"
    )
    mqtt_publish(
        config["mqtt"]["prefix"],
        UNKNOWN_DEVICE_STATE_TOPIC,
        {
            "state": event_str,
            "device": str(event.device),
            "values": event.values,
        },
    )


def event_callback(config, event):

    if not event.device.id_string:
        return

    if isinstance(event, (rfxtrxmod.StatusEvent, rfxtrxmod.ControlEvent)):
        return

    id = pkt_to_id(event.pkt)

    if id not in _REGISTRY:
        return handle_unknown_devices(config, event)

    for entity in get_event_entities(event, _REGISTRY[id]):
        payload = str(entity.state)
        mqtt_publish(config["mqtt"]["prefix"], entity.state_topic, payload)


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

            payload = {
                "name": f"{entity_config['name']} {entity.value_name}",
                "unique_id": f"rfxtrx2mqtt-{id}-{entity.value_name.lower().replace(' ', '')}",
                "state_topic": f"{config['mqtt']['prefix']}/{entity.state_topic}",
            }
            if entity.device_class:
                payload["device_class"] = entity.device_class
            if entity.unit_of_measurement:
                payload["unit_of_measurement"] = entity.unit_of_measurement
            mqtt_publish(config["mqtt"]["prefix"], entity.config_topic, payload)


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
    mqtt_connect(config)
    setup_logging(config)

    LOG.info("RFXTRX2MQTT")

    LOG.info("Setting up RFXTRX2MQTT")
    setup_unknown_devices_sensor(config)
    setup_devices(config)

    LOG.info("Waiting for events")
    device = "/dev/ttyUSB0"
    # Threads be running with this callback.
    rfx_object = rfxtrxmod.Connect(
        device, functools.partial(event_callback, config), debug=True
    )
    while rfx_object.transport.serial.is_open:
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except:
        LOG.exception("Crash")

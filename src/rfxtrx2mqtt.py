import json
import time

import paho.mqtt.client as mqtt
import RFXtrx as rfxtrxmod
import RFXtrx.lowlevel as lowlevel
import yaml

CLIENT_ID = "rfxtrx2mqtt"

_REGISTRY = {}
mqttc = mqtt.Client(client_id=CLIENT_ID)


def _id(pkt):
    return (f"{pkt.packettype:x}", f"{pkt.subtype:x}", pkt.id_string)


def _payload(data):
    return json.dumps(data)


def publish(*args, **kwargs):
    print(args, kwargs)
    # mqttc.publish(*args, **kwargs)


def event_callback(event):

    if not event.device.id_string:
        return

    if isinstance(event, (rfxtrxmod.StatusEvent, rfxtrxmod.ControlEvent)):
        return

    id = _id(event.pkt)

    if id not in _REGISTRY:
        return

    print(_REGISTRY[id], event.values)

    if id not in _REGISTRY:

        topic = "homeassistant/sensor/rfxtrx2mqtt_unknown_device/state"
        payload = "ON"

    else:
        topic = "homeassistant/{domain}/{entity_id}/state"
        payload = "ON"

    publish(topic, payload)


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def _config(name, value):
    if name == "Temperature":
        return {"device_class": "temperature"}, value
    if name == "Humidity":
        return {"device_class": "humidity"}, value
    if name == "Battery numeric":
        return {"device_class": "battery"}, value
    if name == "Rssi numeric":
        return {"device_class": "signal_strength"}, value

    if name in ("Command", "Humidity status", "Humidity status numeric"):
        return name, value

    print(f"No handling for {name}: {value}")


def setup(config):

    topic = "homeassistant/sensor/rfxtrx2mqtt_unknown_device/config"
    payload = _payload(
        {
            "name": "RFXTRX2MQTT Unknown Device",
            "state_topic": "homeassistant/sensor/rfxtrx2mqtt_unknown_device/state",
        }
    )
    publish(topic, payload)

    for bytes, config in config["devices"].items():
        print(config)
        pkt = lowlevel.parse(bytearray.fromhex(bytes))
        if pkt is None:
            raise Exception(f"Packet not valid? {pkt}")

        if isinstance(pkt, lowlevel.SensorPacket):
            obj = rfxtrxmod.SensorEvent(pkt)
        elif isinstance(pkt, lowlevel.Status):
            obj = rfxtrxmod.StatusEvent(pkt)
        else:
            obj = rfxtrxmod.ControlEvent(pkt)

        id = _id(pkt)
        if isinstance(config, str):
            config = {"name": config}
        _REGISTRY[id] = config

        print(repr(obj.values))

        for name, value in obj.values.items():
            name, value = _config(name, value)
            topic = "homeassistant/{domain}/{entity_id}/config"
            payload = _payload(
                {
                    "name": f"{config['name']}",
                    "unique_id": id,
                    "unit_of_measurement": "",
                    "device_class": "",
                    "state_topic": "homeassistant/{domain}/{entity_id}/state",
                }
            )
            publish(topic, payload)


def main():
    print("RFXTRX2MQTT")
    config = load_config()

    device = "/dev/ttyUSB0"
    rfx_object = rfxtrxmod.Connect(device, None, debug=True)

    HOSTNAME = config["mqtt"]["host"]
    USERNAME = config["mqtt"]["username"]
    PASSWORD = config["mqtt"]["password"]

    mqttc.username_pw_set(USERNAME, PASSWORD)
    mqttc.connect(host=HOSTNAME)

    setup(config)

    # Threads be running with this callback.
    rfx_object.event_callback = event_callback

    while rfx_object.transport.serial.is_open:
        time.sleep(1)


if __name__ == "__main__":
    main()

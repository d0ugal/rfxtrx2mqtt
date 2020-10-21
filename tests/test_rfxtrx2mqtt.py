import pytest
import RFXtrx as rfxtrxmod
import rfxtrx2mqtt
import RFXtrx.lowlevel as lowlevel


def test_pkt_to_id():
    hex_ = "0a52011bf801007c4f0369"
    pkt = lowlevel.parse(bytearray.fromhex(hex_))
    assert rfxtrx2mqtt.pkt_to_id(pkt) == "52-1-f8:01"


def test_bytes_to_pkt():
    hex_ = "0a52013af801007c4f0369"
    pkt = rfxtrx2mqtt.bytes_to_pkt(hex_)
    assert isinstance(pkt, lowlevel.TempHumid)


def test_bytes_to_pkt_invalid():
    hex_ = "01"
    with pytest.raises(ValueError):
        pkt = rfxtrx2mqtt.bytes_to_pkt(hex_)


def test_pkt_to_event_sensor():
    hex_ = "0a52014ff801007d4f0369"
    pkt = rfxtrx2mqtt.bytes_to_pkt(hex_)
    event = rfxtrx2mqtt.pkt_to_event(pkt)
    assert isinstance(event, rfxtrxmod.SensorEvent)


def test_pkt_to_event_control():
    hex_ = "0a140001f573d710030070"
    pkt = rfxtrx2mqtt.bytes_to_pkt(hex_)
    event = rfxtrx2mqtt.pkt_to_event(pkt)
    assert isinstance(event, rfxtrxmod.ControlEvent)


def test_pkt_to_event_status():
    bytes_ = bytearray(
        b"\x0D\x01\x00\x01\x02\x53\x45"
        b"\x10"  # msg3: rsl
        b"\x0C"  # msg4: hideki lacrosse
        b"\x2F"  # msg5: x10 arc ac homeeasy oregon
        b"\x01"  # msg6: keeloq
        b"\x01\x00\x00"  # unused
    )
    pkt = rfxtrx2mqtt.bytes_to_pkt("".join(f"{x:02x}" for x in bytes_))
    event = rfxtrx2mqtt.pkt_to_event(pkt)
    assert isinstance(event, rfxtrxmod.StatusEvent)


def test_get_event_domains_sensor():
    hex_ = "0a52014ff801007d4f0369"
    pkt = rfxtrx2mqtt.bytes_to_pkt(hex_)
    event = rfxtrx2mqtt.pkt_to_event(pkt)
    assert rfxtrx2mqtt.get_event_domains(event) == {"sensor"}


def test_get_event_domains_control():
    hex_ = "0a140001f573d710030070"
    pkt = rfxtrx2mqtt.bytes_to_pkt(hex_)
    event = rfxtrx2mqtt.pkt_to_event(pkt)
    assert rfxtrx2mqtt.get_event_domains(event) == {"sensor", "binary_sensor"}


def test_get_event_entities():
    hex_ = "0a52014ff801007d4f0369"
    pkt = rfxtrx2mqtt.bytes_to_pkt(hex_)
    event = rfxtrx2mqtt.pkt_to_event(pkt)
    entities = list(rfxtrx2mqtt.get_event_entities(event, {"name": "testing"}))
    assert entities == [
        rfxtrx2mqtt.Entity(
            domain="sensor",
            id="testing_temperature",
            value_name="Temperature",
            state=12.5,
        ),
        rfxtrx2mqtt.Entity(
            domain="sensor", id="testing_humidity", value_name="Humidity", state=79
        ),
        rfxtrx2mqtt.Entity(
            domain="sensor",
            id="testing_humidity_status",
            value_name="Humidity status",
            state="wet",
        ),
        rfxtrx2mqtt.Entity(
            domain="sensor",
            id="testing_humidity_status_numeric",
            value_name="Humidity status numeric",
            state=3,
        ),
        rfxtrx2mqtt.Entity(
            domain="sensor",
            id="testing_battery_numeric",
            value_name="Battery numeric",
            state=90,
        ),
        rfxtrx2mqtt.Entity(
            domain="sensor",
            id="testing_rssi_numeric",
            value_name="Rssi numeric",
            state="-72",
        ),
    ]


def test_battery_convert():
    assert rfxtrx2mqtt._battery_convert(10) == 100
    assert rfxtrx2mqtt._battery_convert(None) == None
    assert rfxtrx2mqtt._battery_convert(2) == 20


def test_rssi_convert():
    assert rfxtrx2mqtt._rssi_convert(25) == "80"
    assert rfxtrx2mqtt._rssi_convert(None) == None


def test_entity_class():

    e = rfxtrx2mqtt.Entity(
        domain="sensor", id="testing_temperature", value_name="Temperature", state=20
    )

    assert e.device_class == "temperature"
    assert e.unit_of_measurement == "°C"
    assert e.config_topic == "sensor/testing_temperature/config"
    assert e.state_topic == "sensor/testing_temperature/state"


def test_setup_logging():
    rfxtrx2mqtt.setup_logging({"debug": True})

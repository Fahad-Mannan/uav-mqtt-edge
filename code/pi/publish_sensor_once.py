import json
import time
import getpass
import threading

import board
import adafruit_bmp280
import adafruit_mpu6050
import adafruit_ina219
import paho.mqtt.client as mqtt

BROKER = "192.168.1.4"
TOPIC = "uav/test"

i2c = board.I2C()

bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=0x77)
mpu = adafruit_mpu6050.MPU6050(i2c)
ina = adafruit_ina219.INA219(i2c)

payload = {
    "seq": 0,
    "timestamp_ns": time.time_ns(),
    "bmp280": {
        "temperature_c": bmp.temperature,
        "pressure_hpa": bmp.pressure
    },
    "mpu6050": {
        "accel_m_s2": mpu.acceleration,
        "gyro_rad_s": mpu.gyro
    },
    "ina219": {
        "bus_voltage_v": ina.bus_voltage,
        "current_ma": ina.current,
        "power_mw": ina.power
    }
}

password = getpass.getpass("MQTT password: ")
connected = threading.Event()
connection_ok = [False]

def on_connect(client, userdata, flags, reason_code, properties):
    connection_ok[0] = (reason_code == 0)
    connected.set()

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set("uavpi", password)
client.on_connect = on_connect

client.connect(BROKER, 1883, 30)
client.loop_start()

try:
    if not connected.wait(10) or not connection_ok[0]:
        raise RuntimeError("MQTT authentication or connection failed")

    message = json.dumps(payload)
    result = client.publish(TOPIC, message, qos=1)
    result.wait_for_publish(timeout=10)

    if not result.is_published():
        raise RuntimeError("MQTT publish was not acknowledged")

    print("Sensor message published successfully!")
    print(message)
finally:
    client.disconnect()
    client.loop_stop()

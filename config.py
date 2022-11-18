import serial
import logging

# dbus configuration

FIRMWARE_VERSION = 1  # value returned by getValue (getText returns string value reported by battery)
HARDWARE_VERSION = 1  # value returned by getValue (getText returns string value reported by battery)

CONNECTION = 'Modbus RTU'
PRODUCT_NAME = 'FIAMM 48TL Series Battery'
PRODUCT_ID = 0xB012   # assigned by victron
DEVICE_INSTANCE = 1
SERVICE_NAME_PREFIX = 'com.victronenergy.battery.'


# driver configuration

SOFTWARE_VERSION = '2.2.0'
UPDATE_INTERVAL = 2000   # milliseconds
LOG_LEVEL = logging.DEBUG

# modbus configuration

BASE_ADDRESS = 999
NO_OF_REGISTERS = 56
MAX_SLAVE_ADDRESS = 10


# RS 485 configuration

PARITY = serial.PARITY_NONE
TIMEOUT = 0.2  # seconds
BAUD_RATE = 115200
BYTE_SIZE = 8
STOP_BITS = 2
MODE = 'rtu'


# battery configuration

MAX_CHARGE_VOLTAGE = 56
MIN_BATTERY_VOLTAGE = 42

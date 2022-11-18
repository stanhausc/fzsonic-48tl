#!/usr/bin/python2 -u
# coding=utf-8

import re
import gobject
import sys
import logging

import config as cfg
import convert as c

import threading
from threading import  Lock

mutex = Lock()

from pymodbus.register_read_message import ReadInputRegistersResponse
from pymodbus.client.sync import ModbusSerialClient as Modbus
from pymodbus.other_message import ReportSlaveIdRequest
from pymodbus.exceptions import ModbusException
from pymodbus.pdu import ExceptionResponse

from dbus.mainloop.glib import DBusGMainLoop
from data import BatteryStatus, Signal, Battery, LedColor

from collections import Iterable
from os import path

app_dir = path.dirname(path.realpath(__file__))
sys.path.insert(1, path.join(app_dir, 'ext', 'velib_python'))

from vedbus import VeDbusService as DBus

# trick the pycharm type-checker into thinking Callable is in scope, not used at runtime
# noinspection PyUnreachableCode
if False:
	from typing import Callable


def init_signals(hardware_version, firmware_version, instance, n_batteries):
	# type: (str,str,int) -> Iterable[Signal]
	"""
	A Signal holds all information necessary for the handling of a
	certain datum (e.g. voltage) published by the battery.

	Signal(dbus_path, aggregate, get_value, get_text = str)

	dbus_path: str
		object_path on DBus where the datum needs to be published

	aggregate: Iterable[object] -> object
		function that combines the values of multiple batteries into one.
		e.g. sum for currents, or mean for voltages

	get_value: (BatteryStatus) -> object [optional]
		function to extract the datum from the modbus record,
		alternatively: a constant

	get_text: (object) -> unicode [optional]
		function to render datum to text, needed by DBus
		alternatively: a constant


	The conversion functions use the same parameters (e.g scale_factor, offset)
	as described in the document 'T48TLxxx ModBus Protocol Rev.7.1' which can
	be found in the /doc folder
	"""

	product_id_hex = '0x{0:04x}'.format(cfg.PRODUCT_ID)

	read_voltage = c.read_float(register=999,  scale_factor=0.01, offset=0)
	read_current = c.read_float(register=1000, scale_factor=0.01, offset=-10000)

	def read_power(status):
		return int(read_current(status) * read_voltage(status))

	def max_current(status):
		return status.battery.ampere_hours/2

	product_name = cfg.PRODUCT_NAME
	if n_batteries > 1:
		product_name = cfg.PRODUCT_NAME + ' x' + str(n_batteries)

	return [
		Signal('/Dc/0/Voltage', c.mean, get_value=read_voltage, get_text=c.append_unit('V')),
		Signal('/Dc/0/Current', sum,    get_value=read_current, get_text=c.append_unit('A')),
		Signal('/Dc/0/Power',   sum,    get_value=read_power,   get_text=c.append_unit('W')),

		Signal('/BussVoltage',      c.mean, c.read_float(register=1001, scale_factor=0.01, offset=0),    c.append_unit('V')),
		Signal('/Soc',              c.mean, c.read_float(register=1053, scale_factor=0.1,  offset=0),    c.append_unit('%')),
		Signal('/Dc/0/Temperature', c.mean, c.read_float(register=1003, scale_factor=0.1,  offset=-400), c.append_unit(u'°C')),

		Signal('/Diagnostics/WarningFlags', c.first, c.read_hex_string(register=1005, count=4)),
		Signal('/Diagnostics/AlarmFlags',   c.first, c.read_hex_string(register=1009, count=4)),
		Signal('/Diagnostics/BmsVersion',   c.first, lambda s: s.battery.bms_version),

		Signal('/Diagnostics/LedStatus/Red',   c.first, c.read_led_state(register=1004, led=LedColor.red)),
		Signal('/Diagnostics/LedStatus/Blue',  c.first, c.read_led_state(register=1004, led=LedColor.blue)),
		Signal('/Diagnostics/LedStatus/Green', c.first, c.read_led_state(register=1004, led=LedColor.green)),
		Signal('/Diagnostics/LedStatus/Amber', c.first, c.read_led_state(register=1004, led=LedColor.amber)),

		Signal('/Diagnostics/IoStatus/MainSwitchClosed',       any, c.read_bool(register=1013, bit=0)),
		Signal('/Diagnostics/IoStatus/AlarmOutActive',         any, c.read_bool(register=1013, bit=1)),
		Signal('/Diagnostics/IoStatus/InternalFanActive',      any, c.read_bool(register=1013, bit=2)),
		Signal('/Diagnostics/IoStatus/VoltMeasurementAllowed', any, c.read_bool(register=1013, bit=3)),
		Signal('/Diagnostics/IoStatus/AuxRelay',               any, c.read_bool(register=1013, bit=4)),
		Signal('/Diagnostics/IoStatus/RemoteState',            any, c.read_bool(register=1013, bit=5)),
		Signal('/Diagnostics/IoStatus/HeaterOn',               any, c.read_bool(register=1013, bit=6)),
		
		# Two Level Alarms: 0=OK, 1=Warning, 2=Alarm
		Signal('/Alarms/LowVoltage',            max, c.read_alarm(warn_reg=1005, warn_bit=6,  alarm_reg=1009, alarm_bit=7)),  # Warn Low VBus < 40V (VBm1) / Alarm if < 39V (VBm2)
		Signal('/Alarms/HighVoltage',           max, c.read_alarm(warn_reg=1005, warn_bit=8,  alarm_reg=1009, alarm_bit=9)),  # Warn High VBus > 60V(VBM1) / Alarm if > 65V (VMB2)
		Signal('/Alarms/LowSoc',                max, c.read_alarm(warn_reg=1005, warn_bit=32, alarm_reg=1005, alarm_bit=35)), # Warn if not enough charging power is available on Vbus (BLPW) / Alarm if string_SOC < 5Ah (Ah_W)
		Signal('/Alarms/HighChargeCurrent',     max, c.read_alarm(warn_reg=1005, warn_bit=26, alarm_reg=1009, alarm_bit=27)), # Warn if string charge current > 9A (iCM1) / Alarm > 10A
		Signal('/Alarms/HighDischargeCurrent',  max, c.read_alarm(warn_reg=1005, warn_bit=10, alarm_reg=1009, alarm_bit=11)), # Warn if Ibatt_Discharge > 151A (IDM1) / Alarm > 160A
		Signal('/Alarms/CellImbalance',         max, c.read_alarm(warn_reg=1005, warn_bit=30, alarm_reg=1009, alarm_bit=31)), # Warn if String voltages unbalance (MID1) / Alarm (MID2)
		Signal('/Alarms/InternalFailure',       max, c.read_alarm(warn_reg=1009, warn_bit=20, alarm_reg=1009, alarm_bit=19)), # Warn if Hardware protection system is activated (HWEM) / Alarm if BMS hw fails (HWFL)
		Signal('/Alarms/HighChargeTemperature', max, c.read_alarm(warn_reg=1005, warn_bit=1,  alarm_reg=1009, alarm_bit=2)),  # Warn if BMS Temp > 70ºC (TaM1) / Alarm > 85ºC (TaM2)
		Signal('/Alarms/LowCellVoltage',        max, c.read_alarm(warn_reg=1009, warn_bit=22, alarm_reg=1009, alarm_bit=23)), # Warn if Vstring < 39V (vsm1) / Alarm < 34V (vsm2)
		Signal('/Alarms/LowTemperature',        max, c.read_alarm(warn_reg=1009, warn_bit=3,  alarm_reg=1009, alarm_bit=3)),  # Alarm if low battery internal temperature is detected (Tbm)
		Signal('/Alarms/HighTemperature',       max, c.read_alarm(warn_reg=1005, warn_bit=4,  alarm_reg=1009, alarm_bit=5)),  # Warn if temp > 340ºC (TbM1) / Alarm > 350�
		
		Signal('/Mgmt/ProcessName',    c.first, __file__),
		Signal('/Mgmt/ProcessVersion', c.first, cfg.SOFTWARE_VERSION),
		Signal('/Mgmt/Connection',     c.first, cfg.CONNECTION),
		# Signal('/DeviceInstance',      c.first, cfg.DEVICE_INSTANCE),
		Signal('/DeviceInstance',      c.first, instance + cfg.DEVICE_INSTANCE),
		Signal('/ProductName',         c.first, product_name),
		Signal('/ProductId',           c.first, cfg.PRODUCT_ID, product_id_hex),

		# see protocol doc page 7
		Signal('/Info/MaxDischargeCurrent', sum, max_current, c.append_unit('A')),
		Signal('/Info/MaxChargeCurrent',    sum, max_current, c.append_unit('A')),
		Signal('/Info/MaxChargeVoltage',    min, cfg.MAX_CHARGE_VOLTAGE, c.append_unit('V')),
		Signal('/Info/BatteryLowVoltage',   max, cfg.MIN_BATTERY_VOLTAGE, c.append_unit('V')),

		Signal('/Connected', c.first, 1),

		Signal('/FirmwareVersion', c.first, cfg.FIRMWARE_VERSION, firmware_version),
		Signal('/HardwareVersion', c.first, cfg.HARDWARE_VERSION, hardware_version)
		]


def init_modbus(tty):
	# type: (str) -> Modbus

	logging.debug('initializing Modbus')

	return Modbus(
		port='/dev/' + tty,
		method=cfg.MODE,
		baudrate=cfg.BAUD_RATE,
		stopbits=cfg.STOP_BITS,
		bytesize=cfg.BYTE_SIZE,
		timeout=cfg.TIMEOUT,
		parity=cfg.PARITY)


def init_dbus(tty, signals):
	# type: (str, Iterable[Signal]) -> DBus

	logging.debug('initializing DBus service')
	dbus = DBus(servicename=cfg.SERVICE_NAME_PREFIX + tty)

	logging.debug('initializing DBus paths')
	for signal in signals:
		init_dbus_path(dbus, signal)

	return dbus


# noinspection PyBroadException
def try_get_value(sig):
	# type: (Signal) -> object
	try:
		return sig.get_value(None)
	except:
		return None


def init_dbus_path(dbus, sig):
	# type: (DBus, Signal) -> ()

	dbus.add_path(
		sig.dbus_path,
		try_get_value(sig),
		gettextcallback=lambda _, v: sig.get_text(v))


def init_main_loop():
	# type: () -> DBusGMainLoop
	logging.debug('initializing DBusGMainLoop Loop')
	DBusGMainLoop(set_as_default=True)
	return gobject.MainLoop()


def report_slave_id(modbus, slave_address):
	# type: (Modbus, int) -> str

	slave = str(slave_address)

	logging.debug('requesting slave id from node ' + slave)

	try:
		mutex.acquire()
		modbus.connect()

		request = ReportSlaveIdRequest(unit=slave_address)
		response = modbus.execute(request)

		if response is ExceptionResponse or issubclass(type(response), ModbusException):
			raise Exception('failed to get slave id from ' + slave + ' : ' + str(response))

		return response.identifier

	finally:
		modbus.close()
		mutex.release()


def identify_battery(modbus, slave_address):
	# type: (Modbus, int) -> Battery

	logging.info('identifying battery...')

	hardware_version, bms_version, ampere_hours = parse_slave_id(modbus, slave_address)
	firmware_version = read_firmware_version(modbus, slave_address)

	specs = Battery(
		slave_address=slave_address,
		hardware_version=hardware_version,
		firmware_version=firmware_version,
		bms_version=bms_version,
		ampere_hours=ampere_hours)

	logging.info('battery identified:\n{0}'.format(str(specs)))

	return specs


def identify_batteries(modbus):
	# type: (Modbus) -> list[Battery]

	def _identify_batteries():
		address_range = range(2, cfg.MAX_SLAVE_ADDRESS + 2)

		for slave_address in address_range:
			try:
				yield identify_battery(modbus, slave_address)
			except Exception as e:
				logging.info('failed to identify battery at {0} : {1}'.format(str(slave_address), str(e)))

	return list(_identify_batteries())  # force that lazy iterable!


def parse_slave_id(modbus, slave_address):
	# type: (Modbus, int) -> (str, str, int)

	slave_id = report_slave_id(modbus, slave_address)

	sid = re.sub(r'[^\x20-\x7E]', '', slave_id)  # remove weird special chars

	match = re.match('(?P<hw>48TL(?P<ah>\d+)) *(?P<bms>.*)', sid)

	if match is None:
		raise Exception('no known battery found')

	return match.group('hw'), match.group('bms'), int(match.group('ah'))


def read_firmware_version(modbus, slave_address):
	# type: (Modbus, int) -> str

	logging.debug('reading firmware version')

	try:
		mutex.acquire()
		modbus.connect()

		response = read_modbus_registers(modbus, slave_address, base_address=1054, count=1)
		register = response.registers[0]

		return '{0:0>4X}'.format(register)

	finally:
		modbus.close()  # close in any case
		mutex.release()


def read_modbus_registers(modbus, slave_address, base_address=cfg.BASE_ADDRESS, count=cfg.NO_OF_REGISTERS):
	# type: (Modbus, int) -> ReadInputRegistersResponse

	logging.debug('requesting modbus registers {0}-{1}'.format(base_address, base_address + count))

	return modbus.read_input_registers(
		address=base_address,
		count=count,
		unit=slave_address)


def read_battery_status(modbus, battery):
	# type: (Modbus, Battery) -> BatteryStatus
	"""
	Read the modbus registers containing the battery's status info.
	"""

	logging.debug('reading battery status')

	try:
		mutex.acquire()
		modbus.connect()
		data = read_modbus_registers(modbus, battery.slave_address)
		return BatteryStatus(battery, data.registers)

	finally:
		modbus.close()  # close in any case
		mutex.release()


def publish_values(dbus, signals, statuses):
	# type: (DBus, Iterable[Signal], Iterable[BatteryStatus]) -> ()

	for s in signals:
		values = [s.get_value(status) for status in statuses]
		dbus[s.dbus_path] = s.aggregate(values)


def update(modbus, batteries, dbus, signals):
	# type: (Modbus, Iterable[Battery], DBus, Iterable[Signal]) -> bool

	"""
	Main update function

	1. requests status record each battery via modbus,
	2. parses the data using Signal.get_value
	3. aggregates the data from all batteries into one datum using Signal.aggregate
	4. publishes the data on the dbus
	"""

	logging.debug('starting update cycle')

	statuses = [read_battery_status(modbus, battery) for battery in batteries]

	publish_values(dbus, signals, statuses)

	logging.debug('finished update cycle\n')
	return True


def print_usage():
	print ('Usage:   ' + __file__ + ' <serial device>')
	print ('Example: ' + __file__ + ' ttyUSB0')


def parse_cmdline_args(argv):
	# type: (list[str]) -> str

	if len(argv) == 0:
		logging.info('missing command line argument for tty device')
		print_usage()
		sys.exit(1)

	return argv[0]


alive = True   # global alive flag, watchdog_task clears it, update_task sets it


def create_update_task(modbus, dbus, batteries, signals, main_loop):
	# type: (Modbus, DBus, Iterable[Battery], Iterable[Signal], DBusGMainLoop) -> Callable[[],bool]
	"""
	Creates an update task which runs the main update function
	and resets the alive flag
	"""

	def update_task():
		# type: () -> bool

		global alive

		alive = update(modbus, batteries, dbus, signals)

		if not alive:
			logging.info('update_task: quitting main loop because of error')
			main_loop.quit()

		return alive

	return update_task


def create_watchdog_task(main_loop):
	# type: (DBusGMainLoop) -> Callable[[],bool]
	"""
	Creates a Watchdog task that monitors the alive flag.
	The watchdog kills the main loop if the alive flag is not periodically reset by the update task.
	Who watches the watchdog?
	"""
	def watchdog_task():
		# type: () -> bool

		global alive

		if alive:
			logging.debug('watchdog_task: update_task is alive')
			alive = False
			return True
		else:
			logging.info('watchdog_task: killing main loop because update_task is no longer alive')
			main_loop.quit()
			return False

	return watchdog_task

def expose_battery(bat, bat_number, modbus, main_loop):
	signals = init_signals(bat.hardware_version, bat.firmware_version,bat_number, 1)

	dbus = init_dbus("bat_" + str( bat_number ), signals)
	batteries = []
	batteries.append(bat)
	update_task = create_update_task(modbus, dbus, batteries, signals, main_loop)
	watchdog_task = create_watchdog_task(main_loop)

	gobject.timeout_add(cfg.UPDATE_INTERVAL * 2, watchdog_task)  # add watchdog first
	gobject.timeout_add(cfg.UPDATE_INTERVAL, update_task)        # call update once every update_interval
	dbus.__del__



def main(argv):
	# type: (list[str]) -> ()

	logging.basicConfig(level=cfg.LOG_LEVEL)
	logging.info('starting ' + __file__)

	tty = parse_cmdline_args(argv)
	modbus = init_modbus(tty)

	batteries = identify_batteries(modbus)

	n = len(batteries)

	logging.info('found ' + str(n) + (' battery' if n == 1 else ' batteries'))

	if n <= 0:
		sys.exit(2)


	main_loop = init_main_loop()      # must run before init_dbus because gobject does some global magic
	threads = []
	i = 0
	for bat in batteries: 
		threads.append(threading.Thread(target = expose_battery, args = (bat, i, modbus, main_loop)))
		i = i+1

	for thread in threads:
		thread.start();
	
	for thread in threads:
		thread.join()

	logging.info('starting gobject.MainLoop')
	main_loop.run()
	logging.info('gobject.MainLoop was shut down')


	
	sys.exit(0xFF)  # reaches this only on error


if __name__ == "__main__":
	main(sys.argv[1:])


from collections import Iterable

# trick the pycharm type-checker into thinking Callable is in scope, not used at runtime
# noinspection PyUnreachableCode
if False:
	from typing import Callable


class LedState(object):
	"""
	from page 6 of the '48TLxxx ModBus Protocol doc'
	"""
	off = 0
	on = 1
	blinking_slow = 2
	blinking_fast = 3


class LedColor(object):
	green = 0
	amber = 1
	blue = 2
	red = 3


class Signal(object):

	def __init__(self, dbus_path, aggregate, get_value, get_text=None):
		# type: (str, Callable[[Iterable[object]],object], Callable[[BatteryStatus],object] | object, Callable[[object],unicode] | object)->None
		"""
		A Signal holds all information necessary for the handling of a
		certain datum (e.g. voltage) published by the battery.

		:param dbus_path: str
			object_path on DBus where the datum needs to be published

		:param aggregate: Iterable[object] -> object
			function that combines the values of multiple batteries into one.
			e.g. sum for currents, or mean for voltages

		:param get_value: (BatteryStatus) -> object
			function to extract the datum from the modbus record,
			alternatively: a constant

		:param get_text: (object) -> unicode [optional]
			function to render datum to text, needed by DBus
			alternatively: a constant
		"""

		self.dbus_path = dbus_path
		self.aggregate = aggregate
		self.get_value = get_value if callable(get_value) else lambda _: get_value
		self.get_text = get_text if callable(get_text) else lambda _: str(get_text)

		# if no 'get_text' provided use 'default_text' if available, otherwise str()
		if get_text is None:
			self.get_text = str


class Battery(object):

	""" Data record to hold hardware and firmware specs of the battery """

	def __init__(self, slave_address, hardware_version, firmware_version, bms_version, ampere_hours):
		# type: (int, str, str, str, int) -> None
		self.slave_address = slave_address
		self.hardware_version = hardware_version
		self.firmware_version = firmware_version
		self.bms_version = bms_version
		self.ampere_hours = ampere_hours

	def __str__(self):
		return 'slave address = {0}\nhardware version = {1}\nfirmware version = {2}\nbms version = {3}\nampere hours = {4}'.format(
			self.slave_address, self.hardware_version, self.firmware_version, self.bms_version, str(self.ampere_hours))


class BatteryStatus(object):
	"""
	record holding the current status of a battery
	"""
	def __init__(self, battery, modbus_data):
		# type: (Battery, list[int]) -> None

		self.battery = battery
		self.modbus_data = modbus_data

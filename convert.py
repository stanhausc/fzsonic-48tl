from collections import Iterable

import config as cfg
from data import LedState, BatteryStatus

# trick the pycharm type-checker into thinking Callable is in scope, not used at runtime
# noinspection PyUnreachableCode
if False:
	from typing import Callable

def read_bool(register, bit):
	# type: (int, int) -> Callable[[BatteryStatus], bool]

	def get_value(status):
		# type: (BatteryStatus) -> bool
		value = status.modbus_data[register - cfg.BASE_ADDRESS]
		return value & (1 << bit) > 0

	return get_value

def read_alarm(warn_reg, warn_bit, alarm_reg, alarm_bit):
	# type: (int, int, int, int) -> Callable[[BatteryStatus], int]

	def get_value(status):
		# type: (BatteryStatus) -> int
		warn_offset =  warn_bit / 16
		wbit = warn_bit % 16
		
		warn_data = status.modbus_data[warn_reg+warn_offset - cfg.BASE_ADDRESS]
		warn_value = warn_data & (1 << wbit) > 0
		
		alarm_offset = alarm_bit / 16
		abit = alarm_bit % 16
		
		alarm_data = status.modbus_data[alarm_reg+alarm_offset - cfg.BASE_ADDRESS]
		alarm_value = alarm_data & ( 1 << abit) > 0
		
		if alarm_value:
			return 2
		elif warn_value:
			return 1
		return 0
	return get_value


def read_float(register, scale_factor=1.0, offset=0.0):
	# type: (int, float, float) -> Callable[[BatteryStatus], float]

	def get_value(status):
		# type: (BatteryStatus) -> float
		value = status.modbus_data[register - cfg.BASE_ADDRESS]

		if value >= 0x8000:    # convert to signed int16
			value -= 0x10000   # fiamm stores their integers signed AND with sign-offset @#%^&!

		return (value + offset) * scale_factor

	return get_value


def read_hex_string(register, count):
	# type: (int, int) -> Callable[[BatteryStatus], str]
	"""
	reads count consecutive modbus registers from start_address,
	and returns a hex representation of it:
	e.g. for count=4: DEAD BEEF DEAD BEEF.
	"""
	start = register - cfg.BASE_ADDRESS
	end = start + count

	def get_value(status):
		# type: (BatteryStatus) -> str
		return ' '.join(['{0:0>4X}'.format(x) for x in status.modbus_data[start:end]])

	return get_value


def read_led_state(register, led):
	# type: (int, int) -> Callable[[BatteryStatus], int]

	read_lo = read_bool(register, led * 2)
	read_hi = read_bool(register, led * 2 + 1)

	def get_value(status):
		# type: (BatteryStatus) -> int

		lo = read_lo(status)
		hi = read_hi(status)

		if hi:
			if lo:
				return LedState.blinking_fast
			else:
				return LedState.blinking_slow
		else:
			if lo:
				return LedState.on
			else:
				return LedState.off

	return get_value


def append_unit(unit):
	# type: (unicode) -> Callable[[unicode], unicode]

	def get_text(v):
		# type: (unicode) -> unicode
		return "{0}{1}".format(str(v), unit)

	return get_text


def mean(numbers):
	# type: (Iterable[float] | Iterable[int]) -> float
	return float(sum(numbers)) / len(numbers)



def first(ts):
	return next(t for t in ts)



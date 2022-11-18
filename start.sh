#!/bin/bash

. /opt/victronenergy/serial-starter/run-service.sh

app=/opt/victronenergy/dbus-fzsonick-48tl/dbus-fzsonick-48tl.py
args="$tty"
start $args

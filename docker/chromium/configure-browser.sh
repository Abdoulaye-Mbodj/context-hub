#!/bin/sh
set -eu

install -d -o abc -g abc -m 755 /config/.config/labwc
install -o abc -g abc -m 755 /opt/context-hub/labwc-autostart /config/.config/labwc/autostart

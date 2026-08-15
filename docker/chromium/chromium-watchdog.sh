#!/bin/sh

while true; do
    wrapped-chromium --enable-features=UseOzonePlatform --ozone-platform=wayland ${CHROME_CLI:-https://mail.google.com/}
    exit_code=$?
    echo "[context-hub] Chromium arrêté (code $exit_code), redémarrage dans 1 seconde"
    sleep 1
done

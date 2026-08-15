FROM lscr.io/linuxserver/chromium:latest

# Optional local TLS roots (for example antivirus/proxy inspection CAs) are
# deliberately excluded from Git but included in local Docker builds.
COPY certs/ /usr/local/share/ca-certificates/
RUN apt-get update \
    && apt-get install -y --no-install-recommends libnss3-tools \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY docker/chromium/import-local-cas.sh /custom-cont-init.d/20-import-local-cas
COPY docker/chromium/configure-browser.sh /custom-cont-init.d/30-configure-browser
COPY docker/chromium/chromium-watchdog.sh /usr/local/bin/context-hub-chromium-watchdog
COPY docker/chromium/labwc-autostart /opt/context-hub/labwc-autostart
RUN chmod 755 \
    /custom-cont-init.d/20-import-local-cas \
    /custom-cont-init.d/30-configure-browser \
    /usr/local/bin/context-hub-chromium-watchdog \
    /opt/context-hub/labwc-autostart

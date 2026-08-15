#!/bin/sh
set -eu

nss_db=/config/.local/share/pki/nssdb
mkdir -p "$nss_db"
chown -R abc:abc /config/.local/share/pki

if [ ! -f "$nss_db/cert9.db" ]; then
    su -s /bin/sh abc -c "certutil -N -d sql:$nss_db --empty-password"
fi

for ca_file in /usr/local/share/ca-certificates/*.crt; do
    [ -f "$ca_file" ] || continue
    nickname="context-hub-$(basename "$ca_file" .crt)"
    su -s /bin/sh abc -c "certutil -D -d sql:$nss_db -n '$nickname'" >/dev/null 2>&1 || true
    su -s /bin/sh abc -c "certutil -A -d sql:$nss_db -n '$nickname' -t 'C,,' -i '$ca_file'"
done

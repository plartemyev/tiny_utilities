#!/bin/sh
# archinstaller: use DHCP-provided DNS whenever it answers; ignore it
# (systemd-resolved fallback resolvers take over) while it does not.
iface="$1"; event="$2"
case "$event" in
    up|reapply|dhcp4-change|dhcp6-change|manual) ;;
    *) exit 0 ;;
esac
case "$3" in
    --worker) ;;
    *)  # dispatcher context: NM kills slow scripts, probe in the background
        setsid "$0" "$iface" "$event" --worker >/dev/null 2>&1 </dev/null &
        exit 0 ;;
esac
exec 9>/run/archinstaller-dns-fallback.lock || exit 0
flock -n 9 || exit 0
servers="${DHCP4_DOMAIN_NAME_SERVERS:-} ${DHCP6_DOMAIN_NAME_SERVERS:-}"
if [ -z "$(printf '%s' "$servers" | tr -d ' \t')" ]; then
    servers="$(nmcli -f DHCP4 dev show "$iface" 2>/dev/null \
        | sed -n 's/^[^:]*: *domain_name_servers = //p')"
fi
[ -n "$servers" ] || exit 0
alive=""
for s in $servers; do
    if timeout 4 drill archlinux.org @"$s" >/dev/null 2>&1; then
        alive=1; break
    fi
done
mode=no; [ -n "$alive" ] || mode=yes
conn="${CONNECTION_ID:-$(nmcli -g GENERAL.CONNECTION dev show "$iface" 2>/dev/null)}"
[ -n "$conn" ] || exit 0
[ "$(nmcli -g ipv4.ignore-auto-dns con show "$conn" 2>/dev/null)" = "$mode" ] && \
    [ "$(nmcli -g ipv6.ignore-auto-dns con show "$conn" 2>/dev/null)" = "$mode" ] && exit 0
nmcli con modify "$conn" ipv4.ignore-auto-dns "$mode" ipv6.ignore-auto-dns "$mode" || exit 0
nmcli dev reapply "$iface" >/dev/null 2>&1

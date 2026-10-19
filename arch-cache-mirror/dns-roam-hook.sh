#!/bin/bash
# dns-roam-hook.sh - NetworkManager dispatcher hook keeping the
# arch-cache-mirror container's resolvers current across host network
# roams (see README "DNS resilience").
#
# Docker's embedded resolver snapshots the host's nameservers at container
# start and never refreshes them, so a roaming host used to leave the
# mirror querying a dead resolver (upstream db refreshes failed and stale
# dbs got served silently).  The container instead bind-mounts
# dns-resolv.conf (glibc semantics, hot-reloadable), and this hook
# rewrites that file in place on every network event: DNS servers of the
# current connection first (each probed alive), public fallbacks last.
# glibc re-reads the file on change, so the running container picks the
# rewrite up immediately - no restart, in-flight downloads are untouched.
#
# Install:
#   sudo install -m755 dns-roam-hook.sh \
#        /etc/NetworkManager/dispatcher.d/90-arch-cache-mirror-dns
# Test run:
#   sudo /etc/NetworkManager/dispatcher.d/90-arch-cache-mirror-dns <iface> manual
#
# In-place writes ONLY (printf > file): renaming (mv, sed -i) swaps the
# inode out from under the bind mount and the container would keep seeing
# the old content.

set -u

iface="${1:-}"
event="${2:-}"
case "$event" in
    up|reapply|dhcp4-change|dhcp6-change|manual) ;;
    *) exit 0 ;;
esac

# serialize overlapping events (NM may fire several in quick succession);
# a busy lock means another run is already doing this work (ACM_DNS_LOCK
# overrides the path, e.g. for test runs without root)
exec 9>"${ACM_DNS_LOCK:-/run/arch-cache-mirror-dns.lock}"
flock -n 9 || exit 0

# the container's mounted resolv.conf, resolved from the running container
# itself (no hardcoded repo paths; nothing to do without the container)
target="$(docker inspect arch-cache-mirror --format \
    '{{range .Mounts}}{{if eq .Destination "/etc/resolv.conf"}}{{.Source}}{{end}}{{end}}' \
    2>/dev/null)"
if [ -z "$target" ] || [ ! -f "$target" ]; then
    exit 0
fi

# DNS servers of the current connection: dispatcher env first, nmcli
# fallback (same sources as archinstaller's DNS fallback hook; the sed
# guards exclude the requested_* echo lines)
servers="${DHCP4_DOMAIN_NAME_SERVERS:-} ${DHCP6_DOMAIN_NAME_SERVERS:-}"
if [ -z "${servers// /}" ] && [ -n "$iface" ]; then
    for grp in DHCP4 DHCP6; do
        servers="$servers $(nmcli -f "$grp" dev show "$iface" 2>/dev/null \
            | sed -n -e 's/.*[^_a-z]domain_name_servers *= *//p' \
                    -e 's/.*[^_a-z]ip6_domain_name_servers *= *//p' \
            | tr ' ' '\n')"
    done
fi

probe() {  # probe <server>: an answer for archlinux.org within 1s
    if command -v drill >/dev/null 2>&1; then
        timeout 1 drill archlinux.org @"$1" >/dev/null 2>&1
    else
        timeout 4 dig +time=1 +tries=1 archlinux.org @"$1" >/dev/null 2>&1
    fi
}

# alive lease servers first, then public fallbacks; glibc reads at most
# MAXNS=3 nameservers, so cap the list there
nameservers=""
for s in $servers 1.1.1.1 8.8.8.8; do
    case " $nameservers " in *" $s "*) continue ;; esac
    case "$s" in
        1.1.1.1|8.8.8.8) ;;          # fallbacks are taken as-is
        *) probe "$s" || continue ;;
    esac
    nameservers="$nameservers $s"
    set -- $nameservers
    [ "$#" -ge 3 ] && break
done
if [ -z "${nameservers// /}" ]; then
    exit 0  # nothing usable; leave the current file alone
fi

body=""
for s in $nameservers; do
    body="${body}nameserver $s
"
done
content="# managed by NetworkManager dispatcher hook dns-roam-hook.sh -
# rewritten on network events: current connection's DNS servers first
# (probed alive), public fallbacks last.  Static default: the repo's
# dns-resolv.conf.example.  In-place writes only (see that file's header), at
# most 3 nameservers (glibc MAXNS).
${body}options timeout:1 attempts:2
"

# idempotence: skip the rewrite (and the log line) when nothing changed
if printf '%s' "$content" | cmp -s - "$target"; then
    exit 0
fi
printf '%s' "$content" > "$target"
logger -t arch-cache-mirror-dns "resolvers after $event on $iface:$nameservers"

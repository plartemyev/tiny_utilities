#!/usr/bin/env bash
# uninstall.sh - undo setup.sh: restore rewired VM NICs, remove the libvirt
# network, the persisted sysctls and the state directory. Run with sudo.
set -euo pipefail

NET_NAME="${NET_NAME:-lan-routed}"
STATE_DIR="${STATE_DIR:-/var/lib/lan-expose}"

die() { echo "ERROR: $*" >&2; exit 1; }
vsh() { virsh -c qemu:///system "$@"; }

[ "$(id -u)" -eq 0 ] || die "run with sudo"
if [ ! -f "$STATE_DIR/state.env" ]; then
    die "no state at $STATE_DIR; manual cleanup: virsh net-destroy/undefine $NET_NAME," \
        "rm /etc/sysctl.d/30-$NET_NAME-proxyarp.conf"
fi
# shellcheck source=/dev/null
. "$STATE_DIR/state.env"

restore_vms() {
    if [ ! -f "$STATE_DIR/rewired.tsv" ]; then
        echo "   no rewired VMs recorded"
        return 0
    fi
    while IFS=$'\t' read -r vm type source model mac; do
        [ -n "$vm" ] || continue
        echo "   $vm: $NET_NAME -> $source"
        if ! vsh detach-interface "$vm" --type network --mac "$mac" --config >/dev/null; then
            echo "   WARN: could not detach NIC $mac from $vm (already gone?)"
            continue
        fi
        if ! vsh attach-interface "$vm" --type "$type" --source "$source" \
            --model "$model" --mac "$mac" --config >/dev/null; then
            echo "   WARN: could not re-attach NIC $mac to $source on $vm; fix with virsh edit"
        fi
    done < "$STATE_DIR/rewired.tsv"
}

echo "== restoring VM NICs"
restore_vms
echo "== removing libvirt network $NET_NAME"
vsh net-destroy "$NET_NAME" >/dev/null 2>&1 || true
vsh net-undefine "$NET_NAME"
echo "== removing $SYSCTL_FILE"
rm -f "$SYSCTL_FILE"
rm -rf "$STATE_DIR"
echo "DONE (net.ipv4.ip_forward intentionally left enabled: shared by docker/libvirt)."

#!/usr/bin/env bash
# setup.sh - expose libvirt guests on the host's Wi-Fi LAN (routed + proxy ARP).
# See README.md for the design and the caveats. Companion: uninstall.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/network.xml.tpl"

NET_NAME="${NET_NAME:-lan-routed}"
STATE_DIR="${STATE_DIR:-/var/lib/lan-expose}"
REWIRE_FROM="${REWIRE_FROM:-default}"
IFACE="${IFACE:-}"
SLICE_CIDR="${SLICE_CIDR:-}"

NO_REWIRE=0
NO_TEST=0
FORCE=0
DRY_RUN=0
DRIFT=0

usage() {
    cat <<'EOF'
setup.sh - expose libvirt guests on the host's Wi-Fi LAN (routed + proxy ARP)

Usage:
  sudo ./setup.sh [options]      apply (define network, sysctls, rewire VMs, verify)
  ./setup.sh --dry-run           preview discovery, rendered XML and planned actions

Options:
  --dry-run    change nothing
  --no-rewire  do not rewire VM NICs (only create the network)
  --no-test    skip the end-to-end simulated-guest test
  --force      redefine the network even if the live one drifted from discovery
  -h, --help   this help

Environment overrides:
  NET_NAME=lan-routed          libvirt network name
  IFACE=<iface>                upstream interface (default: default-route wireless iface)
  SLICE_CIDR=<a.b.c.d/p>       guest slice (default: top-aligned /27 of the LAN subnet)
  REWIRE_FROM=default          rewire VM NICs currently attached to this network
  STATE_DIR=/var/lib/lan-expose
EOF
}

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "== $*"; }
vsh()  { virsh -c qemu:///system "$@"; }

ip2int() { local IFS=. a b c d; read -r a b c d <<< "$1"; echo $(( (a<<24)|(b<<16)|(c<<8)|d )); }
int2ip() { local n=$1; echo "$(( (n>>24)&255 )).$(( (n>>16)&255 )).$(( (n>>8)&255 )).$(( n&255 ))"; }

mask2prefix() {
    local m p=0
    m=$(ip2int "$1")
    while (( p < 32 && (m >> (31-p)) & 1 )); do p=$((p+1)); done
    echo "$p"
}

while [ $# -gt 0 ]; do
    case $1 in
        --dry-run)   DRY_RUN=1 ;;
        --no-rewire) NO_REWIRE=1 ;;
        --no-test)   NO_TEST=1 ;;
        --force)     FORCE=1 ;;
        -h|--help)   usage; exit 0 ;;
        *)           usage >&2; die "unknown argument: $1" ;;
    esac
    shift
done

for cmd in ip virsh awk sed ping; do
    command -v "$cmd" >/dev/null || die "missing command: $cmd"
done
[ -f "$TEMPLATE" ] || die "template not found: $TEMPLATE"
[[ $NET_NAME =~ ^[a-zA-Z0-9._-]+$ ]] || die "invalid NET_NAME: $NET_NAME"

# Discover the primary (default-route) wireless interface and its IPv4 subnet.
discover_network() {
    if [ -z "$IFACE" ]; then
        IFACE=$(ip -4 route show default | awk '{for(i=1;i<NF;i++) if($i=="dev"){print $(i+1); exit}}')
        [ -n "$IFACE" ] || die "no default route found; set IFACE=<iface>"
    fi
    if [ ! -d "/sys/class/net/$IFACE/phy80211" ] && [ ! -d "/sys/class/net/$IFACE/wireless" ]; then
        die "$IFACE is not a wireless interface; set IFACE=<iface> to override"
    fi
    HOST_CIDR=$(ip -4 addr show dev "$IFACE" scope global | awk '/inet /{print $2; exit}')
    [ -n "$HOST_CIDR" ] || die "no global IPv4 address on $IFACE"
}

# Carve the guest slice out of a subnet: for /27-and-larger subnets take the
# top-aligned /27, for smaller ones use the subnet whole. The host's own IP
# must stay outside the slice. Sets SLICE_CIDR/GATEWAY/DHCP_START/DHCP_END.
compute_slice() {
    local cidr=$1 ip=${1%/*} p=${1#*/} n mask size net bcast ssize sbcast hip
    if ! [[ $ip =~ ^[0-9]+(\.[0-9]+){3}$ ]]; then die "bad IP in CIDR: $cidr"; fi
    if ! [[ $p =~ ^[0-9]+$ ]] || (( p < 8 )) || (( p > 32 )); then die "bad prefix in CIDR: $cidr"; fi
    n=$(ip2int "$ip")
    mask=$(( (0xFFFFFFFF << (32-p)) & 0xFFFFFFFF ))
    net=$(( n & mask ))
    size=$(( 1 << (32-p) ))
    bcast=$(( net + size - 1 ))
    if (( size < 8 )); then die "subnet /$p is too small to carve a guest slice from"; fi
    if (( p <= 27 )); then
        SLICE_PREFIX=27
        SLICE_BASE=$(( bcast - 31 ))
    else
        SLICE_PREFIX=$p
        SLICE_BASE=$net
    fi
    ssize=$(( 1 << (32-SLICE_PREFIX) ))
    sbcast=$(( SLICE_BASE + ssize - 1 ))
    SLICE_CIDR=$(int2ip "$SLICE_BASE")/$SLICE_PREFIX
    GATEWAY=$(int2ip $(( SLICE_BASE + 1 )))
    DHCP_START=$(int2ip $(( SLICE_BASE + 2 )))
    DHCP_END=$(int2ip $(( SLICE_BASE+16 < sbcast-1 ? SLICE_BASE+16 : sbcast-1 )))
    hip=$(ip2int "${HOST_CIDR%/*}")
    if (( hip >= SLICE_BASE && hip <= sbcast )); then
        die "host address ${HOST_CIDR%/*} falls inside guest slice $SLICE_CIDR; set SLICE_CIDR=<cidr>"
    fi
}

# Pick the first free virbrN bridge name (not present as a link, not used by
# any defined libvirt network).
pick_bridge() {
    local in_use existing i
    in_use=$(ip -o link show | awk -F': ' '{print $2}' | cut -d@ -f1)
    existing=$(vsh net-list --all --name 2>/dev/null | while read -r n; do
        [ -n "$n" ] && vsh net-dumpxml "$n" 2>/dev/null
    done | grep -o "bridge name='[^']*'" | cut -d"'" -f2 || true)
    for i in $(seq 0 99); do
        if ! grep -qx "virbr$i" <<< "$in_use" && ! grep -qx "virbr$i" <<< "$existing"; then
            BRIDGE="virbr$i"
            return 0
        fi
    done
    die "no free virbr0..virbr99 name"
}

# If the network already exists (e.g. installed by an earlier one-shot
# script), adopt its live parameters: prefer its bridge name and require the
# discovered slice to match, unless --force.
reconcile_existing() {
    vsh net-info "$NET_NAME" >/dev/null 2>&1 || return 0
    local xml ip_line abridge addr pprefix pmask rstart rend
    xml=$(vsh net-dumpxml "$NET_NAME")
    abridge=$(grep -o "bridge name='[^']*'" <<< "$xml" | cut -d"'" -f2 || true)
    if [ -n "$abridge" ] && [ "$abridge" != "$BRIDGE" ]; then
        echo "   note: adopting existing bridge of '$NET_NAME': $abridge"
        BRIDGE=$abridge
    fi
    ip_line=$(grep -o "<ip address='[^']*'[^>]*>" <<< "$xml" | head -1 || true)
    addr=$(sed -n "s/.*address='\([^']*\)'.*/\1/p" <<< "$ip_line")
    pprefix=$(sed -n "s/.*prefix='\([^']*\)'.*/\1/p" <<< "$ip_line")
    if [ -z "$pprefix" ]; then
        pmask=$(sed -n "s/.*netmask='\([^']*\)'.*/\1/p" <<< "$ip_line")
        [ -n "$pmask" ] && pprefix=$(mask2prefix "$pmask")
    fi
    rstart=$(grep -o "range start='[^']*'" <<< "$xml" | cut -d"'" -f2 || true)
    rend=$(grep -o " end='[^']*'" <<< "$xml" | cut -d"'" -f2 || true)
    if [ "$addr" != "$GATEWAY" ] || [ "${pprefix:-}" != "$SLICE_PREFIX" ] \
        || [ "$rstart" != "$DHCP_START" ] || [ "$rend" != "$DHCP_END" ]; then
        DRIFT=1
        echo "   live '$NET_NAME' differs: ip ${addr:-?}/${pprefix:-?} dhcp ${rstart:-?}..${rend:-?}" \
             "vs discovered ${GATEWAY}/${SLICE_PREFIX} dhcp ${DHCP_START}..${DHCP_END}"
        if [ $FORCE -eq 0 ]; then
            die "drift detected; re-run with --force to redefine '$NET_NAME' (guests will blip)"
        fi
    fi
}

render_template() {
    sed -e "s|@NET_NAME@|$NET_NAME|g" \
        -e "s|@BRIDGE@|$BRIDGE|g" \
        -e "s|@IFACE@|$IFACE|g" \
        -e "s|@GATEWAY@|$GATEWAY|g" \
        -e "s|@PREFIX@|$SLICE_PREFIX|g" \
        -e "s|@DHCP_START@|$DHCP_START|g" \
        -e "s|@DHCP_END@|$DHCP_END|g" \
        "$TEMPLATE"
}

apply_network() {
    local rendered="$STATE_DIR/$NET_NAME.xml"
    mkdir -p "$STATE_DIR"
    render_template > "$rendered"
    if [ $FORCE -eq 1 ] && [ $DRIFT -eq 1 ]; then
        vsh net-destroy "$NET_NAME" >/dev/null 2>&1 || true
        vsh net-undefine "$NET_NAME" >/dev/null
    fi
    if ! vsh net-info "$NET_NAME" >/dev/null 2>&1; then
        vsh net-define "$rendered" >/dev/null
        echo "   defined $NET_NAME from $rendered"
    else
        echo "   network $NET_NAME already defined"
    fi
    vsh net-autostart "$NET_NAME" >/dev/null
    if vsh net-info "$NET_NAME" | grep -q '^Active:.*yes'; then
        echo "   network already active"
    else
        vsh net-start "$NET_NAME" >/dev/null
    fi
}

apply_sysctls() {
    SYSCTL_FILE="/etc/sysctl.d/30-$NET_NAME-proxyarp.conf"
    sysctl -w net.ipv4.ip_forward=1 >/dev/null
    sysctl -w "net.ipv4.conf.$IFACE.proxy_arp=1" >/dev/null
    sysctl -w "net.ipv4.conf.$BRIDGE.proxy_arp=1" >/dev/null
    cat > "$SYSCTL_FILE" <<EOF
# libvirt "$NET_NAME" network: guests in $SLICE_CIDR behind $IFACE.
# The host must proxy-answer ARP for guest IPs arriving on $IFACE.
# (virbrN proxy_arp is re-set by setup.sh; the bridge does not exist at boot.)
net.ipv4.ip_forward = 1
net.ipv4.conf.$IFACE.proxy_arp = 1
EOF
    echo "   proxy_arp enabled on $IFACE and $BRIDGE; persisted in $SYSCTL_FILE"
}

rewire_vms() {
    local found=0 vm row model mac
    while IFS= read -r vm; do
        [ -n "$vm" ] || continue
        while IFS= read -r row; do
            [ -n "$row" ] || continue
            model=${row%% *}
            mac=${row#* }
            vsh detach-interface "$vm" --type network --mac "$mac" --config >/dev/null
            vsh attach-interface "$vm" --type network --source "$NET_NAME" \
                --model "$model" --mac "$mac" --config >/dev/null
            printf '%s\tnetwork\t%s\t%s\t%s\n' "$vm" "$REWIRE_FROM" "$model" "$mac" \
                >> "$STATE_DIR/rewired.tsv"
            echo "   $vm: $REWIRE_FROM -> $NET_NAME (model $model, mac $mac)"
            found=1
        done < <(vsh domiflist "$vm" | awk -v src="$REWIRE_FROM" \
            '$2=="network" && $3==src && $5!="-" {print $4" "$5}')
    done < <(vsh list --all --name)
    [ $found -eq 1 ] || echo "   no VM NICs on network '$REWIRE_FROM' (nothing to rewire)"
}

write_state() {
    cat > "$STATE_DIR/state.env" <<EOF
NET_NAME=$NET_NAME
BRIDGE=$BRIDGE
IFACE=$IFACE
SUBNET_CIDR=$HOST_CIDR
SLICE_CIDR=$SLICE_CIDR
GATEWAY=$GATEWAY
DHCP_START=$DHCP_START
DHCP_END=$DHCP_END
REWIRE_FROM=$REWIRE_FROM
RENDERED_XML=$STATE_DIR/$NET_NAME.xml
SYSCTL_FILE=$SYSCTL_FILE
EOF
    chmod 600 "$STATE_DIR/state.env"
}

test_cleanup() {
    ip netns del lanexpose-test 2>/dev/null || true
    ip link del lanexpose-t0 2>/dev/null || true
}

# Prove the whole path without booting a VM: a simulated guest in a netns
# pings the LAN gateway. The gateway's reply can only come back if the host
# proxy-answered ARP for the guest IP on the upstream interface — exactly
# what a real LAN device triggers when it talks to a guest.
run_test() {
    local gw rc=0
    gw=$(ip -4 route show default dev "$IFACE" | awk '{for(i=1;i<NF;i++) if($i=="via"){print $(i+1); exit}}')
    test_cleanup
    trap test_cleanup EXIT
    ip netns add lanexpose-test
    ip link add lanexpose-t0 type veth peer name lanexpose-t1
    ip link set lanexpose-t1 netns lanexpose-test
    ip link set lanexpose-t0 master "$BRIDGE" up
    ip netns exec lanexpose-test ip link set lo up
    ip netns exec lanexpose-test ip link set lanexpose-t1 up
    ip netns exec lanexpose-test ip addr add "$DHCP_START/$SLICE_PREFIX" dev lanexpose-t1
    ip netns exec lanexpose-test ip route add default via "$GATEWAY"
    sleep 1
    if [ -n "$gw" ]; then
        if ip netns exec lanexpose-test ping -c3 -W2 "$gw" >/dev/null 2>&1; then
            echo "   PASS: guest($DHCP_START) -> LAN gateway($gw) round-trip (proxy ARP answers LAN-side)"
        else
            echo "   FAIL: guest -> LAN gateway($gw) ping failed; inspect routing/proxy_arp"
            rc=1
        fi
    else
        echo "   SKIP: $IFACE has no gateway; LAN-side proxy ARP not exercised"
    fi
    if ping -c2 -W2 "$DHCP_START" >/dev/null 2>&1; then
        echo "   PASS: host -> guest($DHCP_START) direct"
    else
        echo "   FAIL: host -> guest($DHCP_START) ping failed"
        rc=1
    fi
    test_cleanup
    trap - EXIT
    return $rc
}

discover_network
compute_slice "${SLICE_CIDR:-$HOST_CIDR}"
pick_bridge
reconcile_existing

info "discovered"
echo "   interface:    $IFACE ($HOST_CIDR)"
echo "   guest slice:  $SLICE_CIDR (gateway $GATEWAY, DHCP $DHCP_START..$DHCP_END)"
echo "   bridge:       $BRIDGE"
echo "   network:      $NET_NAME (rewire source: $REWIRE_FROM)"

if [ $DRY_RUN -eq 1 ]; then
    info "dry-run: planned network XML (nothing written)"
    render_template | sed 's/^/   /'
    exit 0
fi

[ "$(id -u)" -eq 0 ] || die "root required (sudo); use --dry-run for a no-change preview"

info "1. libvirt network"
apply_network
info "2. sysctls"
apply_sysctls
if [ $NO_REWIRE -eq 1 ]; then
    info "3. VM NIC rewire: skipped (--no-rewire)"
else
    info "3. VM NIC rewire ($REWIRE_FROM -> $NET_NAME)"
    rewire_vms
fi
write_state
if [ $NO_TEST -eq 1 ]; then
    info "4. end-to-end test: skipped (--no-test)"
elif ! run_test; then
    die "end-to-end test failed; network left defined/started for debugging"
fi

info "DONE"
echo "   Boot a VM: it leases $DHCP_START..$DHCP_END (gateway $GATEWAY, DNS $GATEWAY)."
echo "   Other WLAN/LAN devices reach guests directly by IP. Undo: sudo uninstall.sh"

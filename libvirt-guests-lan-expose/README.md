# libvirt-guests-lan-expose

Expose libvirt guests as first-class citizens of the LAN the host is
connected to over Wi-Fi: guests get real addresses from the LAN's own
subnet and are reachable directly from any other WLAN/LAN device — no NAT,
no router configuration. Host↔guest and guest↔guest communication included.

## Why not a bridge

A WLAN *client* interface can be neither a bridge port nor a macvtap
uplink: 802.11 client-mode data frames carry only the associated station's
own MAC as source, so the access point drops every frame with a guest's
source MAC. WDS/4-address mode would lift this, but needs explicit AP
support (consumer ISP routers don't). This tool therefore *routes* instead
of bridging.

## How it works

1. discovers the default-route wireless interface and its IPv4 subnet;
2. carves the guest slice: the top-aligned `/27` of the LAN subnet (a
   smaller subnet is used whole), e.g. host `192.168.1.6/24` → slice
   `192.168.1.224/27`; the host's own address must fall outside it;
3. defines a libvirt `<forward mode='route'>` network on the first free
   `virbrN` bridge; the bridge IP is the slice gateway and libvirt's
   dnsmasq leases the remaining slice addresses to guests;
4. enables kernel proxy ARP on the Wi-Fi interface: the host answers ARP
   for guest IPs, so LAN devices (and the router) treat guests as on-link
   neighbors; the host then routes packets between the bridge and the
   Wi-Fi interface — no NAT anywhere;
5. rewires VM NICs from a source network (default: libvirt's `default`
   NAT network) to the new one, preserving model and MAC, and records the
   previous state for uninstall;
6. verifies the whole path end-to-end without booting a VM: a simulated
   guest (netns + veth on the bridge) pings the LAN gateway — the
   gateway's reply can only return if the host proxy-answered ARP for the
   guest IP on the upstream interface, exactly what a real LAN device
   triggers.

```
guest 192.168.1.226/27 ── virbr2 (192.168.1.225/27, libvirt routed net)
                               │ host routes, no NAT
host wlan0 192.168.1.6/24 ─────┴── Wi-Fi ── router 192.168.1.1
   └ proxy-answers "who has 192.168.1.226?" on wlan0 for the guest

phone/PC: ping 192.168.1.226 ──► (host ARP-proxies, routes) ──► guest
```

## Requirements

- Arch-style Linux with libvirtd system daemon; every virsh call passes
  `-c qemu:///system` explicitly (the default URI here is `qemu:///session`)
- iproute2, dnsmasq (libvirt dependency), iputils (ping), bash 4+
- apply run needs root (`sudo`); `--dry-run` needs only read access to
  `qemu:///system`
- tested with libvirt 12.7 + QEMU 11.1 + NetworkManager on Arch Linux

## Usage

```bash
./setup.sh --dry-run      # preview: discovery, rendered XML, planned actions
sudo ./setup.sh           # apply: define network, sysctls, rewire VMs, verify
sudo ./uninstall.sh       # undo: restore NICs, remove network + sysctls + state
```

Options: `--dry-run`, `--no-rewire`, `--no-test`, `--force`, `-h`.

Environment overrides:

| Variable     | Default                        | Meaning                                    |
|--------------|--------------------------------|--------------------------------------------|
| `NET_NAME`   | `lan-routed`                   | libvirt network name (also file names)     |
| `IFACE`      | default-route wireless iface   | upstream interface (must be wireless)      |
| `SLICE_CIDR` | top-aligned `/27` of LAN       | explicit guest slice, e.g. `192.168.1.96/27` |
| `REWIRE_FROM`| `default`                      | rewire VM NICs currently on this network   |
| `STATE_DIR`  | `/var/lib/lan-expose`          | state + rendered XML location              |

`--force` redefines the network when the live definition drifted from the
current discovery (e.g. the host moved to a different Wi-Fi subnet);
guests blip and renew their leases.

## What it changes on the system

- libvirt network `lan-routed` (autostarted) on a `virbrN` bridge
- `/etc/sysctl.d/30-lan-routed-proxyarp.conf`: `ip_forward=1` and
  `proxy_arp=1` on the Wi-Fi interface (also set live, along with the
  bridge's own `proxy_arp`)
- VM NICs rewired to the new network (previous source kept in state)
- state under `/var/lib/lan-expose/`: `state.env`, `lan-routed.xml`
  (rendered), `rewired.tsv` (vm → previous type/source/model/mac)
- during the test only: a temporary netns + veth pair, removed afterwards

## Guest addressing

- DHCP from libvirt's dnsmasq: slice base +2 … (15 addresses on a `/27`),
  gateway and DNS = bridge IP (dnsmasq forwards DNS upstream)
- static guest addresses **must stay inside the carved slice**: the host's
  longest-prefix route for the slice points at the bridge; anything else
  falls into the LAN `/24` route via the Wi-Fi interface and breaks
- fixed per-guest addresses: add `<host mac='…' ip='…'/>` under `<dhcp>`
  (e.g. `virsh net-update lan-routed add last ip-dhcp-host "<host …/>"`)

## Caveats

- the carved slice must be outside the router's DHCP pool — check the
  router; nothing on the host can verify this
- broadcast/multicast does not cross: guests don't appear in mDNS/NetBIOS
  discovery; reach them by IP (or a DNS entry)
- the network is pinned to the discovered interface and subnet; roaming to
  a different Wi-Fi LAN invalidates it until a `--force` re-run
- Windows guests may need their network profile set to "Private" (or ICMP
  allowed) before they answer pings
- `uninstall.sh` intentionally leaves `net.ipv4.ip_forward=1` (shared
  setting, e.g. docker/libvirt NAT also use it)
- wired upstream: the routed+proxy-ARP design works there too, but a real
  bridge is the better tool; `setup.sh` refuses non-wireless interfaces
  unless `IFACE=` is given explicitly

## Files

| File             | Purpose                                              |
|------------------|------------------------------------------------------|
| `setup.sh`       | discovery, rendering, apply, rewire, end-to-end test |
| `uninstall.sh`   | restore VM NICs, remove network/sysctls/state        |
| `network.xml.tpl`| network template rendered via `@PLACEHOLDER@` sed    |

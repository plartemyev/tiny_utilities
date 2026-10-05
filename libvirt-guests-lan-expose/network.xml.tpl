<!-- Template rendered by setup.sh via @PLACEHOLDER@ substitution.
     A libvirt routed network that exposes guests on the host's LAN subnet:
     the guest slice is part of the LAN's own prefix, and the host
     proxy-answers ARP for guest IPs on the upstream (Wi-Fi) interface. -->
<network>
  <name>@NET_NAME@</name>
  <bridge name='@BRIDGE@' stp='off' delay='0'/>
  <forward mode='route' dev='@IFACE@'/>
  <ip address='@GATEWAY@' prefix='@PREFIX@'>
    <dhcp>
      <range start='@DHCP_START@' end='@DHCP_END@'/>
    </dhcp>
  </ip>
</network>

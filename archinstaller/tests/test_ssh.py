from archinstaller.ssh import subnet_addresses


def test_subnet_addresses_covers_usable_hosts():
    addresses = subnet_addresses("192.168.56.113")
    assert len(addresses) == 254
    assert addresses[0] == "192.168.56.1"
    assert addresses[-1] == "192.168.56.254"
    assert "192.168.56.113" in addresses


def test_subnet_addresses_normalizes_non_network_base():
    addresses = subnet_addresses("10.0.2.77")
    assert addresses[0] == "10.0.2.1"
    assert addresses[-1] == "10.0.2.254"

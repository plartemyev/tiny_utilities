from archinstaller.script import InstallConfig
from archinstaller.workbook import build_workbook

KEY = ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDU0ZDDGMlGKUYbFQtKyODXXUequNtcQz+2UVe5Vr9A0"
       " nameless@example")


def make_cfg(**overrides):
    defaults = {
        "disk": "/dev/vda",
        "hostname": "arch-host-2026-10-17",
        "locale": "en_US.UTF-8",
        "swap_size": "16G",
        "username": "nameless",
        "root_password": "{{ROOT_PASSWORD}}",
        "user_password": "{{USER_PASSWORD}}",
        "public_key": KEY,
        "graphical": False,
        "virt": "none",
        "discard": False,
        "timezone": "Asia/Bangkok",
        "opencode": False,
        "opencode_password": None,
    }
    defaults.update(overrides)
    return InstallConfig(**defaults)


def render(cfg: InstallConfig, **kwargs) -> str:
    return build_workbook(cfg, **kwargs)


def test_header_and_facts_line():
    md = render(make_cfg())
    assert md.startswith("# archinstaller workbook — arch-host-2026-10-17\n")
    assert ("Rendered " in md and "disk=/dev/vda, virt=none, discard=off,"
            " graphical=no, locale=en_US.UTF-8, swap=16G, username=nameless,"
            " timezone=Asia/Bangkok." in md)


def test_facts_line_reports_mirror_and_opencode():
    md = render(make_cfg(local_mirror="http://192.168.1.10:8282", opencode=True,
                         opencode_password="{{OPENCODE_PASSWORD}}"))
    assert "local mirror=http://192.168.1.10:8282" in md
    assert "opencode=yes" in md


def test_placeholders_reach_the_commands_and_no_caution():
    md = render(make_cfg())
    assert "printf 'root:%s\\n' '{{ROOT_PASSWORD}}' | chpasswd" in md
    assert "printf '%s:%s\\n' 'nameless' '{{USER_PASSWORD}}' | chpasswd" in md
    assert "Caution" not in md


def test_embedded_passwords_add_caution_block():
    md = render(make_cfg(root_password="s3cret", user_password="hunter2"),
                passwords_embedded=True)
    assert "Caution — live credentials" in md
    assert "mode 0600" in md and "Rotate the passwords" in md
    assert "printf 'root:%s\\n' 's3cret' | chpasswd" in md
    assert "printf '%s:%s\\n' 'nameless' 'hunter2' | chpasswd" in md


def test_caution_lists_opencode_only_when_enabled():
    with_oc = render(make_cfg(opencode=True, opencode_password="ocpw"),
                     passwords_embedded=True)
    assert "(root, user, opencode)" in with_oc
    without_oc = render(make_cfg(), passwords_embedded=True)
    assert "(root, user)" in without_oc


def test_virt_conditionals():
    oracle = render(make_cfg(virt="oracle"))
    assert "systemctl enable vboxservice" in oracle
    assert "position_fix=1" in oracle
    kvm = render(make_cfg(virt="kvm"))
    assert "systemctl enable qemu-guest-agent" in kvm
    assert "systemctl enable vboxservice" not in kvm
    assert "position_fix" not in kvm
    none = render(make_cfg(virt="none"))
    assert "systemctl enable vboxservice" not in none
    assert "systemctl enable qemu-guest-agent" not in none


def test_provision_section_replaces_target_facts():
    md = build_workbook(make_cfg(), provision="PROVISION-SECTION-MARKER")
    assert "PROVISION-SECTION-MARKER" in md
    assert "## 0. Target facts" not in md


def test_plain_workbook_keeps_target_facts():
    md = build_workbook(make_cfg())
    assert "## 0. Target facts" in md


def test_discard_conditionals():
    with_discard = render(make_cfg(discard=True))
    assert "systemctl enable fstrim.timer" in with_discard
    assert "defaults,discard" in with_discard
    without = render(make_cfg())
    assert "systemctl enable fstrim.timer" not in without
    assert "defaults,discard" not in without


def test_graphical_conditionals():
    graphical = render(make_cfg(graphical=True, virt="oracle"))
    assert "systemctl enable soniclogin" in graphical
    tokens = graphical.split()
    assert "virtualbox-guest-utils" in tokens
    assert "virtualbox-guest-utils-nox" not in tokens
    console = render(make_cfg(virt="oracle"))
    assert "soniclogin" not in console
    tokens = console.split()
    assert "virtualbox-guest-utils-nox" in tokens
    assert "virtualbox-guest-utils" not in tokens


def test_opencode_unit_renders_with_password():
    md = render(make_cfg(opencode=True, opencode_password="ocpw"))
    assert "Environment=OPENCODE_SERVER_PASSWORD=ocpw" in md
    assert "loginctl enable-linger 'nameless'" in md
    assert "sudo firewall-cmd --permanent --add-port=49374/tcp" in md


def test_post_boot_uses_sudo_only_for_root_steps():
    md = render(make_cfg())
    assert "sudo ln -sf ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf" in md
    assert "sudo timedatectl set-timezone 'Asia/Bangkok'" in md
    # user-level steps stay plain
    assert "sudo ssh-keygen" not in md
    assert "ssh-keygen -q -t ed25519" in md


def test_dns_kick_step_present_for_manual_repair():
    md = render(make_cfg())
    assert "Restoring DNS resolution if it is broken" in md
    assert "/etc/NetworkManager/dispatcher.d/90-archinstaller-dns-fallback" in md


def test_repos_append_is_part_of_the_pacman_conf_section():
    md = render(make_cfg())
    heading = md.index("## 8. Tuning /etc/pacman.conf")
    repos = md.index("cat >> /etc/pacman.conf <<'REPOS'")
    next_heading = md.index("## 9. ")
    assert heading < repos < next_heading


def test_target_facts_and_probes():
    md = render(make_cfg(local_mirror="http://192.168.1.10:8282"))
    assert "## 0. Target facts" in md
    assert "test -d /sys/firmware/efi" in md
    assert "systemd-detect-virt" in md
    assert "/sys/block/vda/queue/discard_max_bytes" in md
    assert "curl -fsS --max-time 8 http://192.168.1.10:8282/healthz" in md


def test_no_helper_definitions_and_retry_unwrapped():
    md = render(make_cfg())
    assert "set -euo pipefail" not in md  # no helper block
    assert "retry" not in md  # commands are runnable as-is
    assert "pacman -Sy --needed --noconfirm" in md
    assert "curl -O https://xlibre-arch.github.io/xlibre-archlinux.asc" in md


def test_no_bash_log_markers_in_workbook():
    md = render(make_cfg(graphical=True))
    assert "log '" not in md


def test_local_mirror_renders_sole_source_lines():
    md = render(make_cfg(local_mirror="http://192.168.1.10:8282"))
    assert "> /etc/pacman.d/mirrorlist" in md
    assert "Server = http://192.168.1.10:8282/$repo/os/$arch" in md
    assert "Server = http://192.168.1.10:8282/xlibre/os/$arch" in md
    assert "packages.xlibre.net" not in md

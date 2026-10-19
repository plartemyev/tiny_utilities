# tiny_utilities

Small, independent utilities. Each folder is self-contained with its own
README.

| Folder | What it is |
|---|---|
| `arch-cache-mirror/` | Caching pacman mirror container (incl. ALARM/arm64), byte-range + db refresh semantics |
| `archinstaller/` | Opinionated Arch installer for libvirt/VirtualBox/physical targets |
| `archpkg/` | Arch package tooling |
| `codebook-dictionary-harvest/` | Dictionary harvesting for codebook |
| `kdeconnect-media-logger/` | KDE Connect MPRIS media logging service |
| `lax-bandwidth-analyzer/` | Bandwidth analysis |
| `libvirt-guests-lan-expose/` | Expose libvirt guests on the LAN |
| `opencode-power-saver/` | Tampermonkey userscript cutting CPU/battery cost of the opencode web UI (motion kill, content-visibility, freeze-when-hidden for background streaming tabs) |
| `PHP-REDIS-SESSIONS-aws_elastic_beanstalk/` | PHP Redis sessions on Elastic Beanstalk |
| `sony-as300-xavc-recovery/` | Sony AS300 XAVC recovery |
| `zabbix-reporter/` | Zabbix reporting |

Host-specific tooling notes live in `AGENTS.md` and
`~/.config/opencode/AGENTS.md` (global).

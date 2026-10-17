log 'Configuring the new system (arch-chroot)'
arch-chroot /mnt/new-root /bin/bash <<'CHROOT'
set -euo pipefail
log() { printf '\n===== %s =====\n' "$*"; }

retry() {
    local attempt=1
    while true; do
        if "$@"; then
            return 0
        fi
        if [ "$attempt" -ge 3 ]; then
            return 1
        fi
        echo "attempt $attempt/3 failed: $*; retrying in 5s..."
        attempt=$((attempt + 1))
        sleep 5
    done
}

# Builder image for the nightly zcode packages. The pinned Node/pnpm
# toolchain is resolved at build time from upstream's mise.toml/package.json
# and cached on the /cache volume, so the image itself stays version-agnostic.
# fpm (ruby) is required by electron-builder's pacman target.
FROM archlinux:latest
RUN pacman-key --init \
    && pacman -Sy --noconfirm archlinux-keyring \
    && pacman -Syu --noconfirm \
       git curl tar xz zstd base-devel ruby ruby-rubygems python make gcc \
       libarchive gnupg sed awk findutils which \
    && gem install fpm --no-document \
    && rm -rf /var/cache/pacman/pkg/* /var/lib/pacman/sync/*
COPY build.sh strip-telemetry.sh verify-stripped.sh /build-files/
COPY packaging /build-files/packaging
RUN chmod 755 /build-files/build.sh /build-files/strip-telemetry.sh /build-files/verify-stripped.sh \
    && mkdir -p /work /cache /repo \
    && chmod 1777 /work
WORKDIR /work
CMD ["/build-files/build.sh"]

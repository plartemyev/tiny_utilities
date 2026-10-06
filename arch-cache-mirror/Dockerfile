# arch-cache-mirror: caching LAN mirror for pacman repositories
FROM archlinux:latest

# -Sy archlinux-keyring first: the base image can lag behind the repos and
# otherwise fail signature checks during -Syu (partial upgrade of the keyring
# alone is the officially suggested workaround for container builds).
RUN pacman-key --init \
	&& pacman -Sy --noconfirm archlinux-keyring \
	&& pacman -Syu --noconfirm python-aiohttp \
	&& pacman -Scc --noconfirm

# Unprivileged runtime user; docker-compose.yml maps this uid:gid to the
# calling host user so the bind-mounted cache stays host-user owned
# (see README.md "Caveats"). Default 1000 also matches a bare
# `docker run` on typical single-user hosts.
RUN groupadd -g 1000 mirror \
	&& useradd -u 1000 -g mirror -M -d /var/cache/arch-mirror -s /usr/bin/nologin mirror \
	&& install -d -o mirror -g mirror /var/cache/arch-mirror

COPY server.py test_mirror.py /app/

USER mirror

ENV LISTEN_ADDR=0.0.0.0 \
	LISTEN_PORT=8080 \
	CACHE_DIR=/var/cache/arch-mirror

VOLUME /var/cache/arch-mirror
EXPOSE 8080

# stdlib-only check so no curl/wget dependency is needed
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
	CMD python -c "import os,sys,urllib.request; \
	sys.exit(\
	0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('LISTEN_PORT','8080'), \
	timeout=4\
	).status == 200 else 1)"

# Non-root (mirror, uid/gid 1000): port 8080 is unprivileged and the cache
# is a bind mount whose host side is owned by the mapped user.
CMD ["python", "/app/server.py"]

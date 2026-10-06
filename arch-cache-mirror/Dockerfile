# arch-cache-mirror: caching LAN mirror for pacman repositories
FROM archlinux:latest

# -Sy archlinux-keyring first: the base image can lag behind the repos and
# otherwise fail signature checks during -Syu (partial upgrade of the keyring
# alone is the officially suggested workaround for container builds).
RUN pacman-key --init \
	&& pacman -Sy --noconfirm archlinux-keyring \
	&& pacman -Syu --noconfirm python-aiohttp \
	&& pacman -Scc --noconfirm

COPY server.py test_mirror.py /app/

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

# Runs as root so the (bind-mounted) cache volume is always writable; see
# README.md ("Security") if you want to drop privileges.
CMD ["python", "/app/server.py"]

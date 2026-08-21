FROM python:3.12-slim

RUN groupadd --gid 65532 sandbox \
    && useradd --uid 65532 --gid 65532 --no-create-home --home-dir /workspace sandbox

COPY sandbox/run-command.py /opt/cloud-agent/run-command.py
RUN chmod 0555 /opt/cloud-agent/run-command.py

WORKDIR /workspace
USER 65532:65532

# Docker supplies --init, read-only rootfs, dropped capabilities, cgroup limits,
# a network-disabled namespace and a bounded /tmp at container creation time.
CMD ["sleep", "infinity"]

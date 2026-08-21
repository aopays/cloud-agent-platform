"""Minimal allowlisted CONNECT tunnel for Docker-routed OpenAI egress.

The proxy never terminates TLS and therefore cannot inspect API credentials or
request bodies. The container port must only be published on 127.0.0.1.
"""

from __future__ import annotations

import select
import socket
import socketserver

ALLOWED_AUTHORITY = "api.openai.com:443"
MAX_HEADER_BYTES = 4096


class ConnectHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        client = self.request
        client.settimeout(10)
        header = bytearray()
        while b"\r\n\r\n" not in header:
            chunk = client.recv(1024)
            if not chunk:
                return
            header.extend(chunk)
            if len(header) > MAX_HEADER_BYTES:
                self._reject(431, "Request Header Fields Too Large")
                return

        request_line = bytes(header).split(b"\r\n", 1)[0]
        try:
            method, authority, version = request_line.decode("ascii").split(" ")
        except (UnicodeDecodeError, ValueError):
            self._reject(400, "Bad Request")
            return
        if (
            method != "CONNECT"
            or authority.lower() != ALLOWED_AUTHORITY
            or version not in {"HTTP/1.0", "HTTP/1.1"}
        ):
            self._reject(403, "Forbidden")
            return

        try:
            upstream = socket.create_connection(("api.openai.com", 443), timeout=15)
        except OSError:
            self._reject(502, "Bad Gateway")
            return

        with upstream:
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            client.settimeout(None)
            upstream.settimeout(None)
            self._relay(client, upstream)

    def _reject(self, status: int, reason: str) -> None:
        self.request.sendall(
            f"HTTP/1.1 {status} {reason}\r\nConnection: close\r\n\r\n".encode("ascii")
        )

    @staticmethod
    def _relay(client: socket.socket, upstream: socket.socket) -> None:
        sockets = (client, upstream)
        while True:
            readable, _, _ = select.select(sockets, (), (), 60)
            if not readable:
                return
            for source in readable:
                data = source.recv(64 * 1024)
                if not data:
                    return
                destination = upstream if source is client else client
                destination.sendall(data)


class TunnelServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    with TunnelServer(("0.0.0.0", 3128), ConnectHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()

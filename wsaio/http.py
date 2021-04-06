from __future__ import annotations

import http
import re


class HttpProtocol:
    def http_response_received(self, response: HttpResponse) -> None:
        pass


class HttpResponse:
    STATUS_LINE_REGEX = re.compile(
        r'HTTP/(?P<version>\d(\.\d)?) (?P<status>\d+) (?P<phrase>\w+)'
    )

    def __init__(self, *, version='1.1', status, headers, body):
        self.version = version
        self.status = http.HTTPStatus(status)
        self.headers = headers

    def encode(self) -> bytes:
        response = [f'HTTP/{self.version} {self.status} {self.status.phrase}']
        response.extend(f'{k}: {v}' for k, v in self.headers.items())
        response.append('\r\n')
        return b'\r\n'.join(part.encode() for part in response)

    @staticmethod
    def _iter_headers(headers: bytes):
        offset = 0
        while True:
            try:
                index = headers.index(b'\r\n', offset) + 2
            except ValueError:
                return
            data = headers[offset:index]
            offset = index
            yield [item.strip() for item in data.split(b':', 1)]

    @staticmethod
    def _get_lower(key, dct, default=None):
        key = key.lower()
        for k in dct:
            if k.lower() == key:
                return dct[k]
        return default

    @classmethod
    def parser(cls, protocol: HttpProtocol):
        headers = b''
        body = b''

        while True:
            headers += yield
            end = headers.find(b'\r\n\r\n')
            if end != -1:
                headers = headers[:end]
                body += headers[end + 4:]
                break

        headers = cls._iter_headers(headers)

        status_line, = next(headers)
        match = cls.STATUS_LINE_REGEX.match(status_line.decode())

        headers = dict(headers)

        content_length = cls._get_lower(b'content-length', headers, 0)

        while True:
            if len(body) >= content_length:
                break
            body += yield

        response = cls(
            version=match.group('version'),
            status=int(match.group('status')),
            headers=headers,
            body=body[:content_length]
        )
        protocol.http_response_received(response)

        return body[content_length:]


class HttpRequest:
    def __init__(self, *, version='1.1', method, path=None, headers):
        self.version = version
        self.method = method
        self.path = path or '/'
        self.headers = headers

    def encode(self) -> bytes:
        request = [f'{self.method} {self.path} HTTP/{self.version}']
        request.extend(f'{k}: {v}' for k, v in self.headers.items())
        request.append('\r\n')
        return b'\r\n'.join(part.encode() for part in request)

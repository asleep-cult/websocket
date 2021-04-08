from __future__ import annotations

import http
import re

from .exceptions import ParserInvalidDataError
from .utils import ensure_length

SENTINEL = object()


class HeadersMultiValue(list):
    pass


class Headers(dict):
    def __setitem__(self, key, value):
        key = key.lower()
        v = self.get(key, SENTINEL)
        if v is SENTINEL:
            return super().__setitem__(key, value)
        elif type(v) is HeadersMultiValue:
            return v.append(value)
        else:
            nv = HeadersMultiValue()
            nv.append(v)
            nv.append(value)
            return super().__setitem__(key, nv)

    def __getitem__(self, key, value):
        return super().__getitem__(key.lower(), value)

    def __delitem__(self, key, value):
        return super().__delitem__(key.lower(), value)

    def get(self, key, default=None):
        return super().get(key.lower(), default)

    def getone(self, key, default=None):
        value = self.get(key, default)
        if type(value) is HeadersMultiValue:
            value = value[0]
        return value

    def pop(self, key, *args, **kwargs):
        return super().pop(key.lower(), *args, **kwargs)

    def popone(self, key, default=SENTINEL):
        value = self.get(key, default)
        if value is SENTINEL:
            raise KeyError(key)
        elif type(value) is HeadersMultiValue:
            value = value.pop(0)
        else:
            del self[key]
        return value


class HttpResponseProtocol:
    def http_response_received(self, response: HttpResponse) -> None:
        pass


class HttpRequestProtocol:
    def http_request_received(self, request: HttpRequest) -> None:
        pass


def _iter_headers(headers: bytes):
    offset = 0

    while True:
        index = headers.index(b'\r\n', offset) + 2
        data = headers[offset:index]
        offset = index

        if data == b'\r\n':
            return

        yield [item.strip() for item in data.split(b':', 1)]


def _find_headers():
    headers = b''
    body = b''

    while True:
        headers += yield
        end = headers.find(b'\r\n\r\n') + 4

        if end != -1:
            headers = headers[:end]
            body += headers[end:]
            break

    return _iter_headers(headers), body


class HttpResponse:
    STATUS_LINE_REGEX = re.compile(
        r'HTTP/(?P<version>\d((?=\.)(\.\d))?) (?P<status>\d+) (?P<phrase>.+)'
    )

    def __init__(self, *, version='1.1', status, phrase, headers, body):
        self.version = version
        self.status = http.HTTPStatus(status)
        self.phrase = phrase
        self.headers = headers
        self.body = body

    def encode(self) -> bytes:
        response = [f'HTTP/{self.version} {self.status} {self.status.phrase}']
        response.extend(f'{k}: {v}' for k, v in self.headers.items())
        response.append('\r\n')
        return b'\r\n'.join(part.encode() for part in response)

    @classmethod
    def parser(cls, protocol: HttpResponseProtocol):
        headers, body = yield from _find_headers()

        status_line, = next(headers)

        extra = {
            'protocol': protocol,
            'status_line': status_line
        }

        try:
            match = cls.STATUS_LINE_REGEX.match(status_line.decode())
        except UnicodeDecodeError as e:
            raise ParserInvalidDataError(str(e), extra)

        if match is None:
            raise ParserInvalidDataError('The status line is invalid', extra)

        headers_dict = Headers()
        for key, value in headers:
            headers_dict[key] = value

        content_length = headers_dict.get(b'content-length', 0)

        body = yield from ensure_length(body, content_length)

        response = cls(
            version=match.group('version'),
            status=int(match.group('status')),
            phrase=match.group('phrase'),
            headers=headers_dict,
            body=body[:content_length]
        )
        protocol.http_response_received(response)

        return body[content_length:]


class HttpRequest:
    METHODS = (
        'GET', 'HEAD', 'POST', 'PUT', 'DELETE',
        'CONNECT', 'OPTIONS', 'TRACE', 'PATCH'
    )

    REQUEST_LINE_REXEX = re.compile(
        rf'(?P<method>{"|".join(METHODS)}) (?P<path>.+) '
        r'HTTP/(?P<version>\d((?=\.)(\.\d))?)'
    )

    def __init__(self, *, version='1.1', method, path=None, headers, body):
        self.version = version
        self.method = method
        self.path = path or '/'
        self.headers = headers
        self.body = body

    def encode(self) -> bytes:
        request = [f'{self.method} {self.path} HTTP/{self.version}']
        request.extend(f'{k}: {v}' for k, v in self.headers.items())
        request.append('\r\n')
        return b'\r\n'.join(part.encode() for part in request)

    @classmethod
    def parser(cls, protocol: HttpRequestProtocol):
        headers, body = yield from _find_headers()

        request_line, = next(headers)

        extra = {
            'protocol': protocol,
            'request_line': request_line
        }

        try:
            match = cls.REQUEST_LINE_REXEX.match(request_line.decode())
        except UnicodeDecodeError as e:
            raise ParserInvalidDataError(str(e), extra)

        if match is None:
            raise ParserInvalidDataError('The request line is invalid', extra)

        headers_dict = Headers()
        for key, value in headers:
            headers_dict[key] = value

        content_length = headers_dict.get(b'content-length', 0)

        body = yield from ensure_length(body, content_length)

        request = cls(
            version=match.group('version'),
            method=match.group('method'),
            path=match.group('path'),
            headers=headers_dict,
            body=body
        )
        protocol.http_request_received(request)

        return body[content_length:]

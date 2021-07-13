import re
from http import HTTPStatus

from .exceptions import ParserInvalidDataError
from .utils import ensure_length

_SENTINEL = object()


class Headers(dict):
    def __setitem__(self, key, value):
        key = key.lower()
        values = super().get(key)

        if values is not None:
            values.append(value)
        else:
            values = [value]

        super().__setitem__(key, values)

    def __getitem__(self, key):
        return super().__getitem__(key.lower())

    def __delitem__(self, key, value):
        return super().__delitem__(key.lower(), value)

    def get(self, key, *args, **kwargs):
        return super().get(key.lower(), *args, **kwargs)

    def pop(self, key, *args, **kwargs):
        return super().pop(key.lower(), *args, **kwargs)

    def getone(self, key, default=None):
        try:
            return self[key][0]
        except KeyError:
            return default

    def popone(self, key, default=_SENTINEL):
        try:
            return self[key].pop(0)
        except KeyError:
            if default is _SENTINEL:
                raise
            return default


def _iter_headers(headers):
    offset = 0

    while True:
        index = headers.index(b'\r\n', offset) + 2
        data = headers[offset:index]
        offset = index

        if data == b'\r\n':
            return

        yield [item.strip() for item in data.split(b':', 1)]


def _find_headers():
    data = b''

    while True:
        data += yield
        end = data.find(b'\r\n\r\n') + 4

        if end != -1:
            return _iter_headers(data[:end]), data[end:]


class HTTPResponse:
    STATUS_LINE_REGEX = re.compile(
        r'HTTP/(?P<version>\d((?=\.)(\.\d))?) (?P<status>\d+) (?P<phrase>.+)'
    )

    def __init__(self, *, version='1.1', status, phrase, headers, body):
        self.version = version
        self.status = HTTPStatus(status)
        self.phrase = phrase
        self.headers = headers
        self.body = body

    def serialize(self):
        response = [f'HTTP/{self.version} {self.status} {self.status.phrase}']

        response.extend(f'{k}: {v}' for k, v in self.headers.items())
        response.append('\r\n')

        return b'\r\n'.join(part.encode() for part in response)

    @classmethod
    def parser(cls, protocol):
        headers, body = yield from _find_headers()

        status_line, = next(headers)

        extra = {
            'protocol': protocol,
            'status_line': status_line
        }

        match = cls.STATUS_LINE_REGEX.match(status_line.decode())

        if match is None:
            raise ParserInvalidDataError('The status line is invalid', extra)

        headers_dict = Headers()

        for key, value in headers:
            headers_dict[key] = value

        content_length = headers_dict.getone(b'content-length')

        if content_length is not None:
            content_length = int(content_length.decode())
        else:
            content_length = 0

        body = yield from ensure_length(body, content_length)

        response = cls(
            version=match.group('version'), status=int(match.group('status')),
            phrase=match.group('phrase'), headers=headers_dict, body=body[:content_length]
        )

        protocol.http_response_received(response)

        return body[content_length:]


class HTTPRequest:
    METHODS = ('GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'CONNECT', 'OPTIONS', 'TRACE', 'PATCH')

    REQUEST_LINE_REXEX = re.compile(
        rf'(?P<method>{"|".join(METHODS)}) (?P<path>.+) HTTP/(?P<version>\d((?=\.)(\.\d))?)'
    )

    def __init__(self, *, version='1.1', method, path=None, headers, body):
        self.version = version
        self.method = method
        self.path = path or '/'
        self.headers = headers
        self.body = body

    def serialize(self):
        request = [f'{self.method} {self.path} HTTP/{self.version}']

        request.extend(f'{k}: {v}' for k, v in self.headers.items())
        request.append('\r\n')

        return b'\r\n'.join(part.encode() for part in request)

    @classmethod
    def parser(cls, protocol):
        headers, body = yield from _find_headers()

        request_line, = next(headers)

        extra = {
            'protocol': protocol,
            'request_line': request_line
        }

        match = cls.REQUEST_LINE_REXEX.match(request_line.decode())

        if match is None:
            raise ParserInvalidDataError('The request line is invalid', extra)

        headers_dict = Headers()

        for key, value in headers:
            headers_dict[key] = value

        content_length = headers_dict.getone(b'content-length')

        if content_length is not None:
            content_length = int(content_length.decode())
        else:
            content_length = 0

        body = yield from ensure_length(body, content_length)

        request = cls(
            version=match.group('version'), method=match.group('method'), path=match.group('path'),
            headers=headers_dict, body=body
        )

        protocol.http_request_received(request)

        return body[content_length:]

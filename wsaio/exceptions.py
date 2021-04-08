class WsaioError(Exception):
    def __init__(self, msg, extra):
        super().__init__(msg)
        self._extra = extra

    def get_extra(self, key, default=None):
        return self._extra.get(key, default)


class BrokenHandshakeError(WsaioError):
    pass


class ParserInvalidDataError(WsaioError):
    pass


class ConnectionClosedError(WsaioError, ConnectionError):
    pass

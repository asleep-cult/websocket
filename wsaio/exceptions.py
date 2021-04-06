class UnexpectedHttpResponse(ValueError):
    def __init__(self, msg, response):
        super().__init__(msg)
        self.response = response

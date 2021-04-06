def ensure_length(data, length):
    while length > len(data):
        data += yield
    return data

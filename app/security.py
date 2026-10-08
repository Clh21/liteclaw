import hmac

from starlette.datastructures import Headers


def credentials_valid(headers: Headers, expected: str) -> bool:
    authorization = headers.get("authorization")
    api_key = headers.get("x-api-key")
    bearer = None
    if authorization:
        scheme, separator, value = authorization.partition(" ")
        if not separator or scheme.casefold() != "bearer":
            return False
        bearer = value.strip()
    if bearer is not None and api_key is not None and bearer != api_key:
        return False
    supplied = bearer if bearer is not None else api_key
    return supplied is not None and hmac.compare_digest(supplied, expected)

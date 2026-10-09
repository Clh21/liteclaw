import hmac
from dataclasses import dataclass

from starlette.datastructures import Headers


@dataclass(frozen=True)
class Principal:
    id: str
    username: str
    role: str


def supplied_credential(headers: Headers) -> str | None:
    authorization = headers.get("authorization")
    api_key = headers.get("x-api-key")
    bearer = None
    if authorization:
        scheme, separator, value = authorization.partition(" ")
        if not separator or scheme.casefold() != "bearer":
            return None
        bearer = value.strip()
    if bearer is not None and api_key is not None and bearer != api_key:
        return None
    return bearer if bearer is not None else api_key


def credentials_valid(headers: Headers, expected: str) -> bool:
    supplied = supplied_credential(headers)
    return supplied is not None and hmac.compare_digest(supplied, expected)


async def authenticate(
    headers: Headers, database, bootstrap_key: str
) -> Principal | None:
    if credentials_valid(headers, bootstrap_key):
        return Principal("bootstrap", "bootstrap-admin", "admin")
    supplied = supplied_credential(headers)
    if not supplied:
        return None
    user = await database.authenticate_api_token(supplied)
    return Principal(**user) if user else None

import uvicorn

from app.config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)

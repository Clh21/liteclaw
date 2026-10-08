import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.memory.repository import Database

if __name__ == "__main__":
    asyncio.run(Database(Settings().database_path).initialize())

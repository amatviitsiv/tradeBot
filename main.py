import asyncio
import logging
from manager import Manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)

if __name__ == "__main__":
    manager = Manager()
    asyncio.run(manager.run())

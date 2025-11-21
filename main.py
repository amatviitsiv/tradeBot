import asyncio, logging
from manager import Manager
from logger_setup import logger

logging.basicConfig(level=logging.INFO)

async def main():
    mgr = Manager()
    try:
        await mgr.start()
    except KeyboardInterrupt:
        logging.info("Stopped by user (KeyboardInterrupt)")
        await mgr.stop()
    except Exception as e:
        logging.exception("Unhandled exception: %s", e)
        try:
            await mgr.stop()
        except Exception:
            pass

if __name__ == "__main__":
    asyncio.run(main())

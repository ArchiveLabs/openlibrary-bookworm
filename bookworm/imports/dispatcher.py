import asyncio
import logging
from contextlib import suppress

import psycopg

from bookworm.config import get_settings
from bookworm.imports.config import get_import_settings
from bookworm.imports.tasks import create_queue

logger = logging.getLogger(__name__)


async def run():
    settings = get_import_settings()
    url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    queue = create_queue(url)
    while True:
        try:
            await run_if_elected(queue, url, settings)
        except Exception:
            logger.exception("dispatcher_stopped")
        await asyncio.sleep(settings.poll_interval)


async def run_if_elected(queue, url, settings):
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as connection:
        cursor = await connection.execute(
            "SELECT pg_try_advisory_lock(%s)", (settings.dispatcher_lock_key,)
        )
        if not (await cursor.fetchone())[0]:
            return
        logger.info("dispatcher_elected")
        await run_worker(queue, connection, settings)


async def run_worker(queue, connection, settings):
    async with queue.open_async():
        worker = asyncio.create_task(
            queue.run_worker_async(
                queues=["imports"],
                concurrency=settings.dispatcher_concurrency,
                install_signal_handlers=False,
                fetch_job_polling_interval=settings.poll_interval,
            )
        )
        try:
            while not worker.done():
                await connection.execute("SELECT 1")
                await asyncio.sleep(settings.poll_interval)
        finally:
            # Procrastinate cancellation stops fetching and drains running tasks.
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker

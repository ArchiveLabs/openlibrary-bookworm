import logging
from uuid import UUID

from procrastinate import App, PsycopgConnector, RetryStrategy, SyncPsycopgConnector

from bookworm.imports.client import ImportResult, OpenLibraryClient

logger = logging.getLogger(__name__)
app = App(connector=SyncPsycopgConnector())


@app.task(
    name="imports:import_item",
    queue="imports",
    retry=RetryStrategy(max_attempts=4, wait=5),
    pass_context=True,
)
def import_item(context, item_id: str):
    from bookworm.imports import service

    item_id = UUID(item_id)
    record = service.get_import_data(item_id, context.job.id)
    if record is None:
        return
    try:
        result = OpenLibraryClient().import_record(record)
    except Exception:
        logger.exception("client_exception item_id=%s", item_id)
        result = ImportResult(
            success=False,
            unknown=True,
            description="Client exception; remote outcome is unknown",
        )
    service.finish_import(item_id, context.job.id, result)


def create_queue(url: str) -> App:
    queue = App(
        connector=PsycopgConnector(
            conninfo=url, kwargs={"options": "-c search_path=procrastinate,public"}
        )
    )

    queue.task(
        import_item.func,
        name=import_item.name,
        queue=import_item.queue,
        retry=import_item.retry_strategy,
        pass_context=import_item.pass_context,
    )
    return queue

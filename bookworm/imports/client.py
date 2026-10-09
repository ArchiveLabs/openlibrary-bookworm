import logging
import random
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class ImportResult:
    success: bool
    error_code: str | None = None
    description: str | None = None
    retryable: bool = False
    unknown: bool = False


class OpenLibraryClient:
    def import_record(self, record: dict[str, Any]) -> ImportResult:
        # Temporary concurrency test; replace with the real Open Library request.
        delay = random.uniform(2, 5)
        logger.info("import_start title=%s delay=%.2fs", record["title"], delay)
        time.sleep(delay)
        logger.info("import_finish title=%s", record["title"])
        return ImportResult(success=True)

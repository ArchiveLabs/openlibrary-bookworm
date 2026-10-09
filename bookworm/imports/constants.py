NON_RETRYABLE_CODES = {
    "INVALID_RECORD",
    "INVALID_SOURCE_RECORD",
    "DUPLICATE_SOURCE",
    "OUTCOME_UNKNOWN",
}


def error_context(code: str, description: str) -> dict[str, str]:
    return {"error_code": code, "description": description}

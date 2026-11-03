"""Fail-closed first phase: prove one-row Graph write before data sync exists."""
from __future__ import annotations

from hashlib import sha256

from .graph import GraphWorkbook, durable_backup
from .safe_xlsx import WorkbookSafetyError, append_run_log_only


class ControlledTestError(RuntimeError):
    """A safe, user-visible diagnostic stage for the controlled write test."""


def required(env: dict, name: str) -> str:
    value = env.get(name)
    if not value:
        raise RuntimeError(f"Missing required setting: {name}")
    return value


def safe_storage_failure(error: Exception) -> str:
    """Report only a normalized storage failure class, never connection details."""
    allowed = {
        "ClientAuthenticationError",
        "HttpResponseError",
        "ResourceExistsError",
        "ResourceNotFoundError",
        "ServiceRequestError",
        "ServiceResponseError",
        "ValueError",
    }
    kind = type(error).__name__
    if kind not in allowed:
        return "Azure backup failed (unexpected storage error)"
    status = getattr(error, "status_code", None)
    suffix = f", HTTP {status}" if isinstance(status, int) else ""
    return f"Azure backup failed ({kind}{suffix})"


def execute(env: dict) -> str:
    mode = env.get("RUN_MODE", "preflight")
    try:
        graph = GraphWorkbook(required(env, "GRAPH_DRIVE_ID"), required(env, "GRAPH_ITEM_ID"))
        metadata = graph.metadata()
    except Exception as error:
        if mode == "run_log_test":
            raise ControlledTestError("Target workbook verification failed") from error
        raise
    if metadata.get("name") != "AI_Stock_Trading_Simulator_v1.xlsx" or not metadata.get("eTag"):
        raise RuntimeError("Exact target workbook/version could not be verified")
    if mode == "preflight":
        return f"DATA REDO — verified {metadata['name']} version {metadata['eTag']}; no write requested"
    if mode != "run_log_test":
        raise RuntimeError("RUN_MODE must be preflight or run_log_test")
    try:
        original = graph.download()
    except Exception as error:
        raise ControlledTestError("Workbook download failed") from error
    if len(original) != metadata.get("size"):
        raise ControlledTestError("Downloaded file size differs from verified metadata")
    try:
        backup = durable_backup(
            original,
            required(env, "AzureWebJobsStorage"),
            env.get("BACKUP_CONTAINER", "workbook-backups"),
            metadata["eTag"],
        )
    except Exception as error:
        raise ControlledTestError(safe_storage_failure(error)) from error
    try:
        changed = append_run_log_only(
            original,
            "RUN-AZURE-CONTROLLED-LOG-TEST",
            metadata["eTag"],
        )
    except WorkbookSafetyError as error:
        raise ControlledTestError("Run_Log safety validation failed") from error
    except Exception as error:
        raise ControlledTestError("Run_Log preparation failed") from error
    try:
        uploaded = graph.replace(changed, metadata["eTag"])
    except Exception as error:
        raise ControlledTestError("OneDrive upload failed") from error
    try:
        verified = graph.download()
    except Exception as error:
        raise ControlledTestError("Post-upload verification download failed") from error
    if sha256(verified).digest() != sha256(changed).digest():
        raise ControlledTestError("Post-upload byte verification failed")
    return f"DATA UPPDATERAD — controlled Run_Log test verified; backup {backup}; version {uploaded.get('eTag', 'unknown')}"

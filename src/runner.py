"""Fail-closed workbook operations: preflight, controlled test, and data-only sync."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

from .graph import BackupFailure, GraphWorkbook, durable_backup
from .market_data import MarketDataPreflightError, load_validated_market_data
from .safe_xlsx import WorkbookSafetyError, append_market_data_and_run_log, append_run_log_only


class ControlledTestError(RuntimeError):
    """A safe, user-visible diagnostic stage for the controlled write test."""


class DataSyncError(RuntimeError):
    """A safe, user-visible failure for the data-only workbook update."""


def required(env: dict, name: str) -> str:
    value = env.get(name)
    if not value:
        raise RuntimeError(f"Missing required setting: {name}")
    return value


def safe_storage_failure(error: Exception) -> str:
    """Report only a normalized storage failure class, never connection details."""
    if isinstance(error, BackupFailure):
        return str(error)
    kind = type(error).__name__
    status = getattr(error, "status_code", None)
    suffix = f", HTTP {status}" if isinstance(status, int) else ""
    return f"Azure backup failed ({kind}{suffix})"


def _verified_workbook(env: dict) -> tuple[GraphWorkbook, dict]:
    graph = GraphWorkbook(required(env, "GRAPH_DRIVE_ID"), required(env, "GRAPH_ITEM_ID"))
    metadata = graph.metadata()
    if metadata.get("name") != "AI_Stock_Trading_Simulator_v1.xlsx" or not metadata.get("eTag"):
        raise RuntimeError("Exact target workbook/version could not be verified")
    return graph, metadata


def _download_and_backup(env: dict, graph: GraphWorkbook, metadata: dict) -> tuple[bytes, str]:
    original = graph.download()
    if len(original) != metadata.get("size"):
        raise RuntimeError("Downloaded file size differs from verified metadata")
    backup = durable_backup(
        original,
        required(env, "AzureWebJobsStorage"),
        env.get("BACKUP_CONTAINER", "workbook-backups"),
        metadata["eTag"],
    )
    return original, backup


def _replace_and_verify(graph: GraphWorkbook, changed: bytes, etag: str) -> dict:
    uploaded = graph.replace(changed, etag)
    verified = graph.download()
    if sha256(verified).digest() != sha256(changed).digest():
        raise RuntimeError("Post-upload byte verification failed")
    return uploaded


def execute(env: dict) -> str:
    mode = env.get("RUN_MODE", "preflight")
    try:
        graph, metadata = _verified_workbook(env)
    except Exception as error:
        if mode == "run_log_test":
            raise ControlledTestError("Target workbook verification failed") from error
        if mode == "data_sync":
            raise DataSyncError("Target workbook verification failed") from error
        raise

    if mode == "preflight":
        return f"DATA REDO — verified {metadata['name']} version {metadata['eTag']}; no write requested"

    if mode == "run_log_test":
        try:
            original, backup = _download_and_backup(env, graph, metadata)
            changed = append_run_log_only(
                original,
                "RUN-AZURE-CONTROLLED-LOG-TEST",
                metadata["eTag"],
            )
            uploaded = _replace_and_verify(graph, changed, metadata["eTag"])
        except WorkbookSafetyError as error:
            raise ControlledTestError("Run_Log safety validation failed") from error
        except Exception as error:
            raise ControlledTestError(safe_storage_failure(error)) from error
        return (
            "DATA UPPDATERAD — controlled Run_Log test verified; "
            f"backup {backup}; version {uploaded.get('eTag', 'unknown')}"
        )

    if mode != "data_sync":
        raise RuntimeError("RUN_MODE must be preflight, run_log_test or data_sync")

    try:
        validated = load_validated_market_data(env)
        original, backup = _download_and_backup(env, graph, metadata)
        run_id = f"RUN-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-EODHD-SYNC"
        changed = append_market_data_and_run_log(
            original,
            validated,
            run_id,
            metadata["eTag"],
        )
        uploaded = _replace_and_verify(graph, changed, metadata["eTag"])
    except MarketDataPreflightError as error:
        raise DataSyncError(str(error)) from error
    except WorkbookSafetyError as error:
        raise DataSyncError(str(error)) from error
    except Exception as error:
        raise DataSyncError(safe_storage_failure(error)) from error
    return (
        f"DATA UPPDATERAD — {validated.session_date}; 6 validated EODHD rows and one Run_Log row "
        f"were added after backup {backup}; version {uploaded.get('eTag', 'unknown')}. "
        "Signals, orders, holdings and transactions were not changed."
    )

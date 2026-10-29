"""Fail-closed first phase: prove one-row Graph write before data sync exists."""
from __future__ import annotations

from hashlib import sha256

from .graph import GraphWorkbook, durable_backup
from .safe_xlsx import WorkbookSafetyError, append_run_log_only


def required(env: dict, name: str) -> str:
    value = env.get(name)
    if not value:
        raise RuntimeError(f"Missing required setting: {name}")
    return value


def execute(env: dict) -> str:
    mode = env.get("RUN_MODE", "preflight")
    graph = GraphWorkbook(required(env, "GRAPH_DRIVE_ID"), required(env, "GRAPH_ITEM_ID"))
    metadata = graph.metadata()
    if metadata.get("name") != "AI_Stock_Trading_Simulator_v1.xlsx" or not metadata.get("eTag"):
        raise RuntimeError("Exact target workbook/version could not be verified")
    if mode == "preflight":
        return f"DATA REDO — verified {metadata['name']} version {metadata['eTag']}; no write requested"
    if mode != "run_log_test":
        raise RuntimeError("RUN_MODE must be preflight or run_log_test")
    original = graph.download()
    if len(original) != metadata.get("size"):
        raise RuntimeError("Downloaded file size differs from verified metadata")
    backup = durable_backup(original, required(env, "AzureWebJobsStorage"), env.get("BACKUP_CONTAINER", "workbook-backups"), metadata["eTag"])
    try:
        changed = append_run_log_only(original, "RUN-AZURE-CONTROLLED-LOG-TEST", metadata["eTag"])
    except WorkbookSafetyError as error:
        raise RuntimeError(f"Workbook safety check failed: {error}") from error
    uploaded = graph.replace(changed, metadata["eTag"])
    if sha256(graph.download()).digest() != sha256(changed).digest():
        raise RuntimeError("Post-upload byte verification failed")
    return f"DATA UPPDATERAD — controlled Run_Log test verified; backup {backup}; version {uploaded.get('eTag', 'unknown')}"

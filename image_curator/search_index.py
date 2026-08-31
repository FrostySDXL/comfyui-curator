"""Rebuildable media search indexes for filenames and local metadata."""

from __future__ import annotations

import json
import hashlib
import os
import re
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import batch_store
from .sidecar_metadata import extract_media_metadata, json_sidecar_candidates


SEARCH_INDEX_FILENAME = "search-index.json"
SEARCH_INDEX_VERSION = 1
SEARCH_QUERY_MAX_CHARS = 256
SEARCH_RESULT_LIMIT = 200
SEARCH_RESULT_LIMIT_MAX = 500
SIDECAR_SEARCH_MAX_DEPTH = 8
SIDECAR_SEARCH_MAX_VALUES = 1000
SIDECAR_SEARCH_MAX_CHARS = 64 * 1024
SIDECAR_SUMMARY_STRING_MAX_CHARS = 4096
SEARCH_INDEX_CACHE_MAX_ENTRIES = 32

_LOCK = threading.RLock()
_INDEX_CACHE: OrderedDict[tuple[str, int, int, int], dict[str, Any]] = OrderedDict()
_SEPARATOR_RE = re.compile(r"[_\-]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


class SearchIndexBuildCancelled(Exception):
    """Raised when a cooperative search-index build cancellation is requested."""


def _normalize(value: object) -> str:
    text = _CAMEL_BOUNDARY_RE.sub(" ", str(value))
    return " ".join(_SEPARATOR_RE.sub(" ", text.casefold()).split())


def _cache_path(batches_dir: Path, batch: str) -> Path:
    batch_store._validate_name(batch, "batch name")
    return Path(batches_dir) / batch / SEARCH_INDEX_FILENAME


def _resolved_batch(batches_dir: Path, batch: str) -> tuple[Path, Path, Path]:
    batch_store._validate_name(batch, "batch name")
    root = Path(batches_dir).resolve()
    batch_dir = Path(batches_dir) / batch
    if batch_dir.is_symlink() or not batch_dir.is_dir():
        raise ValueError("Unsafe search index path")
    resolved_batch = batch_dir.resolve()
    try:
        resolved_batch.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("Unsafe search index path") from exc
    return root, batch_dir, resolved_batch


def _safe_stage(root: Path, batch_dir: Path, resolved_batch: Path, folder: str) -> Path:
    stage = batch_dir / folder
    try:
        if stage.is_symlink() or not stage.is_dir():
            raise ValueError("Unsafe search index path")
        resolved = stage.resolve()
        resolved.relative_to(root)
        resolved.relative_to(resolved_batch)
    except (OSError, ValueError) as exc:
        raise ValueError("Unsafe search index path") from exc
    return resolved


def _safe_cache_target(root: Path, resolved_batch: Path, path: Path) -> bool:
    try:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            return False
        resolved = path.resolve()
        resolved.relative_to(root)
        resolved.relative_to(resolved_batch)
        return True
    except (OSError, ValueError):
        return False


def _flatten_sidecar(value: Any) -> tuple[str, dict[str, Any]]:
    parts: list[str] = []
    summary: dict[str, Any] = {}
    char_count = 0
    value_count = 0
    summary_keys = {
        "category",
        "subcategory",
        "tags",
        "title",
        "author",
        "artist",
        "website",
        "site",
        "source",
        "id",
        "post_id",
        "favorite_id",
        "url",
    }

    def append(token: object) -> bool:
        nonlocal char_count, value_count
        if value_count >= SIDECAR_SEARCH_MAX_VALUES or char_count >= SIDECAR_SEARCH_MAX_CHARS:
            return False
        text = str(token)[:4096]
        remaining = SIDECAR_SEARCH_MAX_CHARS - char_count
        text = text[:remaining]
        if text:
            parts.append(text)
            char_count += len(text)
            value_count += 1
        return char_count < SIDECAR_SEARCH_MAX_CHARS

    def walk(node: Any, depth: int, top_key: str | None = None) -> None:
        if depth > SIDECAR_SEARCH_MAX_DEPTH or char_count >= SIDECAR_SEARCH_MAX_CHARS:
            return
        if isinstance(node, dict):
            for key, child in node.items():
                key_text = str(key)
                if not append(key_text):
                    return
                if (
                    depth == 0
                    and key_text in summary_keys
                    and isinstance(child, (str, int, float, bool))
                ):
                    summary[key_text] = (
                        child[:SIDECAR_SUMMARY_STRING_MAX_CHARS]
                        if isinstance(child, str)
                        else child
                    )
                walk(child, depth + 1, key_text)
            return
        if isinstance(node, list):
            for child in node:
                walk(child, depth + 1, top_key)
            return
        if node is None:
            return
        append(node)

    walk(value, 0)
    return " ".join(parts), summary


def _stat_fingerprint(stat_result, *, name: str | None = None) -> dict[str, int | str]:
    fingerprint: dict[str, int | str] = {
        "device": int(stat_result.st_dev),
        "inode": int(stat_result.st_ino),
        "size": int(stat_result.st_size),
        "mtime_ns": int(stat_result.st_mtime_ns),
    }
    if name is not None:
        fingerprint["name"] = name
    return fingerprint


def _file_fingerprint(path: Path) -> dict[str, Any]:
    """Return the identity and metadata fingerprint used for safe reuse."""
    media_stat = path.stat()
    sidecar_fingerprint: dict[str, Any] | None = None
    for candidate in json_sidecar_candidates(path):
        try:
            if candidate.is_symlink():
                # inspect_json_sidecar treats the preferred symlink as an error;
                # retain that fact so a later rebuild cannot reuse old metadata.
                sidecar_fingerprint = {"symlink": True}
                break
            if candidate.is_file():
                sidecar_stat = candidate.stat()
                sidecar_fingerprint = _stat_fingerprint(sidecar_stat)
                break
        except OSError:
            continue
    return {"media": _stat_fingerprint(media_stat, name=path.name), "sidecar": sidecar_fingerprint}


def _entry_fingerprint(
    entry: os.DirEntry[str], entries_by_name: dict[str, os.DirEntry[str]]
) -> dict[str, Any]:
    """Build a fingerprint from one scandir result and its adjacent sidecar."""
    media_stat = entry.stat(follow_symlinks=False)
    sidecar_fingerprint: dict[str, Any] | None = None
    media_path = Path(entry.path)
    for candidate in json_sidecar_candidates(media_path):
        sidecar_entry = entries_by_name.get(os.path.normcase(candidate.name))
        if sidecar_entry is None:
            continue
        try:
            if sidecar_entry.is_symlink():
                sidecar_fingerprint = {"symlink": True}
                break
            if sidecar_entry.is_file(follow_symlinks=False):
                sidecar_fingerprint = _stat_fingerprint(sidecar_entry.stat(follow_symlinks=False))
                break
        except OSError:
            continue
    return {
        "media": _stat_fingerprint(media_stat, name=entry.name),
        "sidecar": sidecar_fingerprint,
    }


def _fingerprint_key(fingerprint: Any) -> str | None:
    if not isinstance(fingerprint, dict):
        return None
    media = fingerprint.get("media")
    if (
        not isinstance(media, dict)
        or not isinstance(media.get("name"), str)
        or not all(
            isinstance(media.get(key), int) for key in ("device", "inode", "size", "mtime_ns")
        )
    ):
        return None
    sidecar = fingerprint.get("sidecar")
    if sidecar is not None:
        if not isinstance(sidecar, dict):
            return None
        if sidecar.get("symlink") is not True and not all(
            isinstance(sidecar.get(key), int) for key in ("device", "inode", "size", "mtime_ns")
        ):
            return None
    return json.dumps(fingerprint, sort_keys=True, separators=(",", ":"))


def _build_item(
    batch: str,
    folder: str,
    path: Path,
    *,
    fingerprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stat = path.stat()
    fingerprint = fingerprint or _file_fingerprint(path)
    metadata = extract_media_metadata(path)
    sidecar = metadata.get("sidecar") or {}
    sidecar_text = ""
    sidecar_summary: dict[str, Any] = {}
    if sidecar.get("error") is None and "data" in sidecar:
        sidecar_text, sidecar_summary = _flatten_sidecar(sidecar["data"])
    parameters = metadata.get("parameters") or {}
    prompt = str(parameters.get("prompt") or "").strip()
    negative_prompt = str(parameters.get("negative_prompt") or "").strip()
    seed = parameters.get("seed")
    model = parameters.get("model")
    sampler = parameters.get("sampler")
    loras = [
        str(lora.get("name"))
        for lora in metadata.get("loras") or []
        if isinstance(lora, dict) and lora.get("name")
    ]
    fields = {
        "filename": path.name,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "seed": "" if seed is None else str(seed),
        "model": "" if model is None else str(model),
        "sampler": "" if sampler is None else str(sampler),
        "lora": " ".join(loras),
        "sidecar": sidecar_text,
    }
    sources = []
    if metadata.get("has_png_metadata"):
        sources.append("png")
    if sidecar_text:
        sources.append("sidecar")
    return {
        "batch": batch,
        "folder": folder,
        "name": path.name,
        "size": stat.st_size,
        "mtime": stat.st_mtime_ns,
        "fingerprint": fingerprint,
        "media_kind": batch_store.media_kind(path),
        "mime": batch_store.media_mime(path),
        "metadata_sources": sources,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "seed": seed,
        "model": model,
        "sampler": sampler,
        "loras": loras,
        "sidecar_summary": sidecar_summary,
        "_search_fields": fields,
        "_search_text": _normalize(" ".join(fields.values())),
    }


def _check_cancelled(cancel_check) -> None:
    if cancel_check is not None and cancel_check():
        raise SearchIndexBuildCancelled


def _source_state(batches_dir: Path, batch: str, *, cancel_check=None) -> dict[str, dict[str, int]]:
    root, batch_dir, resolved_batch = _resolved_batch(batches_dir, batch)
    state: dict[str, dict[str, int]] = {}
    for folder in batch_store.BATCH_FOLDERS:
        _check_cancelled(cancel_check)
        stage = _safe_stage(root, batch_dir, resolved_batch, folder)
        state[folder] = {
            "mtime_ns": stage.stat().st_mtime_ns,
            "item_count": len(
                batch_store.get_images(
                    stage,
                    sort_by="name",
                    order="asc",
                    cancel_check=lambda: _check_cancelled(cancel_check),
                )
            ),
        }
    return state


def _compact_source_state(batches_dir: Path, batch: str) -> dict[str, dict[str, int]]:
    """Read stage metadata without enumerating the media in each stage."""
    root, batch_dir, resolved_batch = _resolved_batch(batches_dir, batch)
    state: dict[str, dict[str, int]] = {}
    for folder in batch_store.BATCH_FOLDERS:
        stage = _safe_stage(root, batch_dir, resolved_batch, folder)
        state[folder] = {"mtime_ns": stage.stat().st_mtime_ns}
    return state


def _source_state_matches(index_state: Any, live_state: Any) -> bool:
    if not isinstance(index_state, dict) or not isinstance(live_state, dict):
        return False
    for folder in batch_store.BATCH_FOLDERS:
        cached_stage = index_state.get(folder)
        live_stage = live_state.get(folder)
        if not isinstance(cached_stage, dict) or not isinstance(live_stage, dict):
            return False
        if cached_stage.get("mtime_ns") != live_stage.get("mtime_ns"):
            return False
    return True


def _enumerate_manifest(
    batches_dir: Path, batch: str, *, cancel_check=None
) -> tuple[list[tuple[str, Path, dict[str, Any]]], dict[str, dict[str, int]]]:
    """Enumerate safe media and fingerprints, plus stage state for one snapshot."""
    root, batch_dir, resolved_batch = _resolved_batch(batches_dir, batch)
    records: list[tuple[str, Path, dict[str, Any]]] = []
    state: dict[str, dict[str, int]] = {}
    for folder in batch_store.BATCH_FOLDERS:
        _check_cancelled(cancel_check)
        stage = _safe_stage(root, batch_dir, resolved_batch, folder)
        try:
            with os.scandir(stage) as iterator:
                entries_by_name: dict[str, os.DirEntry[str]] = {}
                for entry in iterator:
                    _check_cancelled(cancel_check)
                    entries_by_name.setdefault(os.path.normcase(entry.name), entry)
        except OSError:
            raise ValueError("Unsafe search index path") from None
        media_entries = []
        for entry in entries_by_name.values():
            try:
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    continue
                if Path(entry.name).suffix.lower() not in batch_store.VIEWABLE_MEDIA_EXTENSIONS:
                    continue
                media_entries.append(entry)
            except OSError:
                continue
        media_entries.sort(key=lambda entry: entry.name.lower())
        state[folder] = {"mtime_ns": stage.stat().st_mtime_ns, "item_count": 0}
        for entry in media_entries:
            _check_cancelled(cancel_check)
            try:
                path = stage / entry.name
                fingerprint = _entry_fingerprint(entry, entries_by_name)
            except OSError:
                continue
            records.append((folder, path, fingerprint))
            state[folder]["item_count"] += 1
    return records, state


def _manifest_signature(
    records: list[tuple[str, Path, dict[str, Any]]], state: dict[str, dict[str, int]]
) -> tuple[tuple[tuple[str, dict[str, int]], ...], tuple[tuple[str, str, str], ...]]:
    files = tuple(
        (folder, path.name, _fingerprint_key(fingerprint) or "")
        for folder, path, fingerprint in records
    )
    return (tuple(sorted(state.items())), tuple(sorted(files)))


def _cache_key(path: Path, stat_result) -> tuple[str, int, int, int]:
    return (str(path.resolve()), stat_result.st_ino, stat_result.st_size, stat_result.st_mtime_ns)


def _cache_put(key: tuple[str, int, int, int], index: dict[str, Any]) -> None:
    with _LOCK:
        _INDEX_CACHE[key] = index
        _INDEX_CACHE.move_to_end(key)
        while len(_INDEX_CACHE) > SEARCH_INDEX_CACHE_MAX_ENTRIES:
            _INDEX_CACHE.popitem(last=False)


def _cache_remove_path(path: Path) -> None:
    identity = str(path.resolve())
    with _LOCK:
        for key in list(_INDEX_CACHE):
            if key[0] == identity:
                del _INDEX_CACHE[key]


def _save_index(
    batches_dir: Path, batch: str, index: dict[str, Any], *, temp_path: Path | None = None
) -> None:
    with _LOCK:
        root, _batch_dir, resolved_batch = _resolved_batch(batches_dir, batch)
        path = _cache_path(batches_dir, batch)
        tmp_path = (
            Path(temp_path) if temp_path is not None else path.with_suffix(path.suffix + ".tmp")
        )
        if not _safe_cache_target(root, resolved_batch, path) or not _safe_cache_target(
            root, resolved_batch, tmp_path
        ):
            raise ValueError("Unsafe search index path")
        tmp_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(path)
        _cache_remove_path(path)
        _cache_put(_cache_key(path, path.stat()), index)


def build_search_index(
    batches_dir: Path,
    batch: str,
    *,
    cancel_check=None,
    progress_callback=None,
    commit_check=None,
    temp_path: Path | None = None,
) -> dict[str, Any]:
    """Build and atomically persist one batch's media metadata search index."""
    initial_records, initial_state = _enumerate_manifest(
        batches_dir, batch, cancel_check=cancel_check
    )
    prior = load_search_index(batches_dir, batch)
    prior_by_fingerprint: dict[str, list[dict[str, Any]]] = {}
    if prior is not None:
        for item in prior.get("items", []):
            key = _fingerprint_key(item.get("fingerprint"))
            if key is not None:
                prior_by_fingerprint.setdefault(key, []).append(item)
    current_counts: dict[str, int] = {}
    for _folder, _path, fingerprint in initial_records:
        key = _fingerprint_key(fingerprint)
        if key is not None:
            current_counts[key] = current_counts.get(key, 0) + 1

    total = len(initial_records)
    if progress_callback is not None:
        progress_callback(0, total)
    items: list[dict[str, Any]] = []
    reused_count = 0
    scanned_count = 0
    for folder, path, fingerprint in initial_records:
        _check_cancelled(cancel_check)
        key = _fingerprint_key(fingerprint)
        candidates = prior_by_fingerprint.get(key, []) if key is not None else []
        if key is not None and len(candidates) == 1 and current_counts.get(key) == 1:
            item = dict(candidates[0])
            item["batch"] = batch
            item["folder"] = folder
            item["name"] = path.name
            item["size"] = fingerprint["media"]["size"]
            item["mtime"] = fingerprint["media"]["mtime_ns"]
            item["media_kind"] = batch_store.media_kind(path)
            item["mime"] = batch_store.media_mime(path)
            item["fingerprint"] = fingerprint
            fields = dict(item.get("_search_fields") or {})
            fields["filename"] = path.name
            item["_search_fields"] = fields
            item["_search_text"] = _normalize(" ".join(fields.values()))
            items.append(item)
            reused_count += 1
        else:
            try:
                item = _build_item(batch, folder, path)
            except OSError:
                raise ValueError("Search index source changed during build") from None
            item["fingerprint"] = fingerprint
            items.append(item)
            scanned_count += 1
        if progress_callback is not None:
            progress_callback(len(items), total)
    _check_cancelled(cancel_check)
    if commit_check is not None:
        commit_check()
    final_records, final_state = _enumerate_manifest(batches_dir, batch, cancel_check=cancel_check)
    if _manifest_signature(initial_records, initial_state) != _manifest_signature(
        final_records, final_state
    ):
        raise ValueError("Search index source changed during build")
    _check_cancelled(cancel_check)
    index = {
        "version": SEARCH_INDEX_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "batch": batch,
        "item_count": len(items),
        "source_state": final_state,
        "items": items,
        "reused_count": reused_count,
        "scanned_count": scanned_count,
        "changed_count": scanned_count,
    }
    _check_cancelled(cancel_check)
    # Re-run the caller's commit gate after the final source snapshot.  This
    # keeps the save boundary explicit for job cancellation and shutdown.
    if commit_check is not None:
        commit_check()
    _save_index(batches_dir, batch, index, temp_path=temp_path)
    return index


def summarize_search_index(index: dict[str, Any]) -> dict[str, Any]:
    """Return the bounded build response without echoing the full cached corpus."""
    return {
        "version": index.get("version"),
        "built_at": index.get("built_at"),
        "batch": index.get("batch"),
        "item_count": index.get("item_count", 0),
        "reused_count": index.get("reused_count", 0),
        "scanned_count": index.get("scanned_count", 0),
        "changed_count": index.get("changed_count", 0),
    }


def load_search_index(batches_dir: Path, batch: str) -> dict[str, Any] | None:
    """Load a safe, schema-compatible search index or return ``None``."""
    try:
        root, _batch_dir, resolved_batch = _resolved_batch(batches_dir, batch)
        path = _cache_path(batches_dir, batch)
        if not path.is_file() or not _safe_cache_target(root, resolved_batch, path):
            _cache_remove_path(path)
            return None
        stat_result = path.stat()
        key = _cache_key(path, stat_result)
        with _LOCK:
            cached = _INDEX_CACHE.get(key)
            if cached is not None:
                _INDEX_CACHE.move_to_end(key)
                return cached
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != SEARCH_INDEX_VERSION:
        return None
    if data.get("batch") != batch or not isinstance(data.get("items"), list):
        return None
    source_state = data.get("source_state")
    if not isinstance(source_state, dict):
        return None
    for folder in batch_store.BATCH_FOLDERS:
        stage_state = source_state.get(folder)
        if not isinstance(stage_state, dict) or not isinstance(stage_state.get("mtime_ns"), int):
            return None
    for item in data["items"]:
        if not isinstance(item, dict):
            return None
        if item.get("batch") != batch or item.get("folder") not in batch_store.BATCH_FOLDERS:
            return None
        name = item.get("name")
        if not isinstance(name, str):
            return None
        try:
            batch_store._validate_name(name, "file name")
        except ValueError:
            return None
        if not isinstance(item.get("_search_text"), str) or not isinstance(
            item.get("_search_fields"), dict
        ):
            return None
    with _LOCK:
        _cache_put(key, data)
    return data


def _public_item(item: dict[str, Any], tokens: list[str]) -> dict[str, Any]:
    fields = item.get("_search_fields") or {}
    matched_fields = [
        name
        for name, value in fields.items()
        if any(token in _normalize(value) for token in tokens)
    ]
    return {key: value for key, value in item.items() if not key.startswith("_")} | {
        "matched_fields": matched_fields
    }


def _query_snapshot(
    query: str,
    batch: str | None,
    folder: str | None,
    index_states: list[dict[str, Any]],
) -> str:
    payload = {
        "query": query,
        "batch": batch,
        "folder": folder,
        "indexes": index_states,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def query_search_indices(
    batches_dir: Path,
    query: str,
    *,
    batch: str | None = None,
    folder: str | None = None,
    limit: int = SEARCH_RESULT_LIMIT,
    offset: int = 0,
    snapshot: str | None = None,
) -> dict[str, Any]:
    """Query built indexes using case-insensitive AND-token matching."""
    query = str(query or "").strip()[:SEARCH_QUERY_MAX_CHARS]
    tokens = _normalize(query).split()
    limit = max(1, min(int(limit), SEARCH_RESULT_LIMIT_MAX))
    offset = max(0, int(offset))
    batches = [batch] if batch else batch_store.get_batches(Path(batches_dir))
    loaded_indexes: list[tuple[str, dict[str, Any] | None]] = [
        (batch_name, load_search_index(batches_dir, batch_name)) for batch_name in batches
    ]
    index_statuses: list[dict[str, Any]] = []
    stale_by_batch: dict[str, bool] = {}
    searchable_by_batch: dict[str, bool] = {}
    for batch_name, index in loaded_indexes:
        if index is None:
            stale_by_batch[batch_name] = False
            searchable_by_batch[batch_name] = False
            index_statuses.append(
                {
                    "batch": batch_name,
                    "status": "not_built",
                    "built_at": None,
                    "item_count": 0,
                }
            )
            continue
        try:
            stale = not _source_state_matches(
                index.get("source_state"), _compact_source_state(batches_dir, batch_name)
            )
            searchable = True
        except (OSError, ValueError):
            stale = True
            searchable = False
        stale_by_batch[batch_name] = stale
        searchable_by_batch[batch_name] = searchable
        index_statuses.append(
            {
                "batch": batch_name,
                "status": "stale" if stale else "ready",
                "built_at": index.get("built_at"),
                "item_count": index.get("item_count", len(index.get("items", []))),
            }
        )
    snapshot_value = _query_snapshot(
        query,
        batch,
        folder,
        [
            {
                "batch": batch_name,
                "built_at": index.get("built_at") if index else None,
                "source_state": index.get("source_state") if index else None,
            }
            for batch_name, index in loaded_indexes
        ],
    )
    if snapshot is not None and snapshot != snapshot_value:
        return {
            "query": query,
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "next_offset": None,
            "has_more": False,
            "truncated": False,
            "snapshot": snapshot_value,
            "snapshot_expired": True,
            "indexed_batches": [],
            "missing_batches": [],
            "stale_batches": [],
            "index_statuses": index_statuses,
        }

    matches: list[dict[str, Any]] = []
    indexed_batches: list[str] = []
    missing_batches: list[str] = []
    stale_batches: list[str] = []
    for batch_name, index in loaded_indexes:
        if index is None:
            missing_batches.append(batch_name)
            continue
        stale = stale_by_batch[batch_name]
        if stale:
            stale_batches.append(batch_name)
        if not searchable_by_batch[batch_name]:
            continue
        indexed_batches.append(batch_name)
        for item in index["items"]:
            if folder and item.get("folder") != folder:
                continue
            search_text = item.get("_search_text", "")
            if tokens and not all(token in search_text for token in tokens):
                continue
            matches.append(item)
    matches.sort(
        key=lambda item: (item["batch"].casefold(), item["folder"], item["name"].casefold())
    )
    total = len(matches)
    page_matches = matches[offset : offset + limit]
    items = [_public_item(item, tokens) for item in page_matches]
    next_offset = offset + len(items)
    has_more = next_offset < total
    return {
        "query": query,
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": next_offset if has_more else None,
        "has_more": has_more,
        "truncated": has_more,
        "snapshot": snapshot_value,
        "snapshot_expired": False,
        "indexed_batches": indexed_batches,
        "missing_batches": missing_batches,
        "stale_batches": stale_batches,
        "index_statuses": index_statuses,
    }

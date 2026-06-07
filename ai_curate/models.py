"""
ai_curate.models -- Data models for AI curation runs.

Defines the structure of a curation run, per-image results,
and queue job states. These are the internal contracts that
storage, queue, and API layers all depend on.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from ai_curate.config import DEFAULT_TOP_N


class JobState(str, Enum):
    """Lifecycle states for a curation job."""

    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImageResult:
    """Score result for a single image within a run."""

    __slots__ = (
        "filename",
        "score",
        "total",
        "details",
        "failed",
        "error_message",
        "moved_to",
    )

    def __init__(
        self,
        filename: str,
        score: int = -1,
        total: int = 0,
        details: Optional[Dict[int, str]] = None,
        failed: bool = False,
        error_message: str = "",
        moved_to: Optional[str] = None,
    ):
        self.filename = filename
        self.score = score
        self.total = total
        self.details = details or {}
        self.failed = failed
        self.error_message = error_message
        self.moved_to = moved_to

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "filename": self.filename,
            "score": self.score,
            "total": self.total,
            "details": {str(k): v for k, v in self.details.items()},
            "failed": self.failed,
        }
        if self.error_message:
            d["error_message"] = self.error_message
        if self.moved_to is not None:
            d["moved_to"] = self.moved_to
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImageResult":
        details = {}
        for k, v in data.get("details", {}).items():
            try:
                details[int(k)] = v
            except (ValueError, TypeError):
                pass
        return cls(
            filename=data["filename"],
            score=data.get("score", -1),
            total=data.get("total", 0),
            details=details,
            failed=data.get("failed", False),
            error_message=data.get("error_message", ""),
            moved_to=data.get("moved_to"),
        )


class RunTotals:
    """Aggregate counts for a completed run."""

    __slots__ = ("images", "scored", "failed", "moved")

    def __init__(
        self,
        images: int = 0,
        scored: int = 0,
        failed: int = 0,
        moved: int = 0,
    ):
        self.images = images
        self.scored = scored
        self.failed = failed
        self.moved = moved

    def to_dict(self) -> Dict[str, int]:
        return {
            "images": self.images,
            "scored": self.scored,
            "failed": self.failed,
            "moved": self.moved,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunTotals":
        return cls(
            images=data.get("images", 0),
            scored=data.get("scored", 0),
            failed=data.get("failed", 0),
            moved=data.get("moved", 0),
        )


class CurationRun:
    """Full metadata and results for one AI curation run."""

    def __init__(
        self,
        run_id: Optional[str] = None,
        batch: str = "",
        source_folder: str = "inbox",
        destination_folder: Optional[str] = None,
        move_enabled: bool = False,
        prompt: str = "",
        elements: Optional[List[str]] = None,
        model: str = "",
        top_n: int = DEFAULT_TOP_N,
        status: str = JobState.QUEUED,
        created_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        totals: Optional[RunTotals] = None,
        results: Optional[List[ImageResult]] = None,
        error_message: str = "",
    ):
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.batch = batch
        self.source_folder = source_folder
        self.destination_folder = destination_folder
        self.move_enabled = move_enabled
        self.prompt = prompt
        self.elements = elements or []
        self.model = model
        self.top_n = top_n
        self.status = status
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.completed_at = completed_at
        self.totals = totals or RunTotals()
        self.results = results or []
        self.error_message = error_message

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "run_id": self.run_id,
            "batch": self.batch,
            "source_folder": self.source_folder,
            "destination_folder": self.destination_folder,
            "move_enabled": self.move_enabled,
            "prompt": self.prompt,
            "elements": self.elements,
            "model": self.model,
            "top_n": self.top_n,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "totals": self.totals.to_dict(),
            "results": [r.to_dict() for r in self.results],
        }
        if self.error_message:
            d["error_message"] = self.error_message
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CurationRun":
        results = [ImageResult.from_dict(r) for r in data.get("results", [])]
        totals = RunTotals.from_dict(data.get("totals", {}))
        return cls(
            run_id=data.get("run_id"),
            batch=data.get("batch", ""),
            source_folder=data.get("source_folder") or "inbox",
            destination_folder=data.get("destination_folder"),
            move_enabled=data.get("move_enabled", False),
            prompt=data.get("prompt", ""),
            elements=data.get("elements") or [],
            model=data.get("model") or "",
            top_n=data.get("top_n", DEFAULT_TOP_N),
            status=data.get("status", JobState.QUEUED),
            created_at=data.get("created_at"),
            completed_at=data.get("completed_at"),
            totals=totals,
            results=results,
            error_message=data.get("error_message", ""),
        )

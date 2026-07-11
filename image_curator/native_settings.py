"""ComfyUI-owned operational settings for the native Curator adapter."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NativeCuratorSettings:
    """Resolved native paths and non-secret page configuration."""

    batch_root: Path
    import_source: Path
    state_file: Path
    available_models: tuple[str, ...] = ()
    default_model: str = ""
    watcher_enabled: bool = False
    public_export_root: Path | None = None

    @classmethod
    def from_host_paths(
        cls,
        *,
        get_system_user_directory: Callable[[str], str],
        get_output_directory: Callable[[], str],
    ) -> NativeCuratorSettings:
        system_dir = Path(get_system_user_directory("curator"))
        models = tuple(
            model.strip()
            for model in os.environ.get("IMAGE_CURATOR_MODEL", "").split(",")
            if model.strip()
        )
        return cls(
            batch_root=system_dir / "batches",
            import_source=Path(get_output_directory()),
            state_file=system_dir / "state.json",
            available_models=models,
            default_model=models[0] if models else "",
            public_export_root=system_dir / "public-exports",
        )

    def public_payload(self) -> dict[str, object]:
        """Return browser-safe settings without host paths or credentials."""
        return {
            "available_models": list(self.available_models),
            "default_model": self.default_model,
            "watcher_enabled": self.watcher_enabled,
            "public_enabled": self.public_export_root is not None,
        }

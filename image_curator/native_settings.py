"""ComfyUI-owned operational settings for the native Curator adapter."""

from __future__ import annotations

import os
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlparse

CONFIG_VERSION = 1


class NativeConfigError(ValueError):
    """A stable settings storage or validation error."""


class NativeConfigStore:
    """Thread-safe native config persistence confined to one system directory."""

    def __init__(self, system_dir: Path) -> None:
        self.system_dir = Path(system_dir)
        self.path = self.system_dir / "config.json"
        self.tmp_path = self.system_dir / "config.json.tmp"
        self._lock = threading.RLock()

    def _validate_target(self, path: Path, *, allow_missing: bool) -> None:
        try:
            current = Path(path.anchor)
            for part in path.parts[1:]:
                current /= part
                if current.is_symlink():
                    raise NativeConfigError("Unsafe settings storage")
                if current.exists() and current != path and not current.is_dir():
                    raise NativeConfigError("Unsafe settings storage")
            root = self.system_dir.resolve()
            path.resolve().relative_to(root)
            path.parent.resolve().relative_to(root)
        except NativeConfigError:
            raise
        except (OSError, ValueError) as exc:
            raise NativeConfigError("Unsafe settings storage") from exc
        if path.exists() and not path.is_file():
            raise NativeConfigError("Unsafe settings storage")
        if not allow_missing and not path.exists():
            raise NativeConfigError("Settings file does not exist")

    def load(self) -> dict[str, object]:
        with self._lock:
            self._validate_target(self.path, allow_missing=True)
            if not self.path.exists():
                return {}
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise NativeConfigError("Stored settings are invalid") from exc
            if not isinstance(data, dict) or data.get("version") != CONFIG_VERSION:
                raise NativeConfigError("Stored settings are invalid")
            expected = {
                "batch_root": str,
                "import_source": str,
                "public_export_enabled": bool,
                "public_export_root": str,
                "llm_base_url": str,
                "models": list,
                "default_model": str,
                "api_key": str,
                "request_timeout": int,
            }
            if any(
                key in data and not isinstance(data[key], kind) for key, kind in expected.items()
            ):
                raise NativeConfigError("Stored settings are invalid")
            if "models" in data and any(not isinstance(model, str) for model in data["models"]):
                raise NativeConfigError("Stored settings are invalid")
            return data

    def save(self, data: dict[str, object]) -> dict[str, object]:
        payload = {"version": CONFIG_VERSION, **data}
        with self._lock:
            created_temp = False
            try:
                self.system_dir.mkdir(parents=True, exist_ok=True)
                self._validate_target(self.path, allow_missing=True)
                self._validate_target(self.tmp_path, allow_missing=True)
                if self.tmp_path.exists():
                    raise NativeConfigError("Unsafe settings storage")
                with self.tmp_path.open("x", encoding="utf-8") as temp_file:
                    created_temp = True
                    temp_file.write(json.dumps(payload, indent=2))
                self._validate_target(self.tmp_path, allow_missing=False)
                os.replace(self.tmp_path, self.path)
            except NativeConfigError:
                if created_temp:
                    try:
                        self.tmp_path.unlink()
                    except OSError:
                        pass
                raise
            except OSError as exc:
                if created_temp:
                    try:
                        self.tmp_path.unlink()
                    except OSError:
                        pass
                raise NativeConfigError("Could not save settings") from exc
            return payload


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value is not None and value.strip() else None


def _models(value: object) -> tuple[str, ...]:
    raw = value if isinstance(value, list) else str(value or "").split(",")
    return tuple(
        dict.fromkeys(item.strip() for item in raw if isinstance(item, str) and item.strip())
    )


def _absolute_path(value: object, default: Path) -> Path:
    path = Path(str(value)) if value else default
    return path if path.is_absolute() else default


def _timeout(value: object) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return 120
    return parsed if 1 <= parsed <= 3600 else 120


def _validate_editable_directory(field: str, path: Path) -> Path:
    message = f"{field} must reference a safe directory"
    try:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current /= part
            if current.is_symlink():
                raise NativeConfigError(message)
            if current.exists() and not current.is_dir():
                raise NativeConfigError(message)
        lexical = Path(os.path.abspath(path))
        if path.resolve() != lexical:
            raise NativeConfigError(message)
    except NativeConfigError:
        raise
    except OSError as exc:
        raise NativeConfigError(message) from exc
    return path


@dataclass
class NativeCuratorSettings:
    """Resolved native paths and non-secret page configuration."""

    batch_root: Path
    import_source: Path
    state_file: Path
    available_models: tuple[str, ...] = ()
    default_model: str = ""
    public_export_root: Path | None = None
    llm_base_url: str = "http://localhost:8080"
    api_key: str | None = None
    request_timeout: int = 120
    config_store: NativeConfigStore | None = None
    config_error: bool = False

    @classmethod
    def from_host_paths(
        cls,
        *,
        get_system_user_directory: Callable[[str], str],
        get_output_directory: Callable[[], str],
    ) -> NativeCuratorSettings:
        system_dir = Path(get_system_user_directory("curator"))
        store = NativeConfigStore(system_dir)
        config_error = False
        try:
            config = store.load()
        except NativeConfigError as exc:
            if str(exc) != "Stored settings are invalid":
                raise
            config = {}
            config_error = True
        models = _models(config.get("models", _env("IMAGE_CURATOR_MODEL")))
        batch_root = _absolute_path(
            config.get("batch_root") or _env("IMAGE_CURATOR_BATCHES"), system_dir / "batches"
        )
        import_source = _absolute_path(
            config.get("import_source") or _env("IMAGE_CURATOR_COMFYUI"),
            Path(get_output_directory()),
        )
        if "public_export_enabled" in config:
            public_enabled = config["public_export_enabled"] is True
        else:
            public_enabled = True
        export_value = (
            config.get("public_export_root")
            or _env("IMAGE_CURATOR_PUBLIC_EXPORTS")
            or system_dir / "public-exports"
        )
        return cls(
            batch_root=batch_root,
            import_source=import_source,
            state_file=system_dir / "state.json",
            available_models=models,
            default_model=str(config.get("default_model") or (models[0] if models else "")),
            public_export_root=Path(str(export_value)) if public_enabled else None,
            llm_base_url=str(
                config.get("llm_base_url")
                or _env("IMAGE_CURATOR_LLM_URL")
                or "http://localhost:8080"
            ),
            api_key=(str(config["api_key"]) or None)
            if "api_key" in config
            else _env("IMAGE_CURATOR_API_KEY"),
            request_timeout=_timeout(
                config.get("request_timeout") or _env("IMAGE_CURATOR_TIMEOUT")
            ),
            config_store=store,
            config_error=config_error,
        )

    def public_payload(self) -> dict[str, object]:
        """Return browser-safe settings without host paths or credentials."""
        return {
            "available_models": list(self.available_models),
            "default_model": self.default_model,
            "public_enabled": self.public_export_root is not None,
        }

    def editable_payload(self) -> dict[str, object]:
        return {
            "batch_root": str(self.batch_root),
            "import_source": str(self.import_source),
            "public_export_enabled": self.public_export_root is not None,
            "public_export_root": str(self.public_export_root or ""),
            "llm_base_url": self.llm_base_url,
            "models": list(self.available_models),
            "default_model": self.default_model,
            "ai_api_key_set": bool(self.api_key),
            "request_timeout": self.request_timeout,
            "config_error": self.config_error,
        }

    def candidate(self, data: dict[str, object]) -> NativeCuratorSettings:
        candidate = replace(self)
        candidate.update(data, persist=False)
        return candidate

    def update(self, data: dict[str, object], *, persist: bool = True) -> dict[str, object]:
        allowed = {
            "batch_root",
            "import_source",
            "public_export_enabled",
            "public_export_root",
            "llm_base_url",
            "models",
            "default_model",
            "api_key",
            "clear_api_key",
            "request_timeout",
        }
        if set(data) - allowed:
            raise NativeConfigError("Unknown settings field")
        for key in (
            "batch_root",
            "import_source",
            "public_export_root",
            "llm_base_url",
            "default_model",
            "api_key",
        ):
            if key in data and not isinstance(data[key], str):
                raise NativeConfigError(f"{key} must be a string")
        if not isinstance(data.get("public_export_enabled"), bool):
            raise NativeConfigError("public_export_enabled must be a boolean")
        if not isinstance(data.get("clear_api_key", False), bool):
            raise NativeConfigError("clear_api_key must be a boolean")
        paths = {key: Path(str(data.get(key, ""))) for key in ("batch_root", "import_source")}
        if any(not path.is_absolute() for path in paths.values()):
            raise NativeConfigError("Paths must be absolute")
        export_enabled = data["public_export_enabled"]
        export = Path(str(data.get("public_export_root", "")))
        if export_enabled and not export.is_absolute():
            raise NativeConfigError("Public export path must be absolute")
        for field, path in paths.items():
            _validate_editable_directory(field, path)
        if export_enabled:
            _validate_editable_directory("public_export_root", export)
        url = str(data.get("llm_base_url", "")).strip()
        if urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc:
            raise NativeConfigError("LLM base URL must be HTTP or HTTPS")
        if not isinstance(data.get("models"), list) or any(
            not isinstance(model, str) for model in data["models"]
        ):
            raise NativeConfigError("Models must be a list of strings")
        models = _models(data.get("models"))
        default = str(data.get("default_model", "")).strip()
        if default and default not in models:
            raise NativeConfigError("Default model must be in the model list")
        timeout = data.get("request_timeout")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3600:
            raise NativeConfigError("Request timeout must be between 1 and 3600")
        key = (
            None
            if data.get("clear_api_key")
            else (str(data.get("api_key", "")).strip() or self.api_key)
        )
        persisted = {
            "batch_root": str(paths["batch_root"]),
            "import_source": str(paths["import_source"]),
            "public_export_enabled": export_enabled,
            "public_export_root": str(export) if export_enabled else "",
            "llm_base_url": url,
            "models": list(models),
            "default_model": default,
            "request_timeout": timeout,
            "api_key": key or "",
        }
        if persist and self.config_store is None:
            raise NativeConfigError("Settings storage is unavailable")
        if persist:
            assert self.config_store is not None
            self.config_store.save(persisted)
        self.batch_root = paths["batch_root"]
        self.import_source = paths["import_source"]
        self.public_export_root = export if export_enabled else None
        self.llm_base_url, self.available_models, self.default_model = url, models, default
        self.request_timeout, self.api_key = timeout, key
        self.config_error = False
        return self.editable_payload()

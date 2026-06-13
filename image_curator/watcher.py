"""Auto-import watcher for ComfyUI output folders."""

from collections.abc import Callable
from pathlib import Path
import threading
import time


class ImageWatcher:
    """Poll a ComfyUI output folder and import new images into the active batch."""

    def __init__(
        self,
        *,
        comfyui_output: Callable[[], Path],
        image_extensions: set[str],
        load_state: Callable[[], dict],
        get_batch_folder: Callable[[str, str], Path],
        move_image: Callable[[Path, Path], bool],
        poll_interval: int = 2,
    ) -> None:
        self._comfyui_output = comfyui_output
        self.image_extensions = image_extensions
        self.load_state = load_state
        self.get_batch_folder = get_batch_folder
        self.move_image = move_image
        self.poll_interval = poll_interval
        self.running = False
        self.thread: threading.Thread | None = None
        self._seen_lock = threading.Lock()
        self.seen_files: set[str] = set()
        output_dir = self._comfyui_output()
        if output_dir.exists():
            self.seen_files = {
                p.name
                for p in output_dir.iterdir()
                if p.is_file() and p.suffix.lower() in self.image_extensions
            }

    def start(self) -> None:
        """Start the background polling thread if it is not already running."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._watch_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Signal the watcher to stop and wait for the current iteration."""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)

    def reset_seen(self) -> None:
        """Clear the seen-files set after a manual import."""
        with self._seen_lock:
            self.seen_files = set()

    def _watch_loop(self) -> None:
        while self.running:
            try:
                self._check_for_new_images()
            except Exception as exc:
                print(f"Watcher error: {exc}")
            time.sleep(self.poll_interval)

    def _check_for_new_images(self) -> None:
        state = self.load_state()
        active_batch = state.get("active_batch")
        output_dir = self._comfyui_output()

        if not active_batch or not output_dir.exists():
            return

        dest_inbox = self.get_batch_folder(active_batch, "inbox")
        if not dest_inbox.exists():
            return

        current_files = {
            f.name
            for f in output_dir.iterdir()
            if f.is_file() and f.suffix.lower() in self.image_extensions
        }
        with self._seen_lock:
            new_files = current_files - self.seen_files

        for filename in new_files:
            src = output_dir / filename
            if not src.exists():
                continue
            # Wait for file-size stability (file still being written).
            for _ in range(10):
                if not src.exists():
                    break
                size1 = src.stat().st_size
                time.sleep(0.1)
                if not src.exists():
                    break
                if src.stat().st_size == size1 and size1 > 0:
                    break
            if src.exists():
                dst = dest_inbox / filename
                if self.move_image(src, dst):
                    print(f"Auto-imported: {filename} -> {active_batch}/inbox")
                else:
                    print(f"Failed to move {filename}")

        with self._seen_lock:
            self.seen_files = (
                {
                    f.name
                    for f in output_dir.iterdir()
                    if f.is_file() and f.suffix.lower() in self.image_extensions
                }
                if output_dir.exists()
                else set()
            )

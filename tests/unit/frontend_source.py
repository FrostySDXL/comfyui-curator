from pathlib import Path


# IMPORTANT: order must match the classic script load order in templates/index.html.
JS_FILES = [
    Path("static/js/state.js"),
    Path("static/js/dom-utils.js"),
    Path("static/js/api.js"),
    Path("static/js/sidebar.js"),
    Path("static/js/batches.js"),
    Path("static/js/grid.js"),
    Path("static/js/favorites.js"),
    Path("static/js/publish.js"),
    Path("static/js/moves.js"),
    Path("static/js/lightbox.js"),
    Path("static/js/metadata.js"),
    Path("static/js/prompts.js"),
    Path("static/js/ai-state.js"),
    Path("static/js/ai-sidebar.js"),
    Path("static/js/ai-panel.js"),
    Path("static/js/ai-history.js"),
    Path("static/js/ai-job.js"),
    Path("static/js/ai-inspector.js"),
    Path("static/js/ai-overlays.js"),
    Path("static/js/ai.js"),
    Path("static/js/polling.js"),
    Path("static/js/modals.js"),
    Path("static/js/combobox.js"),
    Path("static/js/keyboard.js"),
    Path("static/js/events.js"),
    Path("static/js/bootstrap.js"),
    Path("static/js/app.js"),
]

CSS_FILES = [
    Path("static/css/base.css"),
    Path("static/css/sidebar.css"),
    Path("static/css/layout.css"),
    Path("static/css/grid.css"),
    Path("static/css/lightbox.css"),
    Path("static/css/modals.css"),
    Path("static/css/prompts.css"),
    Path("static/css/toast.css"),
    Path("static/css/ai.css"),
    Path("static/css/responsive.css"),
]


def read_frontend_js() -> str:
    existing = [path for path in JS_FILES if path.exists()]
    return "\n".join(path.read_text(encoding="utf-8") for path in existing)


def read_frontend_css() -> str:
    existing = [path for path in CSS_FILES if path.exists()]
    return "\n".join(path.read_text(encoding="utf-8") for path in existing)


def extract_function_body(source: str, signature: str) -> str:
    start = source.find(signature)
    if start == -1:
        raise AssertionError(f"Could not locate {signature}")
    brace_start = source.find("{", start)
    if brace_start == -1:
        raise AssertionError(f"Could not locate function body for {signature}")
    depth = 0
    in_string: str | None = None
    in_line_comment = False
    in_block_comment = False
    index = brace_start
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
            index += 1
            continue
        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == in_string:
                in_string = None
            index += 1
            continue

        if char == "/" and next_char == "/":
            in_line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            in_block_comment = True
            index += 2
            continue
        if char in {'"', "'", "`"}:
            in_string = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    raise AssertionError(f"Could not find end of function body for {signature}")

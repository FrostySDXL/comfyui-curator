import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.frontend_source import extract_function_body, read_frontend_css, read_frontend_js


def read_index_html() -> str:
    return Path("templates/index.html").read_text(encoding="utf-8")


def test_ai_sidebar_contains_contextual_image_inspector() -> None:
    html = read_index_html()
    css = read_frontend_css()

    assert 'id="ai-review-section"' in html
    assert 'class="ai-review-section"' in html
    assert 'id="ai-image-inspector"' in html
    assert 'class="ai-image-inspector ai-image-inspector-empty"' in html
    assert "AI Review" in html
    assert 'id="ai-panel-tab-inspect"' in html
    assert 'id="ai-panel-tab-score"' in html
    assert 'id="ai-panel-tab-runs"' in html
    assert ".ai-review-section" in css
    assert ".ai-image-inspector" in css
    assert ".ai-image-inspector-empty" in css


def test_ai_inspector_exposes_threshold_preview_apply_and_clear_controls() -> None:
    html = read_index_html()
    js = read_frontend_js()
    css = read_frontend_css()

    inspect_markup = html.split('id="ai-review-section"', 1)[1].split('id="ai-score-section"', 1)[0]
    for element_id in (
        "ai-threshold-preview",
        "ai-score-threshold",
        "ai-threshold-preview-status",
        "ai-threshold-apply",
        "ai-threshold-clear",
    ):
        assert f'id="{element_id}"' in inspect_markup
    assert 'type="number"' in inspect_markup
    assert 'aria-live="polite"' in inspect_markup
    assert "function aiRenderThresholdPreview(" in js
    assert "function aiApplyThresholdFilter()" in js
    assert "function aiClearThresholdFilter()" in js
    assert "function aiBuildThresholdPreview(" in js
    assert ".ai-threshold-preview" in css
    assert ".ai-threshold-actions" in css


def test_ai_threshold_preview_does_not_mutate_grid_until_explicit_apply() -> None:
    js = read_frontend_js()
    render = extract_function_body(js, "function aiRenderThresholdPreview(")
    apply_filter = extract_function_body(js, "function aiApplyThresholdFilter()")

    assert "updateGrid()" not in render
    assert "loadCurrentFolderImages" not in render
    assert "aiFilterMode = 'threshold'" in apply_filter
    assert "aiRefreshFilteredGrid()" in apply_filter
    assert "aiShowOverlays = true" in apply_filter
    assert "updateGrid()" not in apply_filter


def test_ai_threshold_preview_disables_apply_when_no_scored_results_exist() -> None:
    js = read_frontend_js()
    render = extract_function_body(js, "function aiRenderThresholdPreview(")
    apply_filter = extract_function_body(js, "function aiApplyThresholdFilter()")

    assert "No scored images" in render
    assert "applyButton.disabled" in render
    assert "preview.scored === 0" in apply_filter
    assert "return;" in apply_filter


def test_ai_run_failure_details_are_bounded_and_report_hidden_remainder() -> None:
    js = read_frontend_js()
    summary = extract_function_body(js, "function aiShowRunSummary(run)")

    assert "AI_FAILURE_DETAIL_LIMIT" in js
    assert "aiGetFailureDisplayData" in summary
    assert "more failures not shown" in summary


def test_ai_job_status_copy_distinguishes_partial_and_wholly_failed_runs() -> None:
    js = read_frontend_js()
    status = extract_function_body(js, "function aiGetJobStatusCopy(job)")

    assert "Completed with failures" in status
    assert "Failed" in status
    assert "scored/succeeded" in status
    show_status = extract_function_body(js, "function aiShowJobStatus(job)")
    assert "aiGetJobStatusCopy(job)" in show_status
    assert "stateEl.className = 'ai-job-state ' + job.status;" in show_status


def test_ai_render_and_diff_guard_after_await() -> None:
    js = read_frontend_js()
    render = extract_function_body(js, "async function aiRenderCurrentRunUi(")
    diff = extract_function_body(js, "async function aiShowRunDiff(")

    assert "await aiShowRunDiff(aiActiveRun, isCurrent)" in render
    assert "if (!isCurrent()) return false;" in render
    assert "isCurrent = () => true" in diff
    assert "if (!isCurrent()) return;" in diff


def test_ai_stale_run_lifecycle_node_harness_passes() -> None:
    result = subprocess.run(
        ["node", "tests/unit/ai_stale_run_lifecycle_test.js"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert json.loads(result.stdout) == {"passed": 1, "failed": 0}


def test_ai_threshold_preview_counts_failed_and_unknown_results() -> None:
    js = read_frontend_js()
    assert "atOrAbove" in js
    assert "below" in js
    assert "failed" in js
    assert "unscored" in js
    assert "normalized_score" in js
    assert "aiThresholdScopeKey" in js
    assert "aiRunDataRequestToken" in js


def test_ai_threshold_preview_node_behavior_harness_passes() -> None:
    result = subprocess.run(
        ["node", "tests/unit/ai_threshold_preview_test.js"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert json.loads(result.stdout) == {"passed": 23, "failed": 0}


def test_ai_run_summary_surfaces_partial_failure_names_and_reasons() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    summary = extract_function_body(js, "function aiShowRunSummary(run)")
    assert "error_message" in summary
    assert "failedResults" in summary
    assert "Scored" in summary and "Failed" in summary
    assert "ai-run-failure-details" in summary
    assert ".ai-run-failure-details" in css
    assert ".ai-run-failure-item" in css


def test_ai_run_loading_discards_stale_batch_or_run_responses() -> None:
    js = read_frontend_js()
    load_body = extract_function_body(js, "async function aiLoadRun(runId)")
    refresh_body = extract_function_body(js, "async function aiRefreshRunData(existingRuns = null)")

    assert "const requestToken = typeof aiRunDataRequestToken === 'undefined'" in load_body
    assert "requestStillCurrent()" in load_body
    assert "currentBatch !== requestedBatch" in load_body
    assert "const requestToken = typeof aiRunDataRequestToken === 'undefined'" in refresh_body
    assert "requestStillCurrent()" in refresh_body
    assert "currentBatch !== requestedBatch" in refresh_body


def test_ai_sidebar_tabs_expose_complete_semantics_and_keyboard_navigation() -> None:
    html = read_index_html()
    js = read_frontend_js()

    for tab, panel in (
        ("inspect", "ai-review-section"),
        ("score", "ai-score-section"),
        ("runs", "ai-history-section"),
    ):
        assert (
            f'id="ai-panel-tab-{tab}" data-ai-tab="{tab}" type="button" '
            f'role="tab" aria-controls="{panel}"'
        ) in html
        assert f'id="{panel}"' in html
        assert 'role="tabpanel"' in html.split(f'id="{panel}"', 1)[1].split(">", 1)[0]

    assert 'aria-selected="true" tabindex="0"' in html
    assert html.count('aria-selected="false" tabindex="-1"') == 2
    assert "tab.setAttribute('aria-selected', String(isActive));" in js
    assert "tab.tabIndex = isActive ? 0 : -1;" in js
    assert "function aiHandlePanelTabKeydown(event)" in js
    assert "['ArrowLeft', 'ArrowRight', 'Home', 'End']" in js


def test_ai_inspector_renders_score_details_without_api_calls() -> None:
    js = read_frontend_js()
    css = read_frontend_css()
    html = read_index_html()

    # Inspect run selector present and hidden initially
    assert 'id="ai-inspect-controls"' in html
    assert 'id="ai-inspect-run-select"' in html
    assert 'class="ai-history-controls ai-inspect-controls hidden"' in html

    assert "function aiSyncRunSelects()" in js
    assert "ai-inspect-run-select" in js
    assert "aiPopulateRunSelect('ai-inspect-run-select'" in js

    assert "let aiInspectedImageName = null;" in js
    assert "function aiSetInspectedImage(img, sourceOverride = null)" in js
    assert "function aiRenderImageInspector(img = null)" in js
    assert "function aiRenderSelectionInspector()" in js
    assert "if (selectedImages.size > 1)" in js
    assert "if (selectedImages.size === 0)" in js
    assert "function aiGetSingleSelectedImage()" in js
    assert "Common missing" in js
    assert "ai-selection-image-list" in js
    assert "toggleAiSelectionImageCard" in js
    assert "const result = aiGetImageScore(target.name);" in js
    assert "detailChip.className = `ai-inspector-detail ${matched ? 'matched' : 'missing'}`;" in js
    assert "detailChip.textContent = `${matched ? 'YES' : 'NO'} · ${element}`;" in js
    assert "No AI score for this image" in js
    assert ".ai-inspector-score" in css
    assert ".ai-inspector-detail.matched" in css
    assert ".ai-inspector-detail.missing" in css
    assert ".ai-selection-summary" in css
    assert ".ai-selection-image-card" in css
    assert ".ai-selection-image-card.expanded" in css


def test_grid_and_lightbox_update_ai_inspected_image() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "const displayImages = getCurrentDisplayImages();" in js
    assert (
        "if (typeof aiSetInspectedImage === 'function') aiSetInspectedImage(displayImages[index]);"
        in js
    )
    assert "if (typeof aiSetInspectedImage === 'function') aiSetInspectedImage(img);" in js
    assert (
        "thumb.classList.toggle('inspected', typeof aiInspectedImageKey !== 'undefined' && aiInspectedImageKey === getImageIdentityKey(img, source));"
        in js
    )
    assert ".thumb.inspected" in css
    assert ".thumb.inspected::before" not in css


def test_ai_run_changes_refresh_inspector_context() -> None:
    js = read_frontend_js()

    assert "aiRenderImageInspector();" in js
    assert "aiInspectedImageName = null;" in js
    assert "function aiGetInspectedImage()" in js


def test_ai_runs_tab_owns_run_history_visibility() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "historySection.classList.remove('hidden');" in js
    assert "aiSetPanelTab(aiActivePanelTab);" in js
    assert "section.dataset.aiPanelSection === aiActivePanelTab" in js
    assert "historySection.style.display = 'block';" not in js
    assert ".ai-run-brief" in css
    assert ".ai-run-kpis" in css
    assert ".ai-stat-card" not in css


def test_lightbox_has_visible_ai_inspector_opposite_metadata_panel() -> None:
    html = read_index_html()
    js = read_frontend_js()
    css = read_frontend_css()

    assert 'id="lightbox-ai-panel"' in html
    assert 'id="lightbox-ai-toggle-btn"' in html
    assert "function toggleLightboxAiPanel()" in js
    assert "function renderLightboxAiPanel()" in js
    assert "lightboxAiOpen" in js
    assert "case 'i': e.preventDefault(); toggleLightboxAiPanel(); break;" in js
    assert ".lightbox-ai-panel" in css
    assert "right: 20px;" in css
    assert ".lightbox-metadata-panel" in css
    assert "left: 20px;" in css


def test_ai_sidebar_removes_internal_whole_panel_collapse() -> None:
    html = read_index_html()
    js = read_frontend_js()

    assert 'id="ai-curate-toggle"' not in html
    assert "function toggleAiCuratePanel()" not in js
    assert "AI_PANEL_OPEN_KEY" not in js


def test_ai_job_status_uses_running_indicator_not_progress_bar() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "ai-progress-bar" not in js
    assert "ai-progress-fill" not in js
    assert "Scoring images" in js
    assert ".ai-status-dot" in css
    assert ".ai-progress-bar" not in css


def test_ai_quality_flags_preserve_empty_web_selection() -> None:
    """Unchecked optional AI elements must send [] instead of null.

    The backend keeps ``quality_flags=None`` as a compatibility signal for
    appending all default quality checks, so the web UI must send an explicit
    empty list when no optional checkboxes are selected.
    """
    js = read_frontend_js()

    assert "quality_flags: qualityFlags.length > 0 ? qualityFlags : null" not in js
    assert js.count("quality_flags: qualityFlags") >= 2


def test_ai_score_flow_is_guided_and_exposes_the_element_cap_before_submit() -> None:
    html = read_index_html()
    js = read_frontend_js()
    css = read_frontend_css()

    score_markup = html.split('id="ai-score-section"', 1)[1].split('id="ai-job-section"', 1)[0]
    for step, heading in (
        ("1", "Checks"),
        ("2", "Scope and model"),
        ("3", "Outcome"),
    ):
        assert f'<span class="ai-score-step-number">{step}</span>' in score_markup
        assert f">{heading}</h4>" in score_markup
    assert 'id="ai-element-cap-status"' in score_markup
    assert 'id="ai-score-summary"' in score_markup
    assert 'role="status" aria-live="polite"' in score_markup
    assert score_markup.index('id="ai-score-summary"') < score_markup.index('id="ai-submit-btn"')

    assert "const AI_ELEMENT_CAP = 12;" in js
    assert "function aiUpdateScoreSummary()" in js
    assert "manualElements.length + qualityFlags.length" in js
    assert "totalChecks > AI_ELEMENT_CAP" in js
    assert "Only the first ${AI_ELEMENT_CAP} checks will be scored." not in js
    assert "Up to 12 total checks will be scored." in score_markup
    assert ".ai-score-step" in css
    assert ".ai-score-summary" in css
    assert ".ai-element-cap-status.limit-exceeded" in css


def test_ai_submit_job_guards_over_cap_before_fetch() -> None:
    js = read_frontend_js()
    submit = extract_function_body(js, "async function aiSubmitJob()")

    assert "const totalChecks = elements.length + qualityFlags.length;" in submit
    assert "totalChecks > AI_ELEMENT_CAP" in submit
    assert "showToast" in submit
    assert submit.index("totalChecks > AI_ELEMENT_CAP") < submit.index("fetch(")


def test_ai_submit_job_node_cap_lifecycle_passes() -> None:
    """Run the AI cap behavior against the real ai-job.js source in Node."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node executable not found")
    result = subprocess.run(
        [node, "tests/unit/ai_job_cap_test.js"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_ai_score_checklist_updates_have_one_live_announcement_region() -> None:
    html = read_index_html()
    score_markup = html.split('id="ai-score-section"', 1)[1].split('id="ai-job-section"', 1)[0]
    cap_opening = score_markup.split('id="ai-element-cap-status"', 1)[1].split(">", 1)[0]
    summary_opening = score_markup.split('id="ai-score-summary"', 1)[1].split(">", 1)[0]

    assert score_markup.count('role="status"') == 1
    assert score_markup.count('aria-live="polite"') == 1
    assert 'role="status" aria-live="polite"' in cap_opening
    assert 'role="status"' not in summary_opening
    assert "aria-live=" not in summary_opening


def test_ai_score_form_resists_narrow_panel_overflow() -> None:
    css = read_frontend_css()

    assert ".ai-curate-body" in css
    assert "overflow-x: hidden;" in css
    assert ".ai-form-row" in css
    assert "flex-wrap: wrap;" in css
    assert "flex: 1 1 96px;" in css
    assert "min-width: 0;" in css
    assert "#ai-top-n" in css
    assert "#ai-model" in css


def test_ai_sidebar_renders_deliberate_context_and_job_states() -> None:
    html = read_index_html()
    js = read_frontend_js()

    assert 'id="ai-runs-state"' in html
    assert (
        'role="status" aria-live="polite"'
        in html.split('id="ai-runs-state"', 1)[1].split(">", 1)[0]
    )
    assert 'id="ai-job-section"' in html

    assert "const target = img || aiGetInspectedImage();" in js
    assert "function aiAppendBatchInspectorOverview(inspector)" in js
    assert "No scored run yet" in js
    assert "Latest run" in js
    assert "Loading runs" in js
    assert "No runs saved for this batch" in js
    assert "Run history could not be loaded" in js
    assert "Run history refresh failed" in js

    for status_copy in (
        "Waiting for the active run",
        "Scoring images",
        "Run saved",
        "Cancellation requested",
        "Run cancelled",
        "Run failed",
    ):
        assert status_copy in js
    assert "ai-progress-bar" not in js


def test_ai_job_live_region_excludes_interactive_cancel_control() -> None:
    html = read_index_html()
    job_markup = html.split('id="ai-job-section"', 1)[1].split('id="ai-history-section"', 1)[0]
    section_opening = job_markup.split(">", 1)[0]
    status_markup = job_markup.split('class="ai-job-status"', 1)[1].split("</div>", 1)[0]

    assert 'role="status"' not in section_opening
    assert 'aria-live="polite"' not in section_opening
    assert 'role="status" aria-live="polite"' in status_markup.split(">", 1)[0]
    assert 'id="ai-cancel-btn"' not in status_markup
    assert job_markup.index("</div>") < job_markup.index('id="ai-cancel-btn"')


def test_ai_job_polling_retries_transient_status_failures_without_new_interval() -> None:
    js = read_frontend_js()
    poll_body = extract_function_body(js, "async function aiPollJobStatus()")
    catch_body = poll_body.split("catch (error)", 1)[1]
    status_body = extract_function_body(js, "function aiShowJobStatus(job)")

    assert "aiShowJobStatus(job);" in poll_body
    assert "Status update failed. Retrying..." in catch_body
    assert "aiStopPolling();" not in catch_body
    assert "aiStartPolling();" not in catch_body
    assert "setInterval(" not in catch_body
    assert "job.status === 'completed'" in status_body
    assert "job.status === 'cancelled' || job.status === 'failed'" in status_body
    assert status_body.count("aiStopPolling();") == 2


def test_ai_job_busy_state_belongs_to_noninteractive_status_region() -> None:
    js = read_frontend_js()
    status_body = extract_function_body(js, "function aiShowJobStatus(job)")

    assert "document.querySelector('#ai-job-section .ai-job-status')" in status_body
    assert "setAttribute('aria-busy', String(isActive))" in status_body
    assert "section.setAttribute('aria-busy'" not in status_body


def test_ai_run_refresh_rejects_failed_lists_and_missing_run_details() -> None:
    js = read_frontend_js()
    refresh_body = extract_function_body(js, "async function aiRefreshRunData(existingRuns = null)")

    list_status_check = refresh_body.index("if (!resp.ok)")
    list_empty_fallback = refresh_body.index("data.runs || []")
    detail_fetch = refresh_body.index(
        "await Promise.all(runs.map(id => aiFetchRun(id, requestedBatch)))"
    )
    detail_check = refresh_body.index("runDetails.some(run => !run)")
    latest_selection = refresh_body.index("const latestId")

    assert list_status_check < list_empty_fallback
    assert detail_fetch < detail_check < latest_selection
    assert "throw new Error" in refresh_body[list_status_check:list_empty_fallback]
    assert "throw new Error" in refresh_body[detail_check:latest_selection]
    assert "Run history could not be loaded" in refresh_body
    assert "Run history refresh failed" in refresh_body
    assert "aiSetRunsState(" in refresh_body


def test_ai_run_refresh_failure_preserves_cached_run_and_reports_real_recovery() -> None:
    js = read_frontend_js()
    refresh_function = extract_function_body(
        js, "async function aiRefreshRunData(existingRuns = null)"
    )
    scenarios = []

    for active_run in (None, {"run_id": "cached-run"}):
        script = f"""
let currentBatch = 'batch';
let aiActiveRun = {json.dumps(active_run)};
const controls = {{
    hidden: false,
    classList: {{ add(name) {{ if (name === 'hidden') controls.hidden = true; }} }},
}};
const states = [];
const document = {{ querySelector() {{ return controls; }} }};
const fetch = async () => {{ throw new Error('offline'); }};
const ccApiPath = path => path;
const console = {{ warn() {{}} }};
function aiSetRunsState(message, kind = '') {{ states.push({{message, kind}}); }}
{refresh_function}
aiRefreshRunData().then(() => {{
    process.stdout.write(JSON.stringify({{
        activeRun: aiActiveRun,
        controlsHidden: controls.hidden,
        finalState: states.at(-1),
    }}));
}});
"""
        result = subprocess.run(
            ["node", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        scenarios.append(json.loads(result.stdout))

    unavailable, cached = scenarios
    assert unavailable["activeRun"] is None
    assert unavailable["controlsHidden"] is True
    assert "could not be loaded" in unavailable["finalState"]["message"]
    assert "Switch batches and return" in unavailable["finalState"]["message"]
    assert "reload the page" in unavailable["finalState"]["message"]

    assert cached["activeRun"] == {"run_id": "cached-run"}
    assert cached["controlsHidden"] is False
    assert "refresh failed" in cached["finalState"]["message"]
    assert "last loaded run remains available" in cached["finalState"]["message"]


def test_ai_run_detail_failure_preserves_cached_run_ids() -> None:
    js = read_frontend_js()
    refresh_function = extract_function_body(
        js, "async function aiRefreshRunData(existingRuns = null)"
    )
    script = f"""
let currentBatch = 'batch';
let aiRunIds = ['cached-run'];
let aiActiveRun = {{run_id: 'cached-run'}};
const states = [];
const fetch = async () => ({{
    ok: true,
    json: async () => ({{runs: ['new-run']}}),
}});
const aiFetchRun = async () => null;
const ccApiPath = path => path;
const console = {{ warn() {{}} }};
function aiSetRunsState(message, kind = '') {{ states.push({{message, kind}}); }}
{refresh_function}
aiRefreshRunData().then(() => {{
    process.stdout.write(JSON.stringify({{
        activeRun: aiActiveRun,
        runIds: aiRunIds,
        finalState: states.at(-1),
    }}));
}});
"""
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    state = json.loads(result.stdout)

    assert state["activeRun"] == {"run_id": "cached-run"}
    assert state["runIds"] == ["cached-run"]
    assert "refresh failed" in state["finalState"]["message"]
    assert "last loaded run remains available" in state["finalState"]["message"]


def test_ai_load_run_failure_restores_selector_sync() -> None:
    """On fetch failure, aiLoadRun must sync selectors back to active run."""
    js = read_frontend_js()
    load_body = extract_function_body(js, "async function aiLoadRun(runId)")

    # Find the failure branch
    assert "showToast('Failed to load run');" in load_body
    # After showing toast, must sync selectors before returning
    fail_idx = load_body.index("showToast('Failed to load run');")
    sync_idx = load_body.index("aiSyncRunSelects();", fail_idx)
    return_idx = load_body.index("return;", sync_idx)
    # The sync call must appear after toast and before return in the failure path
    assert fail_idx < sync_idx < return_idx

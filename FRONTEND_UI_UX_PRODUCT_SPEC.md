# Frontend UI/UX and Product Specification

**Status:** Proposed  
**Audience:** Maintainers, designers, and implementation agents  
**Scope:** Standalone Flask UI and native ComfyUI curator UI  
**Last Updated:** 2026-07-12

## 1. Purpose

This specification defines an evolutionary improvement program for ComfyUI Curator's frontend experience, product capabilities, accessibility, and client/server performance. It preserves the existing operator-oriented workflow while improving hierarchy, discoverability, responsiveness, and scalability.

The filesystem remains the operational source of truth. Manual curation remains authoritative, and AI scoring remains advisory.

## 2. Visual References

The preferred exploratory concepts are local, non-production references:

- `tmp/ui-concepts/01-review-workspace.html` — review-mode, toolbar, and contextual-inspector ideas
- `tmp/ui-concepts/02-lightbox-compare.html` — comparison and lightbox ideas
- `tmp/ui-concepts/03-prompt-publish-workbench.html` — preferred visual direction for Prompt History and publishing

These mockups communicate visual intent only. They do not define final markup, API contracts, or implementation architecture.

## 3. Executive Assessment

### 3.1 Existing strengths

- The image grid is correctly treated as the primary review surface.
- Review stages are understandable and consistently color-coded.
- Batch and AI sidebars can be resized or hidden.
- Selection, comparison, metadata, AI inspection, publishing, and Prompt History are comprehensive.
- The lightbox supports capable keyboard-first review.
- The dark visual language suits prolonged image-review sessions.
- Manual curation remains distinct from advisory AI scoring.

### 3.2 Primary problem

The interface has high feature density without enough hierarchy or progressive disclosure. Many controls are small, low-contrast, and continuously visible. The result is operationally capable but visually closer to an internal administration tool than a polished image-review workstation.

### 3.3 Design direction

Retain the three-region structure:

1. Batch and library navigation
2. Primary image workspace
3. Contextual inspection and AI tools

Do not replace the application with a fundamentally different shell. Improve the existing structure through stronger hierarchy, larger readable controls, contextual actions, progressive disclosure, and performance-aware rendering.

## 4. Product Principles

1. **The image is primary.** Navigation and controls must not unnecessarily reduce the review surface.
2. **Manual decisions are authoritative.** AI may explain, rank, filter, or recommend but must not obscure file operations.
3. **Frequent actions stay visible.** Infrequent actions move into contextual menus or secondary panels.
4. **State must be obvious.** Selection, active folder, filters, AI state, and pending operations must be recognizable without relying on color alone.
5. **Keyboard and pointer flows are peers.** Neither interaction model may be treated as an afterthought.
6. **Progressive disclosure beats permanent density.** Advanced controls should appear when relevant.
7. **Large libraries are normal.** Designs must account for hundreds of batches and hundreds or thousands of images.
8. **Standalone and native views remain behaviorally aligned.** Shared frontend contracts and template parity must be preserved.

## 5. Compatibility and Non-Goals

### 5.1 Compatibility requirements

- Preserve existing batch folder semantics and filesystem operations.
- Preserve current public API shapes unless a change is intentionally versioned and synchronized across both runtimes.
- Preserve existing keyboard shortcuts unless an explicit migration is approved.
- Preserve the existing review-stage meanings.
- Preserve `templates/index.html` and `templates/curator.html` parity requirements.
- Preserve shared URL-helper behavior for Flask and native ComfyUI modes.
- Preserve manual curation as the source of truth.

### 5.2 Non-goals

- Replacing the application with a general-purpose digital asset manager
- Making AI decisions authoritative
- Introducing a frontend framework solely for visual changes
- Implementing full grid virtualization before measurement demonstrates a need
- Expanding public publishing into a social-network client
- Redesigning the filesystem layout as part of frontend polish

## 6. Primary Experience Requirements

### UX-001: Explicit browse and select modes

The grid must expose two understandable interaction states.

**Browse mode**

- Clicking a thumbnail opens the lightbox.
- Selection affordances may remain subtle until hover or keyboard focus.
- The mode is optimized for one-image-at-a-time review.

**Select mode**

- Clicking a thumbnail toggles selection.
- Selection affordances remain visible.
- The bulk-action bar is present even when zero images are selected.
- Shift-click range selection and Ctrl/Cmd-click disjoint selection are supported and discoverable.

**Acceptance criteria**

- The active mode is visible near Select All.
- Switching modes does not clear the current selection without confirmation.
- Keyboard shortcuts continue to work in both modes.
- The current click behavior is never ambiguous.

### UX-002: Reduced toolbar density

The workspace toolbar must distinguish primary navigation from view configuration.

**Primary controls**

- Folder stages
- Current image count
- Browse/select mode or selection status

**Secondary View menu**

- Sort field and direction
- Grid density or fit mode
- Favorites-only filtering
- AI badges
- AI filtering
- Optional thumbnail overlays

Active view settings should remain visible as compact summaries, for example:

```text
Date ↓    Comfort    Favorites    AI: Scored
```

**Acceptance criteria**

- All existing view functions remain available.
- Opening both sidebars at 1280px does not make the primary toolbar unusable.
- Active hidden settings remain visible without reopening the menu.

### UX-003: Typography and contrast baseline

Recommended baseline:

- Normal interface text: 13–14px
- Secondary text: at least 12px
- Labels: 11–12px semibold
- 9–10px text: limited to nonessential badges
- Muted text: raised to a contrast level appropriate for its size and background

Introduce semantic CSS variables:

```css
--text-primary
--text-secondary
--text-muted
--text-disabled
--surface-0
--surface-1
--surface-2
--border-subtle
--accent-primary
--danger
--success
--warning
```

**Acceptance criteria**

- Normal and secondary text meet WCAG AA contrast targets.
- Disabled text remains readable where understanding the unavailable action matters.
- `color-scheme: dark` is declared.
- Existing reduced-motion support remains functional.

### UX-004: Discoverable thumbnail actions

- Selection controls remain visible in Select mode.
- Active favorite stars remain visible.
- Hover and keyboard focus reveal filename, dimensions, and batch/folder where relevant.
- A compact context menu exposes:
  - Open
  - Compare with…
  - Move to…
  - Favorite
  - Prepare public copy
  - Copy prompt
  - Reveal metadata
- Right-click support supplements rather than replaces keyboard and visible-button flows.

### UX-005: Context-aware AI sidebar

**No selection**

- Latest run summary
- Scored, failed, and unscored counts
- Current AI filter
- Last run age
- Score this folder action
- Model connection status

**One image selected**

- Prominent score
- Passed and missing elements
- Compact evidence or reason
- Previous-run delta
- Find similar scores
- Show missing-element peers
- Compare against the top-scored image

**Multiple images selected**

- Score distribution
- Common missing elements
- Best and worst selected images
- Filter selection by failures or criteria
- Keep only scored
- Deselect failures

The Inspect tab remains the default contextual surface. The Score tab becomes a guided task flow.

### UX-006: Guided AI scoring

Use a three-step workflow:

1. **What should be checked?**
   - Prompt-derived elements
   - Saved element preset
   - Manual elements
   - Quality checks
2. **What should be scored?**
   - Folder or selection
   - All images or selected images
   - Model
3. **What should happen afterward?**
   - Score only
   - Suggest top N
   - Move top N
   - Destination

Before submission, display a plain-language summary:

```text
Score 35 inbox images with vl-scorer
6 prompt elements + 3 quality checks
Results will be saved; files will not be moved
```

The 12-element backend cap must be visible before submission. Inputs exceeding the cap must not be silently truncated.

## 7. Main Workspace

### 7.1 Batch sidebar

Support scalable scanning and organization:

- Optional time grouping: Today, This week, Older
- Prefix/project grouping
- User-defined collections
- Pinned batches
- Recently opened batches
- Compact and comfortable row density
- Stronger selected-batch treatment
- Aligned folder counts or a compact stage distribution
- Tooltips for truncated names
- Row context menu:
  - Rename
  - Duplicate structure
  - Set import destination
  - Open folder
  - Archive
  - Delete with confirmation
- Collapsible Collections group for All Favorites and All Public

### 7.2 Batch search

Support:

- Fuzzy name matching
- Prompt, tag, and model search
- Filters for inbox content, AI history, finals, public copies, and recent changes
- Search tokens such as:

```text
ai:true inbox:>0 public:true
```

### 7.3 Import terminology

Prefer operator-facing language:

- “Auto-import” section → **Import destination**
- “Set as Auto-import” → **Use as Import Destination**

Explain the behavior inline:

```text
New ComfyUI outputs will be imported into:
[ batch-name ]
```

### 7.4 Folder navigation

- Convey the primary flow: Inbox → Shortlisted → Finals.
- Visually separate Rejects as an alternate destination.
- Identify Public as generated output rather than a normal review stage.
- Optionally show stage progress.
- Enlarge folder drop targets during drag.
- Show the dragged image count.
- Confirm only large or destructive moves.
- Do not rely on color alone to communicate stage.

### 7.5 Grid display modes

Support or evaluate:

- Compact
- Comfortable
- Large
- Fit width
- Original-aspect-ratio masonry
- Contact sheet
- Crop thumbnails / Fit entire image

Contact-sheet mode is intended for composition comparison at scale. Fit-entire-image mode prevents square crops from hiding important edge content.

### 7.6 Grid loading and errors

- Use visible but restrained loading animation.
- Announce “Loading N images…” where appropriate.
- Show retryable thumbnail error tiles.
- Show first-time thumbnail-generation progress.
- Preserve scroll position when possible.
- Avoid flashing an empty grid during refresh.

### 7.7 Optional overlays

Allow operator-selected overlays for:

- Sequence/index
- Seed
- Dimensions
- Favorite
- AI score
- Prompt group
- Duplicate indicator

## 8. Lightbox Review

### 8.1 Action hierarchy

Group controls by purpose.

**Navigation**

- Previous/next
- Previous/next scored

**View**

- Zoom
- Fit
- Actual size
- Metadata
- AI

**Decision**

- Shortlist
- Final
- Reject

**More**

- Prepare public copy
- Favorite
- Pin compare

Shortlist, Final, and Reject must be visually dominant.

### 8.2 Filmstrip

Add an optional, collapsible filmstrip that provides:

- Position context
- Direct navigation
- Selection state
- Score and favorite badges
- Quick access to similar images

The filmstrip should be hidden by default and use windowing or lazy loading when necessary.

### 8.3 Configurable move behavior

Support preferences for:

- Move and advance
- Move and remain
- Move and go to next unreviewed
- Move and go to next scored
- Move and remove from the current sequence

### 8.4 Focused feedback

After a move, display a brief centered confirmation with Undo near the operator’s focal area. Existing toast behavior may remain as a secondary notification.

### 8.5 Metadata enhancements

- Search within metadata
- Copy all metadata
- Copy workflow JSON
- Download workflow JSON
- Send prompt to AI Score
- Collapsible sections
- Sticky headings
- Metadata diff in compare mode
- Highlight changed fields

## 9. Compare Mode

### 9.1 Synchronized inspection

- Synchronized zoom toggle
- Synchronized pan toggle
- Fit both
- Actual size for both
- Blink comparison
- Difference overlay
- Split-slider comparison
- Optional pixel-difference heatmap

### 9.2 Comparison decisions

- Pick left
- Pick right
- Favorite either pane
- Reject loser and advance
- Swap panes
- Replace the active candidate from a filmstrip
- Compare metadata side by side
- Compare AI element results side by side

### 9.3 Tournament mode

Tournament mode should:

1. Accept a selected candidate set.
2. Present repeated pairwise comparisons.
3. Support left/right winner shortcuts.
4. Build a deterministic ranked result.
5. Allow moving the top N to Shortlisted or Finals.

## 10. Prompt History Workbench

The visual direction should follow `tmp/ui-concepts/03-prompt-publish-workbench.html`.

### 10.1 Layout

**Left rail**

- Scope
- Batch filter
- Search facets
- Sort and grouping controls
- Index status

**Main panel**

- Search
- Prompt results
- Result count and active filters

### 10.2 Prompt results

- Show a concise preview first.
- Visually separate positive and negative prompts.
- Use one primary Copy menu:
  - Copy positive
  - Copy negative
  - Copy pair
  - Copy as AI elements
- Make image references actionable:
  - Show in grid
  - Open first
  - Select all matching
- Support prompt similarity groups.
- Support prompt version/diff view.
- Show model, LoRAs, resolution, sampler, and date range.
- Support saved prompt collections.
- Support editing a reusable copy without changing image metadata.

### 10.3 Indexing

For multi-batch builds:

- Show batch-level progress.
- Show the current batch and image count.
- Allow cancellation.
- Report unreadable or skipped files.
- Prefer incremental indexing of changed images.

## 11. Help and Onboarding

Replace the single long reference view with:

- Search
- Getting Started tab
- Grid tab
- Lightbox tab
- AI tab
- Publishing tab
- Shortcuts tab
- `<kbd>` rendering for keys
- Platform-appropriate modifiers
- Contextual help near complex controls

First-launch onboarding should cover:

1. Create or select a batch.
2. Import images.
3. Review with grid or keyboard controls.

Empty states should include relevant actions rather than only explanatory text.

## 12. Publishing Workbench

### 12.1 Preview

- Live watermark preview
- Draggable watermark position
- Preview against dark and light image regions
- Contrast warning
- Resulting pixel dimensions
- Approximate output size

### 12.2 Presets

Initial preset examples:

- Instagram portrait
- Bluesky
- X/Twitter
- Web gallery
- Full-resolution archival export
- Watermarked preview
- Clean metadata-stripped copy

Each preset may define:

- Resize and crop policy
- Format
- Quality
- Metadata policy
- Watermark configuration
- Filename template
- Destination

### 12.3 Export queue

- Overall progress
- Per-image success or failure
- Retry failed
- Cancel remaining
- Open output folder
- Copy destination path

### 12.4 Operator-facing terminology

Use **Export destination** in the normal workflow instead of exposing `IMAGE_CURATOR_PUBLIC_EXPORTS`. Configuration terminology belongs in Settings or a technical tooltip.

## 13. Accessibility Requirements

### A11Y-001: Native controls

Prefer native buttons over role-based `div` or `span` controls for:

- Folder tabs
- Lightbox close and navigation
- Thumbnail selection
- Favorite controls

### A11Y-002: Tab semantics

AI tabs require:

- `role="tab"`
- `aria-selected`
- `aria-controls`
- Matching `role="tabpanel"`
- Arrow-key navigation

### A11Y-003: Grid semantics

Use either list/listitem or intentional grid/gridcell semantics. Each thumbnail requires an accessible name similar to:

```text
Image 4 of 35, filename, not selected, favorite, AI score 5 of 6
```

Keyboard users must be able to open, select, favorite, open the context menu, and perform range selection.

### A11Y-004: Focus

- Retain visible focus rings.
- Remove focus styles that depend only on subtle border-color changes.
- Add a skip-to-workspace link.
- Restore focus after modal close.
- Place focus intentionally after batch changes.
- Retain focus predictably after moving an image.

### A11Y-005: Target size

Important interactive targets should approach 40–44px, especially:

- Sort and density controls
- Folder tabs
- Batch rows
- Dropdown options
- Lightbox actions
- Favorite and selection controls

### A11Y-006: Color and motion

- Complete a formal contrast audit.
- Provide non-color state indicators.
- Preserve reduced-motion behavior.
- Declare dark color-scheme support.

## 14. Responsive Requirements

Design and verify at least these ranges:

- Desktop: above 1200px
- Compact desktop/tablet: 768–1200px
- Narrow/mobile: below 768px
- Very narrow: below 480px

At narrow widths:

- Sidebars become drawers.
- Header actions collapse into a menu.
- Workspace filters become a bottom sheet or equivalent compact surface.
- Selection actions scroll horizontally or open as a command sheet.
- Lightbox decision actions remain fixed and prominent.
- Metadata and AI panels become full-height sheets.
- Compare mode supports vertical stacking and pane switching.

## 15. Performance Requirements

### PERF-001: Viewport-aware thumbnails

Implement viewport-aware thumbnail loading:

- Fetch visible thumbnails first.
- Prefetch approximately one or two viewports ahead.
- Deprioritize or cancel work after rapid batch switches.
- Retain offscreen placeholders.

`loading="lazy"` may be used as an initial improvement, but `IntersectionObserver` is preferred where the explicit fetch-to-blob pipeline requires control.

### PERF-002: Blob-memory management

- Measure the explicit blob cache against native browser HTTP caching.
- Prefer LRU over FIFO if the blob cache remains.
- Consider a byte-based limit rather than only an item count.
- Revoke entries unlikely to be revisited.
- Evaluate direct cacheable thumbnail URLs.

### PERF-003: Progressive rendering

Use this order before full virtualization:

1. Lazy-load media.
2. Render large result sets in chunks.
3. Evaluate `content-visibility: auto` and intrinsic sizing.
4. Measure representative workloads.

Implement full virtualization only if measured batch sizes and render times justify its interaction complexity.

### PERF-004: Polling

1. Pause or slow polling when `document.visibilityState` is hidden.
2. Use adaptive intervals:
   - 5 seconds during active import or AI work
   - 15–30 seconds while idle
   - paused while hidden
3. Prevent overlapping poll cycles.
4. Add lightweight revision checks.
5. Support conditional requests with ETags or 304 responses.
6. Evaluate SSE for import, filesystem, AI job, and run-completion events.

### PERF-005: Filesystem summary caching

- Short-lived batch summary cache
- Per-batch revision or mtime cache
- Invalidation after application-controlled mutation
- Optional filesystem watcher invalidation
- Cached favorite and public counts

### PERF-006: Lightbox prefetch

- Prefetch the next image after current-image decode.
- Optionally prefetch the previous image.
- Prefetch the next scored image when scored navigation is active.
- Avoid prefetching when data-saving preferences indicate it should be disabled.

### PERF-007: AI payload separation

Separate:

- Run list and summary
- Run statistics
- Per-image scores
- Detailed per-image element evidence

Summary UI must not require loading every detailed result.

### PERF-008: Prompt History scale

- Server-side search and pagination
- Separate facet payloads
- Incremental indexing
- Cached normalized search text
- Optional Web Worker for expensive client filtering if server search is deferred

## 16. Product Feature Backlog

### FEATURE-001: Tags and ratings

- Arbitrary tags
- Color labels
- One-to-five-star ratings
- Needs-fix status
- Saved filters

### FEATURE-002: Smart collections

Examples:

- Favorites not published
- Finals created this week
- AI score below four
- Missing a named criterion
- Public copies from a model
- Images using a LoRA
- Unreviewed inbox images

### FEATURE-003: Review session tracking

- Reviewed/unreviewed state
- Session progress
- Last reviewed image
- Decisions per minute
- Resume review

### FEATURE-004: Duplicate and similarity detection

- Exact duplicates
- Near duplicates
- Composition variations
- Cross-batch duplicates
- Keep-best-from-group workflow

### FEATURE-005: Tournament ranking

Pairwise comparison that produces a ranked shortlist and supports moving the top N.

### FEATURE-006: Saved AI scoring presets

Save element checklist, quality checks, model, top N, source, and move policy. Initial examples:

- Anatomy review
- Character consistency
- Product-shot quality
- Comic panel review
- Posting readiness

### FEATURE-007: Notes and rejection reasons

- Why rejected
- What to regenerate
- What worked
- Edit needed
- Aggregate rejection-reason reporting

### FEATURE-008: Cross-batch search

Search filename, prompts, seed, model, LoRA, date, dimensions, favorites, tags, ratings, AI score, and folder.

### FEATURE-009: Regeneration bridge

- Copy workflow
- Open workflow in ComfyUI
- Queue variation
- Queue with a changed seed
- Queue with prompt edits
- Convert failed AI criteria into prompt suggestions

### FEATURE-010: Non-destructive export recipes

Persist resize, crop, format, watermark, metadata, and naming policies so public derivatives can be regenerated.

## 17. Delivery Roadmap

### Phase 1: Immediate polish

- Raise minimum text size and contrast.
- Add semantic CSS color tokens.
- Improve focus indicators.
- Add complete AI tab semantics.
- Replace role-based pseudo-buttons where practical.
- Add Ctrl/Cmd-click selection.
- Add explicit selection-mode indication.
- Simplify toolbar grouping.
- Improve the empty AI sidebar.
- Expose the 12-element cap.
- Add lightbox prefetch.
- Add thumbnail lazy loading.
- Pause polling in hidden tabs.

### Phase 2: Workflow quality

- Context menus
- Saved view settings
- Publishing presets and previews
- Prompt History split layout
- Actionable prompt image references
- Review progress
- Notes, tags, and ratings
- Configurable move-and-advance behavior
- Lightbox filmstrip
- Synchronized compare controls

### Phase 3: Scale

- API revisions and ETags
- Cached batch summaries
- Adaptive polling or SSE
- Chunked rendering and content visibility
- Server-side prompt search
- Split AI summary/detail payloads
- Incremental prompt indexing
- Measured virtualization decision

### Phase 4: Differentiated capabilities

- Similarity and duplicate groups
- Tournament ranking
- Smart collections
- Regeneration bridge
- Cross-batch metadata search
- Export recipes

## 18. Recommended Top Ten

1. Viewport-aware thumbnail loading
2. Higher text contrast and 12–14px typography
3. Explicit Browse/Select modes
4. Simplified toolbar with a View menu
5. Context-aware AI empty and selection states
6. Lightbox next-image prefetch
7. Tags, ratings, and review status
8. Publishing presets with live preview
9. Smart collections and cross-batch search
10. Similarity grouping and tournament comparison

## 19. Measurement Plan

Before and after relevant phases, measure:

- Time to first visible thumbnail
- Time until the first viewport is usable
- Thumbnail requests initiated on first render
- Browser memory at 100, 500, and 2,000 images
- Grid render and update duration
- Lightbox next-image latency
- `/api/batches` response time with representative libraries
- Poll request frequency and transferred bytes while active, idle, and hidden
- Prompt History load and search latency
- Keyboard-only completion of core review workflows
- Screen-reader completion of batch selection, image selection, lightbox review, and modal close

Representative test sets should include 100, 500, and 2,000 images and a library with at least 100 batches.

## 20. Verification Expectations

Each implemented phase must include:

- Targeted unit, component, or integration tests as appropriate
- Frontend source-invariant tests where behavior is source-scraped
- `python scripts/run_all.py --quick`
- Manual standalone-browser validation
- Manual native ComfyUI validation for shared surfaces
- Keyboard-only smoke testing
- Narrow-width smoke testing
- Updated Help content when controls or shortcuts change
- Template parity verification between `index.html` and `curator.html`

Performance work must include before/after measurements rather than relying on architectural assumptions.

## 21. Evidence and Limitations

This specification is based on:

- Direct inspection of 13 supplied screenshots
- Review of `README.md`, `CONTRIBUTING.md`, and `static/README.md`
- Review of `templates/index.html`
- Review of relevant CSS and JavaScript, including grid rendering and polling
- Read-only parallel source inspections for visual, workflow, and performance coverage

Not yet performed:

- Live browser interaction audit
- Browser performance profiling
- Screen-reader testing
- Narrow-viewport runtime testing
- Workload measurements using 100-, 500-, and 2,000-image batches

Performance architecture, especially virtualization and push updates, must be chosen after representative measurement.

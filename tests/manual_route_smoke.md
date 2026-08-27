# Route-mode manual smoke checklist

Use this checklist after a UI or route change. It records real browser evidence
that the in-process tests cannot provide; do not treat it as browser automation.

## Automated preflight

Run the focused route/template checks from the repository root:

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_comfyui_static_ui.py tests/component/test_batch_api.py -v
```

Expected evidence: all tests pass, including local asset existence, template
parity, standalone route status, native route registration, and dual-mode URL
helper checks. These tests use local files, Flask's test client, Node source checks,
and mocked ComfyUI modules; they do not start ComfyUI or a browser.

## Standalone Flask route

1. Start the app with isolated disposable batch and output roots (see
   `scripts/README.md`) and open `http://127.0.0.1:5000/`. Do not use a
   production library or output directory.
2. Confirm the page renders with the batch sidebar, workspace toolbar, grid,
   and inspector rather than a template or server error.
3. In browser developer tools, confirm the ordered `/static/css/*.css` and
   `/static/js/*.js` requests return successfully; there should be no asset 404s
   or JavaScript parse errors.
4. Use the shared read-only flow below; confirm requests remain on standalone
   `/api/*`, `/thumb/*`, and `/image/*` paths.

## Native ComfyUI route

1. Install this checkout as `ComfyUI/custom_nodes/comfyui-curator`, configure
   isolated disposable batch, output, and native system roots, restart ComfyUI,
   and confirm the Curator action-bar button appears. Do not use a production
   library or output directory.
2. Open `/curator` and confirm the same page shell renders without an error.
3. In developer tools, confirm ordered `/curator_static/css/*.css` and
   `/curator_static/js/*.js` requests return successfully; there should be no
   `/static/` asset requests, asset 404s, or JavaScript parse errors.
4. Confirm `GET /api/curator/health` returns JSON `{"ok":true}` and use the
   shared read-only flow below; confirm API requests use `/api/curator/*`,
   thumbnails use `/curator/thumb/*`, and originals use `/curator/image/*`.
5. Switch folders and reload the page once; confirm the native page remains
   usable and no duplicate route or asset errors appear in the ComfyUI log.
   After inbox → shortlisted → inbox settles, confirm Activity reports 0 active
   items and prior folder-load records remain terminal.

## Shared read-only flow

- Load the disposable batch, switch folders, open an image, navigate next/previous,
  and change folders; confirm metadata and the inspector follow the image and
  reset when the view changes.
- Open Library Search, run a no-results query, apply a matching query, then
  clear it; confirm the originating view is restored.
- Select two images, open comparison, advance/close it, and confirm focus and
  selection remain usable.
- Open Help and Activity. After inbox → shortlisted → inbox settles, Activity
  must show 0 active items and prior folder-load records must remain terminal.
- Keyboard/focus: with Help, Search, Settings, or New Batch open, press `/`,
  `Ctrl+K`, arrows, and review shortcuts; focus must remain inside the active
  overlay. `Escape` closes only the topmost overlay, while keyboard activation
  of its Close control still works. Verify `Tab` and
  `Shift+Tab` wrap between visible enabled controls. Open an image, verify the
  lightbox initially focuses Close and traps focus, then open Prepare Public,
  close it with Escape, and verify focus returns to the lightbox control; close
  the lightbox and verify focus returns to the original thumbnail/opener.
- Keep this core smoke read-only: do not save Settings, run AI scoring, import,
  move, or delete files. Record any popup/button click separately from direct
  `/curator` loading evidence; a click is not proof that a new tab opened.

Record the date, checkout revision, route (`/` or `/curator`), browser, and any
failed request or console error with the root task's real browser evidence.

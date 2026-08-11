# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FitToList-Python is a desktop photo editor for quickly cropping and resizing multiple images in a folder. It's a single-file Tkinter application (`photo_editor.py`) with no test suite, build step, or packaging config — just a script and a Pillow dependency.

## Running

```bash
pip install -r requirements.txt
python photo_editor.py
```

Requires a display (Tkinter GUI) — cannot be run/verified headlessly. There is no CLI mode, test suite, or linter configured in this repo.

## Architecture

Everything lives in `photo_editor.py` as a single `PhotoEditorApp(tk.Tk)` class. The structure to understand before making changes:

- **Two image buffers**: `self.original_image` (as loaded from disk, never mutated) and `self.current_image` (the working copy that crop/resize operations apply to). `reset_image()` restores `current_image` from `original_image`. Saving always writes `current_image`.
- **Canvas coordinate space vs. image coordinate space**: the canvas displays `current_image` scaled to fit and centered, tracked via `self.display_scale` and `self.display_offset`. All mouse events (selection drag/resize/move) operate in canvas pixel coordinates; `apply_crop()` is the place that converts a canvas-space selection box back into image-space pixel coordinates using `display_scale`/`display_offset` before calling `PIL.Image.crop`.
- **Selection state machine**: `self.selection_box` (canvas coords) plus `self._drag_mode` (`None`, `"new"`, `"move"`, or `"resize-{left,right,top,bottom}"`) drive the crop-selection UI. `_hit_test()` determines what a click landed on (a border within `SELECTION_BORDER_MARGIN` px, `"inside"`, or empty canvas) and `_on_drag_start` sets the mode accordingly; `_on_drag_move` dispatches to `_move_selection` / `_resize_selection` based on that mode. Any operation that changes `current_image` (crop, resize, reset, loading a new file) calls `clear_selection()` first.
- **Redraw flow**: `_redraw()` recomputes the fit-to-canvas scale/offset, rebuilds the `ImageTk.PhotoImage` (must stay referenced via `self.display_photo` or Tkinter garbage-collects it and the canvas goes blank), and calls `_redraw_selection()`. It's called after any edit, on canvas resize (`<Configure>`), and on image load.
- **File list pane**: lists image files (extensions in `IMAGE_EXTENSIONS`) in `self.current_folder`; selecting one loads it via `_load_image()`. Saving into the current folder refreshes this list.

## Conventions to preserve

- No new top-level dependencies beyond Pillow without good reason — keep this a minimal, single-file script.
- Image mutations happen only on `self.current_image`, never on `self.original_image`.
- Any function that replaces `current_image` should clear the selection, redraw, and set a status message via `self._set_message(...)` — follow the existing pattern in `apply_crop`/`reset_image`/`rotate_right`.
- There is no interactive resize control. The only resizing is the optional max-width/max-height cap (File > Max Save Size...), applied to a copy of `current_image` at save time in `_save_current` via `_planned_save_size()` — it only ever shrinks (never enlarges) and never mutates `current_image` itself.

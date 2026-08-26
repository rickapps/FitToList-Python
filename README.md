# FitToList

FitToList is a lightweight desktop tool for cropping and resizing a whole folder of photos in one sitting. It's built for the "batch prep" workflow: point it at a folder of source images and a destination folder, then work through the source images one at a time — drag out a crop, straighten a crooked shot, rotate/flip, and save. Each save writes a new file into the destination folder and automatically advances you to the next unprocessed source image, so you can move through a large shoot without touching a mouse menu between photos.

It's aimed at anyone who needs to prep multiple images the same way — for a marketplace listing, a catalog, a website gallery, or similar — rather than at general-purpose photo editing.

## Features

- **Folder-based batch workflow** — select a source folder and a processed (output) folder once; the file list shows every source image next to the processed versions already saved for it.
- **Interactive crop selection** — drag directly on the image to draw a crop box, then drag its edges/corners to resize or drag inside it to reposition, with live selection dimensions shown in the status bar.
- **Crop to Selection** — commit the current selection, or just double-click inside it to crop and save in one step (**Process & Save**).
- **Straighten** — draw a level line and drag either end (up to 30° in either direction) to trace a tilted feature like a horizon; double-click to level the image around it. Run it again if 30° isn't enough, and use Crop to Selection afterward to trim the corners it exposes — it never crops for you.
- **Rotate left/right and horizontal flip (Reverse Image)**.
- **Reset** — revert the current image back to exactly how it was loaded from disk, discarding all edits.
- **Non-destructive originals** — the original file on disk is never modified; edits apply to a working copy, and a new file is written to the processed folder on save.
- **Smart save-as-new-file naming** — saving a source image writes it as `name_00.ext`, `name_01.ext`, etc. in the processed folder, so repeated edits of the same source never collide.
- **Edit-in-place for already-processed images** — reopening a processed output (rather than the original source) and saving overwrites that file instead of creating another copy, with a confirmation prompt before overwriting unsaved changes.
- **Auto-advance** — after Process & Save on a source image, the app automatically loads the next unprocessed image in the folder.
- **Optional max save size** — set a maximum width/height (File > Max Save Size...) to automatically shrink oversized images on save while preserving aspect ratio; images are never enlarged, and this never alters what's shown on screen.
- **Unsaved-changes protection** — switching images or folders with pending edits prompts you to save, discard, or cancel.
- **Persisted settings** — the last-used source/processed folders and max save size are remembered between sessions.
- **Toolbar shortcuts** for the most common actions (select folders, open processed folder, rotate, crop, straighten, save), plus a full File/Actions/Help menu.

## Installing and running

**Requirements:**

- Python 3.9 or later
- [Pillow](https://python-pillow.org/) (the only third-party dependency)
- Tkinter, which ships with most standard Python installations. On Linux, if `python3-tk` isn't already installed, install it via your distro's package manager (e.g. `sudo apt install python3-tk` on Debian/Ubuntu, `sudo dnf install python3-tkinter` on Fedora).
- A display — this is a GUI application and cannot be run headlessly (e.g. over a plain SSH session without X11 forwarding).

**Setup:**

```bash
git clone https://github.com/rickapps/FitToList-Python.git
cd FitToList-Python
python -m venv venv
source venv/bin/activate    # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**Run:**

```bash
python photo_editor.py
```

On first launch, use **File > Select Folders...** to choose a source folder (where your original images live) and a processed folder (where edited copies will be written).

For the full walkthrough of every feature, see [`user_manual.html`](user_manual.html) or open it from inside the app via **Help > User Guide** (opens in your default browser).

## For developers

FitToList is intentionally a single-file script (`photo_editor.py`) with no build step, packaging config, or test suite — just the script plus its Pillow dependency and the standalone `user_manual.html` it opens for Help > User Guide. This keeps it easy to read top to bottom and easy to fork or modify for a slightly different workflow.

A few things worth knowing before making changes:

- **Everything lives in one class**, `PhotoEditorApp(tk.Tk)`. Helper dialogs (`FolderSelectionDialog`, `MaxSizeDialog`, `FolderTreeFrame`) and small utilities (icon drawing, tooltips, config load/save) sit above it as module-level functions/classes.
- **Two image buffers drive all editing**: `self.original_image` is loaded from disk and never mutated; `self.current_image` is the working copy that every edit (crop, rotate, flip, reset) applies to. Saving always writes `current_image`.
- **Two coordinate spaces**: mouse events on the canvas (drag to select/move/resize a crop box) are handled in *canvas* pixel coordinates, while the underlying image is manipulated in *image* pixel coordinates. `self.display_scale` and `self.display_offset` (recomputed in `_redraw()` on every resize/edit) convert between the two; `apply_crop()`/`_crop_to_selection()` is the main place that conversion happens.
- **A small state machine drives the crop selection UI** — `self.selection_box` plus `self._drag_mode` (`None`, `"new"`, `"move"`, or `"resize-{edge}"`). `_hit_test()` figures out what a click landed on, and `_on_drag_start`/`_on_drag_move` route to the right behavior.
- **Straighten is a separate, mutually-exclusive overlay mode** (`self.straighten_active`/`self.straighten_angle`) layered onto the same canvas event handlers — while it's active they route to `_straighten_hit_test`/`_update_straighten_angle` instead of the crop-selection logic. It never rotates `current_image` (or its live thumbnail) while dragging, only a guide line drawn over the untouched image; `apply_straighten()` performs the one actual `Image.rotate()` on commit.
- **The file tree** (`self.file_tree`) shows one node per source image with processed outputs nested underneath, matched purely by filename convention (`{root}_NN{ext}`) — there's no separate metadata file linking a processed image back to its source.
- **Help > User Guide** doesn't build any UI itself; it hands `user_manual.html` (resolved next to `photo_editor.py` via `__file__`, not the current working directory) off to the OS's default handler through `_open_with_default_app()`, the same helper `open_source_folder`/`open_processed_folder` use. Editing the manual means editing that HTML file directly, not Python strings.
- There's no automated test suite; since this is a Tkinter GUI app, changes should be verified by actually running `python photo_editor.py` and exercising the affected workflow (loading images, dragging a selection, cropping, rotating, saving, and reopening a processed file) by hand.

See `CLAUDE.md` in this repository for a more detailed architectural walkthrough, including the redraw flow and the two distinct save behaviors (new file vs. overwrite-in-place).

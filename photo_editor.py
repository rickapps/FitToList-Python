import ctypes
import json
import os
import re
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"}
SELECTION_BORDER_MARGIN = 6  # canvas px within which a border-hover/resize is detected
SELECTION_MIN_SIZE = 4       # minimum selection width/height in canvas px while resizing

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".fittolist")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(config):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f)
    except OSError:
        pass


class FolderTreeFrame(tk.Frame):
    """Expandable folder tree (children loaded lazily, on expand) that keeps
    `path_var` in sync with whichever folder is highlighted.

    Tk's native directory chooser resolves "OK" differently depending on the
    exact click sequence (a highlighted row vs. the directory currently
    browsed into), which can silently return a folder other than the one
    displayed. Driving everything off the highlighted tree node avoids that
    mismatch - `path_var` is always what's on screen.
    """

    def __init__(self, parent, initial_dir):
        super().__init__(parent)
        self._placeholder_iids = set()
        self.path_var = tk.StringVar()

        scrollbar = tk.Scrollbar(self, orient=tk.VERTICAL)
        self.tree = ttk.Treeview(self, show="tree", selectmode="browse", yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewOpen>>", self._on_open)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        if initial_dir and os.path.isdir(initial_dir):
            target_dir = os.path.abspath(initial_dir)
        else:
            target_dir = os.path.abspath(os.path.expanduser("~"))

        for root_path in self._list_roots():
            self._insert_node("", root_path, text=root_path)
        self._expand_to(target_dir)

    # ---------- tree population ----------
    @staticmethod
    def _list_roots():
        """Return the top-level nodes for the tree: drive letters on Windows,
        or the filesystem root everywhere else."""
        if os.name == "nt":
            # GetLogicalDrives() reports mounted drive letters without touching
            # removable media, so it won't trigger "insert disk" prompts.
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            return [f"{chr(ord('A') + i)}:\\" for i in range(26) if bitmask & (1 << i)]
        return [os.sep]

    @staticmethod
    def _list_subdirs(path):
        try:
            return sorted(
                f for f in os.listdir(path) if not f.startswith(".") and os.path.isdir(os.path.join(path, f))
            )
        except OSError:
            return []

    @classmethod
    def _has_subdirs(cls, path):
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    if not entry.name.startswith(".") and entry.is_dir(follow_symlinks=False):
                        return True
        except OSError:
            pass
        return False

    def _insert_node(self, parent_iid, path, text):
        self.tree.insert(parent_iid, tk.END, iid=path, text=text)
        if self._has_subdirs(path):
            placeholder = self.tree.insert(path, tk.END, text="")
            self._placeholder_iids.add(placeholder)

    def _populate_children(self, iid):
        children = self.tree.get_children(iid)
        if len(children) == 1 and children[0] in self._placeholder_iids:
            placeholder = children[0]
            self.tree.delete(placeholder)
            self._placeholder_iids.discard(placeholder)
            for name in self._list_subdirs(iid):
                self._insert_node(iid, os.path.join(iid, name), text=name)

    def _expand_to(self, target_path):
        ancestors = []
        path = target_path
        while True:
            ancestors.append(path)
            parent = os.path.dirname(path)
            if parent == path:
                break
            path = parent
        for path in reversed(ancestors):
            if not self.tree.exists(path):
                return
            self._populate_children(path)
            self.tree.item(path, open=True)
        self.tree.selection_set(target_path)
        self.tree.see(target_path)
        self.tree.focus(target_path)
        self.path_var.set(target_path)

    # ---------- event handlers ----------
    def _on_open(self, event):
        iid = self.tree.focus()
        if iid:
            self._populate_children(iid)

    def _on_select(self, event):
        selection = self.tree.selection()
        if selection and selection[0] not in self._placeholder_iids:
            self.path_var.set(selection[0])


class FolderSelectionDialog(tk.Toplevel):
    """Modal dialog for choosing both the source and target folders at once.

    Read-only boxes at the top always mirror whichever folder is highlighted
    in the active tab's tree, so what's on screen is always what Save uses -
    same guarantee `FolderTreeFrame` provides for a single folder.
    """

    def __init__(self, parent, initial_source, initial_target):
        super().__init__(parent)
        self.title("Select Folders")
        self.geometry("480x560")
        self.transient(parent)
        self.result = None

        display_frame = tk.Frame(self)
        display_frame.pack(fill=tk.X, padx=8, pady=(8, 4))
        display_frame.grid_columnconfigure(1, weight=1)

        tk.Label(display_frame, text="Source:").grid(row=0, column=0, sticky="w")
        tk.Label(display_frame, text="Target:").grid(row=1, column=0, sticky="w", pady=(4, 0))

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        source_tab = tk.Frame(notebook)
        target_tab = tk.Frame(notebook)
        notebook.add(source_tab, text="Source")
        notebook.add(target_tab, text="Target")

        self.source_tree = FolderTreeFrame(source_tab, initial_source)
        self.source_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.target_tree = FolderTreeFrame(target_tab, initial_target or initial_source)
        self.target_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        source_entry = tk.Entry(
            display_frame, textvariable=self.source_tree.path_var, state="readonly"
        )
        source_entry.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        target_entry = tk.Entry(
            display_frame, textvariable=self.target_tree.path_var, state="readonly"
        )
        target_entry.grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(4, 0))

        btn_frame = tk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=8, pady=8)
        tk.Button(btn_frame, text="Save", command=self._save).pack(side=tk.RIGHT, padx=(4, 0))
        tk.Button(btn_frame, text="Cancel", command=self._cancel).pack(side=tk.RIGHT)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()
        self.focus_set()

    def _save(self):
        source = self.source_tree.path_var.get()
        target = self.target_tree.path_var.get()
        if not source or not os.path.isdir(source):
            messagebox.showerror("Select Folders", "Please select a valid source folder.", parent=self)
            return
        if not target or not os.path.isdir(target):
            messagebox.showerror("Select Folders", "Please select a valid target folder.", parent=self)
            return
        if os.path.abspath(source) == os.path.abspath(target):
            messagebox.showerror(
                "Select Folders", "Source folder cannot be the same as the target folder.", parent=self
            )
            return
        self.result = (source, target)
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class MaxSizeDialog(tk.Toplevel):
    """Modal dialog for setting the max width/height applied to images on save."""

    def __init__(self, parent, enabled, max_width, max_height):
        super().__init__(parent)
        self.title("Max Save Size")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None

        self.enabled_var = tk.BooleanVar(value=enabled)
        self.width_var = tk.StringVar(value=str(max_width) if max_width else "")
        self.height_var = tk.StringVar(value=str(max_height) if max_height else "")

        frame = tk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        tk.Checkbutton(
            frame,
            text="Reduce images that exceed the maximum size when saving",
            variable=self.enabled_var,
            command=self._update_field_state,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        tk.Label(frame, text="Max width (px):").grid(row=1, column=0, sticky="w")
        self.width_entry = tk.Entry(frame, textvariable=self.width_var, width=10)
        self.width_entry.grid(row=1, column=1, sticky="w", padx=(6, 0))

        tk.Label(frame, text="Max height (px):").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.height_entry = tk.Entry(frame, textvariable=self.height_var, width=10)
        self.height_entry.grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(4, 0))

        self._update_field_state()

        btn_frame = tk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=12, pady=(0, 12))
        tk.Button(btn_frame, text="Save", command=self._save).pack(side=tk.RIGHT, padx=(4, 0))
        tk.Button(btn_frame, text="Cancel", command=self._cancel).pack(side=tk.RIGHT)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()
        self.focus_set()

    def _update_field_state(self):
        state = tk.NORMAL if self.enabled_var.get() else tk.DISABLED
        self.width_entry.config(state=state)
        self.height_entry.config(state=state)

    def _save(self):
        enabled = self.enabled_var.get()
        width_str = self.width_var.get().strip()
        height_str = self.height_var.get().strip()
        if enabled:
            if not width_str.isdigit() or not height_str.isdigit() or int(width_str) == 0 or int(height_str) == 0:
                messagebox.showerror(
                    "Max Save Size",
                    "Please enter positive whole numbers for max width and max height.",
                    parent=self,
                )
                return
        width = int(width_str) if width_str.isdigit() else None
        height = int(height_str) if height_str.isdigit() else None
        self.result = (enabled, width, height)
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class PhotoEditorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FitToList - Photo Crop & Resize")
        self.geometry("1000x700")
        self.minsize(600, 400)

        config = load_config()
        self.source_folder = config.get("source_folder") or os.getcwd()
        self.target_folder = config.get("target_folder")
        self.max_size_enabled = bool(config.get("max_size_enabled", False))
        self.max_width = config.get("max_width")
        self.max_height = config.get("max_height")
        self.image_path = None
        self.original_image = None   # PIL.Image as loaded from disk
        self.current_image = None    # PIL.Image after edits
        self.is_dirty = False        # True if current_image has unsaved edits
        self.display_photo = None    # ImageTk.PhotoImage, kept alive for the canvas
        self.display_scale = 1.0
        self.display_offset = (0, 0)
        self.selection_start = None
        self.selection_box = None    # (x0, y0, x1, y1) in canvas coordinates
        self._drag_mode = None       # "new" or "move"
        self._drag_offset = (0, 0)   # click point relative to selection's top-left, for "move"
        self._selection_size = (0, 0)  # (width, height) preserved while moving

        self._build_menu()
        self._build_layout()
        self._populate_file_list()

    # ---------- UI construction ----------
    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Select Folders...", command=self.select_folders)
        file_menu.add_command(label="Max Save Size...", command=self.edit_max_size)
        file_menu.add_command(label="Save", command=self.save)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        actions_menu = tk.Menu(menubar, tearoff=False)
        actions_menu.add_command(label="Crop to Selection", command=self.apply_crop)
        actions_menu.add_command(label="Rotate Right", command=self.rotate_right)
        actions_menu.add_command(label="Rotate Left", command=self.rotate_left)
        actions_menu.add_command(label="Reverse Image", command=self.reverse_image)
        actions_menu.add_separator()
        actions_menu.add_command(
            label="Process & Save", command=self.process_and_save, accelerator="Double-click in selection"
        )
        menubar.add_cascade(label="Actions", menu=actions_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="User Guide", command=self.show_user_guide)
        help_menu.add_command(label="About FitToList", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _build_layout(self):
        top_frame = tk.Frame(self)
        top_frame.pack(fill=tk.X, side=tk.TOP)
        self._build_folder_bar(top_frame)
        self._build_controls(top_frame)

        paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashrelief=tk.RAISED, sashwidth=6)
        paned.pack(fill=tk.BOTH, expand=True)

        left_frame = tk.Frame(paned, width=250)
        paned.add(left_frame, minsize=180)
        self._build_left_pane(left_frame)

        right_frame = tk.Frame(paned)
        paned.add(right_frame, minsize=400)
        self._build_right_pane(right_frame)

    def _build_left_pane(self, parent):
        list_container = tk.Frame(parent)
        list_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        scrollbar = tk.Scrollbar(list_container, orient=tk.VERTICAL)
        self.file_listbox = tk.Listbox(
            list_container, yscrollcommand=scrollbar.set, exportselection=False
        )
        scrollbar.config(command=self.file_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.file_listbox.bind("<<ListboxSelect>>", self.on_file_selected)

    def _build_folder_bar(self, parent):
        folder_bar = tk.Frame(parent)
        folder_bar.pack(fill=tk.X, padx=5, pady=5)
        folder_bar.grid_columnconfigure(1, weight=1)

        tk.Label(folder_bar, text="Source:").grid(row=0, column=0, sticky="w", padx=(0, 5))
        self.folder_label = tk.Label(folder_bar, text=self.source_folder, anchor="w", justify="left")
        self.folder_label.grid(row=0, column=1, sticky="ew")

        tk.Label(folder_bar, text="Target:").grid(row=1, column=0, sticky="w", padx=(0, 5))
        self.target_folder_label = tk.Label(
            folder_bar, text=self.target_folder or "Target folder not set", anchor="w", justify="left"
        )
        self.target_folder_label.grid(row=1, column=1, sticky="ew")

        folders_btn = tk.Button(folder_bar, text="Select Folders...", command=self.select_folders)
        folders_btn.grid(row=0, column=2, rowspan=2, padx=(10, 0), sticky="ns")

    def _build_controls(self, parent):
        controls = tk.Frame(parent)
        controls.pack(fill=tk.X, padx=5, pady=5)
        for col in range(4):
            controls.grid_columnconfigure(col, weight=1)

        tk.Button(controls, text="Crop to Selection", command=self.apply_crop).grid(
            row=0, column=0, padx=2, pady=2, sticky="ew"
        )
        tk.Button(controls, text="Reset", command=self.reset_image).grid(
            row=0, column=1, padx=2, pady=2, sticky="ew"
        )
        tk.Button(controls, text="Save", command=self.save).grid(
            row=0, column=2, columnspan=2, padx=2, pady=2, sticky="ew"
        )

    def _build_right_pane(self, parent):
        self.canvas = tk.Canvas(parent, background="#333333", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self.canvas.bind("<Motion>", self._on_hover)
        self.canvas.bind("<Double-Button-1>", self._on_canvas_double_click)

        status_bar = tk.Frame(parent)
        status_bar.pack(fill=tk.X, padx=5, pady=(0, 5))
        status_bar.columnconfigure(0, weight=1)

        self.status_message_var = tk.StringVar(value="")
        self.status_name_var = tk.StringVar(value="")
        self.status_selection_var = tk.StringVar(value="")
        self.status_output_var = tk.StringVar(value="")

        tk.Label(
            status_bar, textvariable=self.status_message_var, anchor="w", relief=tk.SUNKEN, padx=6, pady=2
        ).grid(row=0, column=0, sticky="ew")
        tk.Label(
            status_bar, textvariable=self.status_name_var, anchor="w", relief=tk.SUNKEN, width=44, padx=6, pady=2
        ).grid(row=0, column=1, sticky="ew")
        tk.Label(
            status_bar, textvariable=self.status_selection_var, anchor="w", relief=tk.SUNKEN, width=20, padx=6, pady=2
        ).grid(row=0, column=2, sticky="ew")
        tk.Label(
            status_bar, textvariable=self.status_output_var, anchor="w", relief=tk.SUNKEN, width=18, padx=6, pady=2
        ).grid(row=0, column=3, sticky="ew")

        self._status_message_base = "Select a photo from the list to begin."
        self._refresh_message()

    # ---------- Settings persistence ----------
    def _persist_config(self):
        save_config(
            {
                "source_folder": self.source_folder,
                "target_folder": self.target_folder,
                "max_size_enabled": self.max_size_enabled,
                "max_width": self.max_width,
                "max_height": self.max_height,
            }
        )

    # ---------- File listing ----------
    def _populate_file_list(self):
        self.file_listbox.delete(0, tk.END)
        try:
            names = sorted(
                f
                for f in os.listdir(self.source_folder)
                if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS
            )
        except OSError as exc:
            messagebox.showerror("Error", f"Could not read folder:\n{exc}")
            names = []
        for name in names:
            self.file_listbox.insert(tk.END, name)

    def select_folders(self):
        dialog = FolderSelectionDialog(self, self.source_folder, self.target_folder)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        new_source, new_target = dialog.result
        source_changed = os.path.abspath(new_source) != os.path.abspath(self.source_folder)
        if source_changed and not self._confirm_discard_changes():
            return
        self.source_folder = new_source
        self.target_folder = new_target
        self.folder_label.config(text=self.source_folder)
        self.target_folder_label.config(text=self.target_folder)
        if source_changed:
            self._populate_file_list()
            self._clear_image_state()
        self._persist_config()

    def edit_max_size(self):
        dialog = MaxSizeDialog(self, self.max_size_enabled, self.max_width, self.max_height)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        self.max_size_enabled, self.max_width, self.max_height = dialog.result
        self._persist_config()
        self._refresh_message()
        self._update_status()

    def on_file_selected(self, event):
        selection = self.file_listbox.curselection()
        if not selection:
            return
        filename = self.file_listbox.get(selection[0])
        path = os.path.join(self.source_folder, filename)
        if path == self.image_path:
            return
        if not self._confirm_discard_changes():
            self._restore_listbox_selection()
            return
        self._load_image(path)

    def _restore_listbox_selection(self):
        """Re-select the currently loaded image in the file list, undoing a selection
        click that was cancelled because of unsaved changes."""
        self.file_listbox.selection_clear(0, tk.END)
        if not self.image_path:
            return
        current_name = os.path.basename(self.image_path)
        names = self.file_listbox.get(0, tk.END)
        if current_name in names:
            index = names.index(current_name)
            self.file_listbox.selection_set(index)
            self.file_listbox.activate(index)
            self.file_listbox.see(index)

    def _has_unsaved_changes(self):
        return self.current_image is not None and (self.is_dirty or self.selection_box is not None)

    def _confirm_discard_changes(self):
        """If the loaded image has unsaved edits, ask the user how to proceed.
        Returns True if it's fine to continue (nothing to save, changes were saved,
        or the user chose to discard them), False if the caller should abort."""
        if not self._has_unsaved_changes():
            return True
        response = messagebox.askyesnocancel(
            "Unsaved Changes",
            f"{os.path.basename(self.image_path)} has unsaved changes. Save before continuing?",
        )
        if response is None:
            return False
        if response:
            if self.selection_box is not None and not self._crop_to_selection():
                return False
            return self._save_current(show_confirmation=False)
        return True

    # ---------- Image loading / display ----------
    def _load_image(self, path):
        try:
            image = Image.open(path)
            image.load()
        except Exception as exc:
            messagebox.showerror("Error", f"Could not open image:\n{exc}")
            return
        self.image_path = path
        self.original_image = image
        self.current_image = image.copy()
        self.is_dirty = False
        self.clear_selection()
        self._redraw()
        self._set_message("Drag on the image to select a crop area.")

    def _clear_image_state(self):
        self.image_path = None
        self.original_image = None
        self.current_image = None
        self.is_dirty = False
        self.clear_selection()
        self.canvas.delete("all")
        self._set_message("Select a photo from the list to begin.")
        self._update_status()

    def _redraw(self):
        self.canvas.delete("image")
        if self.current_image is None:
            return
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        if canvas_w <= 1 or canvas_h <= 1:
            return
        img_w, img_h = self.current_image.size
        scale = min(canvas_w / img_w, canvas_h / img_h)
        disp_w = max(1, int(img_w * scale))
        disp_h = max(1, int(img_h * scale))
        resized = self.current_image.resize((disp_w, disp_h), Image.LANCZOS)
        self.display_photo = ImageTk.PhotoImage(resized)
        offset_x = (canvas_w - disp_w) // 2
        offset_y = (canvas_h - disp_h) // 2
        self.display_scale = scale
        self.display_offset = (offset_x, offset_y)
        self.canvas.create_image(offset_x, offset_y, anchor="nw", image=self.display_photo, tags="image")
        self._redraw_selection()

    # ---------- Crop selection ----------
    def _redraw_selection(self):
        self.canvas.delete("selection")
        if self.selection_box:
            x0, y0, x1, y1 = self.selection_box
            self.canvas.create_rectangle(x0, y0, x1, y1, outline="red", width=2, tags="selection")
        self._update_status()

    def _selection_image_size(self):
        """Return (width, height) of selection_box in image pixels, or None if there's no selection."""
        if self.selection_box is None or self.current_image is None:
            return None
        x0, y0, x1, y1 = self.selection_box
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        off_x, off_y = self.display_offset
        scale = self.display_scale
        img_w, img_h = self.current_image.size
        crop_left = max(0, min(img_w, (left - off_x) / scale))
        crop_right = max(0, min(img_w, (right - off_x) / scale))
        crop_top = max(0, min(img_h, (top - off_y) / scale))
        crop_bottom = max(0, min(img_h, (bottom - off_y) / scale))
        return round(crop_right - crop_left), round(crop_bottom - crop_top)

    def _planned_save_size(self):
        """Return (width, height) the image would be saved at: the pending selection's
        crop size if one exists (Save now commits it), else current_image's size - with
        the max-size cap applied if it's enabled and would actually shrink the result.
        None if no image is loaded."""
        if self.current_image is None:
            return None
        width, height = self._selection_image_size() or self.current_image.size
        if self.max_size_enabled and self.max_width and self.max_height:
            scale = min(self.max_width / width, self.max_height / height, 1.0)
            if scale < 1.0:
                width = max(1, round(width * scale))
                height = max(1, round(height * scale))
        return width, height

    def _update_status(self):
        if self.current_image is None or self.image_path is None:
            self.status_name_var.set("")
            self.status_selection_var.set("")
            self.status_output_var.set("")
            return
        dirty_marker = " *" if self._has_unsaved_changes() else ""
        self.status_name_var.set(
            f"{os.path.basename(self.image_path)} ({self.current_image.width} x {self.current_image.height})"
            f"{dirty_marker}"
        )
        selection_size = self._selection_image_size()
        if selection_size:
            self.status_selection_var.set(f"Selection: {selection_size[0]} x {selection_size[1]}")
        else:
            self.status_selection_var.set("")
        save_width, save_height = self._planned_save_size()
        self.status_output_var.set(f"Save size: {save_width} x {save_height}")

    def _refresh_message(self):
        text = self._status_message_base
        if self.max_size_enabled and self.max_width and self.max_height:
            text = f"{text}  [Max save size: {self.max_width} x {self.max_height}]"
        self.status_message_var.set(text)

    def _set_message(self, text):
        self._status_message_base = text
        self._refresh_message()

    def clear_selection(self):
        self.selection_box = None
        self.selection_start = None
        self._drag_mode = None
        self.canvas.delete("selection")

    def _hit_test(self, x, y):
        """Return which part of the selection box (x, y) is over: one of
        "left"/"right"/"top"/"bottom" (near that border), "inside", or None."""
        if self.selection_box is None:
            return None
        x0, y0, x1, y1 = self.selection_box
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        margin = SELECTION_BORDER_MARGIN

        if abs(x - left) <= margin and top - margin <= y <= bottom + margin:
            return "left"
        if abs(x - right) <= margin and top - margin <= y <= bottom + margin:
            return "right"
        if abs(y - top) <= margin and left - margin <= x <= right + margin:
            return "top"
        if abs(y - bottom) <= margin and left - margin <= x <= right + margin:
            return "bottom"
        if left <= x <= right and top <= y <= bottom:
            return "inside"
        return None

    def _on_hover(self, event):
        if self._drag_mode is not None:
            return
        hit = self._hit_test(event.x, event.y)
        if hit in ("left", "right"):
            self.canvas.config(cursor="sb_h_double_arrow")
        elif hit in ("top", "bottom"):
            self.canvas.config(cursor="sb_v_double_arrow")
        else:
            self.canvas.config(cursor="")

    def _on_drag_start(self, event):
        if self.current_image is None:
            return
        hit = self._hit_test(event.x, event.y)
        if hit in ("left", "right", "top", "bottom"):
            x0, y0, x1, y1 = self.selection_box
            left, right = sorted((x0, x1))
            top, bottom = sorted((y0, y1))
            self.selection_box = (left, top, right, bottom)
            self._drag_mode = f"resize-{hit}"
            self.canvas.config(
                cursor="sb_h_double_arrow" if hit in ("left", "right") else "sb_v_double_arrow"
            )
        elif hit == "inside":
            x0, y0, x1, y1 = self.selection_box
            left, right = sorted((x0, x1))
            top, bottom = sorted((y0, y1))
            self._drag_mode = "move"
            self._drag_offset = (event.x - left, event.y - top)
            self._selection_size = (right - left, bottom - top)
            self.canvas.config(cursor="fleur")
        else:
            self._drag_mode = "new"
            self.selection_start = (event.x, event.y)
            self.selection_box = (event.x, event.y, event.x, event.y)
            self._redraw_selection()

    def _on_drag_move(self, event):
        if self._drag_mode == "move":
            self._move_selection(event.x, event.y)
        elif self._drag_mode and self._drag_mode.startswith("resize-"):
            edge = self._drag_mode.split("-", 1)[1]
            self._resize_selection(edge, event.x, event.y)
        elif self._drag_mode == "new":
            if self.selection_start is None:
                return
            x0, y0 = self.selection_start
            self.selection_box = (x0, y0, event.x, event.y)
            self._redraw_selection()

    def _move_selection(self, x, y):
        off_x, off_y = self.display_offset
        disp_w = self.current_image.width * self.display_scale
        disp_h = self.current_image.height * self.display_scale
        width, height = self._selection_size
        drag_x, drag_y = self._drag_offset

        new_left = x - drag_x
        new_top = y - drag_y
        new_left = max(off_x, min(new_left, off_x + disp_w - width))
        new_top = max(off_y, min(new_top, off_y + disp_h - height))

        self.selection_box = (new_left, new_top, new_left + width, new_top + height)
        self._redraw_selection()

    def _resize_selection(self, edge, x, y):
        off_x, off_y = self.display_offset
        disp_w = self.current_image.width * self.display_scale
        disp_h = self.current_image.height * self.display_scale
        min_x, min_y = off_x, off_y
        max_x, max_y = off_x + disp_w, off_y + disp_h
        min_size = SELECTION_MIN_SIZE
        left, top, right, bottom = self.selection_box

        if edge == "left":
            left = max(min_x, min(x, right - min_size))
        elif edge == "right":
            right = min(max_x, max(x, left + min_size))
        elif edge == "top":
            top = max(min_y, min(y, bottom - min_size))
        elif edge == "bottom":
            bottom = min(max_y, max(y, top + min_size))

        self.selection_box = (left, top, right, bottom)
        self._redraw_selection()

    def _on_drag_end(self, event):
        self.selection_start = None
        self._drag_mode = None
        self._on_hover(event)

    def _on_canvas_double_click(self, event):
        if self._hit_test(event.x, event.y) == "inside":
            self.process_and_save()

    def apply_crop(self):
        self._crop_to_selection()

    def _crop_to_selection(self):
        """Crop current_image to selection_box. Returns True if a crop was applied."""
        if self.current_image is None or self.selection_box is None:
            return False
        x0, y0, x1, y1 = self.selection_box
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        off_x, off_y = self.display_offset
        scale = self.display_scale
        img_w, img_h = self.current_image.size

        crop_left = max(0, min(img_w, (left - off_x) / scale))
        crop_right = max(0, min(img_w, (right - off_x) / scale))
        crop_top = max(0, min(img_h, (top - off_y) / scale))
        crop_bottom = max(0, min(img_h, (bottom - off_y) / scale))

        if crop_right - crop_left < 2 or crop_bottom - crop_top < 2:
            messagebox.showwarning("Crop", "Selection is too small to crop.")
            return False

        box = (int(crop_left), int(crop_top), int(crop_right), int(crop_bottom))
        self.current_image = self.current_image.crop(box)
        self.is_dirty = True
        self.clear_selection()
        self._redraw()
        self._set_message("Cropped.")
        return True

    # ---------- Rotate / Flip ----------
    def rotate_right(self):
        if self.current_image is None:
            return
        self.current_image = self.current_image.transpose(Image.ROTATE_270)
        self.is_dirty = True
        self.clear_selection()
        self._redraw()
        self._set_message("Rotated right.")

    def rotate_left(self):
        if self.current_image is None:
            return
        self.current_image = self.current_image.transpose(Image.ROTATE_90)
        self.is_dirty = True
        self.clear_selection()
        self._redraw()
        self._set_message("Rotated left.")

    def reverse_image(self):
        if self.current_image is None:
            return
        self.current_image = self.current_image.transpose(Image.FLIP_LEFT_RIGHT)
        self.is_dirty = True
        self.clear_selection()
        self._redraw()
        self._set_message("Reversed.")

    # ---------- Reset / Save ----------
    def reset_image(self):
        if self.original_image is None:
            return
        self.current_image = self.original_image.copy()
        self.is_dirty = False
        self.clear_selection()
        self._redraw()
        self._set_message("Reset to original.")

    def save(self):
        if self.selection_box is not None and not self._crop_to_selection():
            return
        self._save_current(show_confirmation=True)

    def _next_suffix(self, root, ext):
        """Return the next _NN suffix for root/ext in target_folder (max existing + 1, else 0)."""
        pattern = re.compile(rf"^{re.escape(root)}_(\d+){re.escape(ext)}$", re.IGNORECASE)
        max_suffix = -1
        for name in os.listdir(self.target_folder):
            match = pattern.match(name)
            if match:
                max_suffix = max(max_suffix, int(match.group(1)))
        return max_suffix + 1

    def _save_current(self, show_confirmation):
        """Write current_image to the target folder. Returns True on success."""
        if self.current_image is None:
            messagebox.showinfo("Save", "No image loaded to save.")
            return False
        if not self.target_folder:
            messagebox.showwarning("Save", "Please set a target folder first.")
            return False
        filename = os.path.basename(self.image_path)
        root, ext = os.path.splitext(filename)
        try:
            suffix = self._next_suffix(root, ext)
            path = os.path.join(self.target_folder, f"{root}_{suffix:02d}{ext}")
            image_to_save = self.current_image
            if os.path.splitext(path)[1].lower() in (".jpg", ".jpeg") and image_to_save.mode in ("RGBA", "P"):
                image_to_save = image_to_save.convert("RGB")
            save_size = self._planned_save_size()
            if save_size != image_to_save.size:
                image_to_save = image_to_save.resize(save_size, Image.LANCZOS)
            image_to_save.save(path)
        except Exception as exc:
            messagebox.showerror("Error", f"Could not save image:\n{exc}")
            return False
        self.is_dirty = False
        self._update_status()
        if show_confirmation:
            messagebox.showinfo("Save", f"Saved to {path}")
        else:
            self._set_message(f"Saved to {path}")
        return True

    # ---------- Process & Save ----------
    def process_and_save(self):
        if self.current_image is None:
            return
        if self.selection_box is not None and not self._crop_to_selection():
            return
        if not self._save_current(show_confirmation=False):
            return
        self._select_next_file()

    def _select_next_file(self):
        size = self.file_listbox.size()
        if size == 0:
            return
        names = self.file_listbox.get(0, tk.END)
        current_name = os.path.basename(self.image_path) if self.image_path else None
        try:
            next_index = names.index(current_name) + 1
        except ValueError:
            next_index = 0
        if next_index >= size:
            return
        self.file_listbox.selection_clear(0, tk.END)
        self.file_listbox.selection_set(next_index)
        self.file_listbox.activate(next_index)
        self.file_listbox.see(next_index)
        path = os.path.join(self.source_folder, names[next_index])
        self._load_image(path)

    # ---------- Help ----------
    def show_user_guide(self):
        messagebox.showinfo(
            "User Guide",
            "1. File > Select Folders... to choose a source and target folder.\n"
            "2. Pick an image from the file list to load it.\n"
            "3. Drag on the image to select a crop area, then Actions > Crop to Selection.\n"
            "4. Use Actions > Rotate Left/Right or Reverse Image to change orientation.\n"
            "5. File > Save (or Actions > Process & Save) to write the result to the target folder.\n"
            "6. Reset restores the image to how it was loaded.\n"
            "7. File > Max Save Size... sets a maximum width/height applied to images when "
            "they're saved, shrinking them (preserving aspect ratio) if they're larger. Images "
            "are never enlarged. This does not change the image on screen, only the saved file. "
            "When active, it's noted in the status bar.",
        )

    def show_about(self):
        messagebox.showinfo(
            "About FitToList",
            "FitToList\n\nA desktop tool for quickly cropping and resizing photos in a folder.",
        )


def main():
    app = PhotoEditorApp()
    app.mainloop()


if __name__ == "__main__":
    main()

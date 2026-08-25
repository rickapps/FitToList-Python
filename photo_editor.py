import ctypes
import json
import math
import os
import re
import subprocess
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"}
SELECTION_BORDER_MARGIN = 6  # canvas px within which a border-hover/resize is detected
SELECTION_MIN_SIZE = 4       # minimum selection width/height in canvas px while resizing

TOOLBAR_ICON_SIZE = 28   # px, source size for generated toolbar icons
TOOLBAR_BUTTON_SIZE = 36  # px, fixed width/height applied to every toolbar button

LINK_COLOR = "#1a56db"
LINK_HOVER_COLOR = "#0f3fa8"

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


def _point_on_circle(cx, cy, r, angle_deg):
    rad = math.radians(angle_deg)
    return (cx + r * math.cos(rad), cy + r * math.sin(rad))


def _draw_folder_icon(draw, size, fg):
    pad = size * 0.11
    tab_w = size * 0.4
    tab_h = size * 0.11
    body_top = pad + tab_h + size * 0.04
    draw.rectangle([pad, pad, pad + tab_w, body_top], outline=fg, width=2)
    draw.rectangle([pad, body_top, size - pad, size - pad], outline=fg, width=2)


def _draw_rotate_icon(draw, size, fg, clockwise):
    cx = cy = size / 2
    r = size * 0.32
    if clockwise:
        start, end = 40, 300
        tip_angle, dir_angle = end, end + 90
    else:
        start, end = 240, 500
        tip_angle, dir_angle = start, start + 90
    draw.arc([cx - r, cy - r, cx + r, cy + r], start=start, end=end, fill=fg, width=3)
    tip = _point_on_circle(cx, cy, r, tip_angle)
    back_left = _point_on_circle(tip[0], tip[1], size * 0.21, dir_angle + 150)
    back_right = _point_on_circle(tip[0], tip[1], size * 0.21, dir_angle - 150)
    draw.polygon([tip, back_left, back_right], fill=fg)


def _draw_crop_icon(draw, size, fg):
    pad = size * 0.14
    arm = size * 0.35
    draw.line([(pad, pad + arm), (pad, pad), (pad + arm, pad)], fill=fg, width=3)
    draw.line(
        [(size - pad, size - pad - arm), (size - pad, size - pad), (size - pad - arm, size - pad)],
        fill=fg,
        width=3,
    )


def _draw_save_icon(draw, size, fg):
    pad = size * 0.11
    draw.rectangle([pad, pad, size - pad, size - pad], outline=fg, width=2)
    draw.rectangle([pad + 4, pad, size - pad - 4, pad + 6], fill=fg)
    draw.rectangle([pad + 5, size - pad - 9, size - pad - 5, size - pad - 1], outline=fg, width=2)


def _draw_open_folder_icon(draw, size, fg):
    _draw_folder_icon(draw, size, fg)
    # arrow breaking out of the folder toward the upper right, signaling "open externally"
    tail = (size * 0.42, size * 0.68)
    tip = (size * 0.86, size * 0.24)
    draw.line([tail, tip], fill=fg, width=3)
    dir_angle = math.degrees(math.atan2(tip[1] - tail[1], tip[0] - tail[0]))
    back_left = _point_on_circle(tip[0], tip[1], size * 0.2, dir_angle + 150)
    back_right = _point_on_circle(tip[0], tip[1], size * 0.2, dir_angle - 150)
    draw.polygon([tip, back_left, back_right], fill=fg)


def build_toolbar_icons(size=TOOLBAR_ICON_SIZE, fg="#333333"):
    """Render the toolbar button icons as ImageTk.PhotoImage objects. Must be
    called after a Tk root window exists. Callers must keep the returned dict
    referenced for the app's lifetime or Tkinter will garbage-collect the images."""
    specs = {
        "select_folders": lambda d: _draw_folder_icon(d, size, fg),
        "open_processed_folder": lambda d: _draw_open_folder_icon(d, size, fg),
        "rotate_right": lambda d: _draw_rotate_icon(d, size, fg, clockwise=True),
        "rotate_left": lambda d: _draw_rotate_icon(d, size, fg, clockwise=False),
        "crop": lambda d: _draw_crop_icon(d, size, fg),
        "save": lambda d: _draw_save_icon(d, size, fg),
    }
    icons = {}
    for name, draw_fn in specs.items():
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw_fn(ImageDraw.Draw(img))
        icons[name] = ImageTk.PhotoImage(img)
    return icons


class ToolTip:
    """Minimal hover tooltip: shows `text` in a borderless popup near the widget
    after a short delay, following the standard Tkinter recipe (no extra dependency)."""

    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after_id = None
        self._tip_window = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _schedule(self, event=None):
        self._cancel_pending()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel_pending(self):
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self):
        if self._tip_window is not None:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=self.text, background="#ffffe0", relief=tk.SOLID, borderwidth=1, padx=6, pady=2
        ).pack()

    def _hide(self, event=None):
        self._cancel_pending()
        if self._tip_window is not None:
            self._tip_window.destroy()
            self._tip_window = None


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
        tk.Label(display_frame, text="Processed:").grid(row=1, column=0, sticky="w", pady=(4, 0))

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        source_tab = tk.Frame(notebook)
        target_tab = tk.Frame(notebook)
        notebook.add(source_tab, text="Source")
        notebook.add(target_tab, text="Processed")

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
            messagebox.showerror("Select Folders", "Please select a valid processed folder.", parent=self)
            return
        if os.path.abspath(source) == os.path.abspath(target):
            messagebox.showerror(
                "Select Folders", "Source folder cannot be the same as the processed folder.", parent=self
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

        self.icons = build_toolbar_icons()  # kept referenced here so Tkinter doesn't GC them

        self._build_menu()
        self._build_layout()
        self._tree_paths = {}  # tree iid -> file path, for both source and processed nodes
        self._populate_tree()

    # ---------- UI construction ----------
    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Select Folders...", command=self.select_folders)
        file_menu.add_command(label="Open Source Folder", command=self.open_source_folder)
        file_menu.add_command(label="Open Processed Folder", command=self.open_processed_folder)
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
        actions_menu.add_command(label="Reset", command=self.reset_image)
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
        self.file_tree = ttk.Treeview(
            list_container, show="tree", selectmode="browse", yscrollcommand=scrollbar.set
        )
        scrollbar.config(command=self.file_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.file_tree.bind("<<TreeviewSelect>>", self.on_tree_select)

    def _build_folder_bar(self, parent):
        folder_bar = tk.Frame(parent)
        folder_bar.pack(fill=tk.X, padx=5, pady=5)

        fields_group = tk.LabelFrame(folder_bar)
        fields_group.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        fields_group.grid_columnconfigure(1, weight=1)

        tk.Label(fields_group, text="Source:").grid(row=0, column=0, sticky="w", padx=(4, 5), pady=(4, 0))
        self.folder_label = tk.Label(fields_group, text=self.source_folder, anchor="w", justify="left")
        self.folder_label.grid(row=0, column=1, sticky="ew", padx=(0, 4), pady=(4, 0))

        tk.Label(fields_group, text="Processed:").grid(row=1, column=0, sticky="w", padx=(4, 5))
        self.target_folder_label = tk.Label(
            fields_group, text=self.target_folder or "Processed folder not set", anchor="w", justify="left"
        )
        self.target_folder_label.grid(row=1, column=1, sticky="ew", padx=(0, 4))

        self.max_size_status_var = tk.StringVar(value="")
        max_size_link = tk.Label(
            fields_group,
            textvariable=self.max_size_status_var,
            anchor="w",
            justify="left",
            fg=LINK_COLOR,
            cursor="hand2",
        )
        self._max_size_link_font = tkfont.nametofont(max_size_link.cget("font")).copy()
        self._max_size_link_font.configure(underline=True)
        max_size_link.configure(font=self._max_size_link_font)
        max_size_link.grid(row=2, column=0, columnspan=2, sticky="w", padx=4, pady=(4, 4))
        max_size_link.bind("<Button-1>", lambda e: self.edit_max_size())
        max_size_link.bind("<Enter>", lambda e: max_size_link.configure(fg=LINK_HOVER_COLOR))
        max_size_link.bind("<Leave>", lambda e: max_size_link.configure(fg=LINK_COLOR))
        ToolTip(max_size_link, "Click to change the max save size")
        self._refresh_max_size_status()

        button_bar = tk.Frame(folder_bar)
        button_bar.pack(side=tk.LEFT, anchor="center")

        toolbar_buttons = [
            ("select_folders", self.select_folders, "Select Folders"),
            ("open_processed_folder", self.open_processed_folder, "Open Processed Folder"),
            ("rotate_right", self.rotate_right, "Rotate Right"),
            ("rotate_left", self.rotate_left, "Rotate Left"),
            ("crop", self.apply_crop, "Crop to Selection"),
            ("save", self.save, "Save"),
        ]
        for icon_name, command, tooltip_text in toolbar_buttons:
            btn = tk.Button(
                button_bar,
                image=self.icons[icon_name],
                command=command,
                width=TOOLBAR_BUTTON_SIZE,
                height=TOOLBAR_BUTTON_SIZE,
            )
            btn.pack(side=tk.LEFT, padx=2)
            ToolTip(btn, tooltip_text)

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
        self.status_output_var = tk.StringVar(value="")

        tk.Label(
            status_bar, textvariable=self.status_message_var, anchor="w", relief=tk.SUNKEN, padx=6, pady=2
        ).grid(row=0, column=0, sticky="ew")
        tk.Label(
            status_bar, textvariable=self.status_name_var, anchor="w", relief=tk.SUNKEN, width=44, padx=6, pady=2
        ).grid(row=0, column=1, sticky="ew")
        tk.Label(
            status_bar, textvariable=self.status_output_var, anchor="w", relief=tk.SUNKEN, width=18, padx=6, pady=2
        ).grid(row=0, column=2, sticky="ew")

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
    def _list_processed_names(self):
        if self.target_folder and os.path.isdir(self.target_folder):
            try:
                return os.listdir(self.target_folder)
            except OSError:
                return []
        return []

    @staticmethod
    def _matching_processed_names(source_name, processed_names):
        """Processed filenames matching source_name's `{root}_NN{ext}` naming
        (the same pattern `_next_suffix` scans for), sorted by suffix."""
        root, ext = os.path.splitext(source_name)
        pattern = re.compile(rf"^{re.escape(root)}_(\d+){re.escape(ext)}$", re.IGNORECASE)
        matches = []
        for pname in processed_names:
            match = pattern.match(pname)
            if match:
                matches.append((int(match.group(1)), pname))
        return [pname for _, pname in sorted(matches)]

    def _populate_tree(self):
        """Rebuild the whole file tree: one top-level node per source image, with a
        child node for each processed output already saved for it. Used on startup
        and when the source/target folders change; a save only touches one node, so
        it goes through _refresh_processed_children instead."""
        self.file_tree.delete(*self.file_tree.get_children(""))
        self._tree_paths = {}
        try:
            source_names = sorted(
                f
                for f in os.listdir(self.source_folder)
                if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS
            )
        except OSError as exc:
            messagebox.showerror("Error", f"Could not read folder:\n{exc}")
            source_names = []

        processed_names = self._list_processed_names()

        for index, name in enumerate(source_names):
            source_iid = f"src{index}"
            self.file_tree.insert("", tk.END, iid=source_iid, text=name, open=False)
            self._tree_paths[source_iid] = os.path.join(self.source_folder, name)

            for pname in self._matching_processed_names(name, processed_names):
                child_iid = f"{source_iid}/{pname}"
                self.file_tree.insert(source_iid, tk.END, iid=child_iid, text=pname)
                self._tree_paths[child_iid] = os.path.join(self.target_folder, pname)

        self._select_tree_node_for_current_image()
        if not self.image_path:
            self._select_first_unprocessed_image()

    def _source_iid_for_path(self, path):
        for iid in self.file_tree.get_children(""):
            if self._tree_paths.get(iid) == path:
                return iid
        return None

    def _refresh_processed_children(self, source_path):
        """Rescan the target folder for processed outputs of a single source image
        and rebuild just that node's children, leaving the rest of the tree (and
        its selection) untouched. Does nothing if source_path isn't a top-level
        (source) node - e.g. it's a processed file itself, which the newly saved
        output won't be matched against anyway (see CLAUDE.md)."""
        source_iid = self._source_iid_for_path(source_path)
        if source_iid is None:
            return
        for child_iid in self.file_tree.get_children(source_iid):
            del self._tree_paths[child_iid]
        self.file_tree.delete(*self.file_tree.get_children(source_iid))

        name = os.path.basename(source_path)
        processed_names = self._list_processed_names()
        matches = self._matching_processed_names(name, processed_names)
        for pname in matches:
            child_iid = f"{source_iid}/{pname}"
            self.file_tree.insert(source_iid, tk.END, iid=child_iid, text=pname)
            self._tree_paths[child_iid] = os.path.join(self.target_folder, pname)
        if matches:
            self.file_tree.item(source_iid, open=True)

    def select_folders(self):
        dialog = FolderSelectionDialog(self, self.source_folder, self.target_folder)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        new_source, new_target = dialog.result
        source_changed = os.path.abspath(new_source) != os.path.abspath(self.source_folder)
        target_changed = not self.target_folder or os.path.abspath(new_target) != os.path.abspath(self.target_folder)
        if source_changed and not self._confirm_discard_changes():
            return
        self.source_folder = new_source
        self.target_folder = new_target
        self.folder_label.config(text=self.source_folder)
        self.target_folder_label.config(text=self.target_folder)
        if source_changed:
            self._clear_image_state()
        if source_changed or target_changed:
            self._populate_tree()
        self._persist_config()

    def _open_folder_in_file_manager(self, path, title):
        if not os.path.isdir(path):
            messagebox.showerror(title, f"Folder not found:\n{path}")
            return
        try:
            if os.name == "nt":
                os.startfile(path)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except OSError as exc:
            messagebox.showerror(title, f"Could not open folder:\n{exc}")

    def open_source_folder(self):
        self._open_folder_in_file_manager(self.source_folder, "Open Source Folder")

    def open_processed_folder(self):
        if not self.target_folder:
            messagebox.showwarning("Open Processed Folder", "Please set a processed folder first.")
            return
        self._open_folder_in_file_manager(self.target_folder, "Open Processed Folder")

    def edit_max_size(self):
        dialog = MaxSizeDialog(self, self.max_size_enabled, self.max_width, self.max_height)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        self.max_size_enabled, self.max_width, self.max_height = dialog.result
        self._persist_config()
        self._refresh_max_size_status()
        self._update_status()

    def on_tree_select(self, event):
        selection = self.file_tree.selection()
        if not selection:
            return
        path = self._tree_paths.get(selection[0])
        if path is None or path == self.image_path:
            return
        if not self._confirm_discard_changes():
            self._select_tree_node_for_current_image()
            return
        self._load_image(path)

    def _select_tree_node_for_current_image(self):
        """Select whichever tree node corresponds to the currently loaded image, if
        any - used to restore the tree after a cancelled switch and to re-highlight
        the loaded image after a tree rebuild. on_tree_select no-ops when the
        resulting selection's path matches self.image_path, so this never re-triggers
        a load."""
        self.file_tree.selection_remove(self.file_tree.selection())
        if not self.image_path:
            return
        for iid, path in self._tree_paths.items():
            if path == self.image_path:
                self.file_tree.selection_set(iid)
                self.file_tree.focus(iid)
                self.file_tree.see(iid)
                return

    def _select_first_unprocessed_image(self):
        """Select and load the first source image with no processed children yet -
        the image the user is most likely to want to work on next. Falls back to
        the first source image overall if every one already has processed output.
        Called after a tree rebuild when there's no currently loaded image to
        restore."""
        source_iids = self.file_tree.get_children("")
        target_iid = next((iid for iid in source_iids if not self.file_tree.get_children(iid)), None)
        if target_iid is None and source_iids:
            target_iid = source_iids[0]
        if target_iid is not None:
            self.file_tree.selection_set(target_iid)
            self.file_tree.focus(target_iid)
            self.file_tree.see(target_iid)
            self._load_image(self._tree_paths[target_iid])

    def _has_unsaved_changes(self):
        return self.current_image is not None and (self.is_dirty or self.selection_box is not None)

    def _confirm_discard_changes(self):
        """If the loaded image has unsaved edits, ask the user how to proceed.
        Returns True if it's fine to continue (nothing to save, changes were saved,
        or the user chose to discard them), False if the caller should abort."""
        if not self._has_unsaved_changes():
            return True
        filename = os.path.basename(self.image_path)
        is_processed = self._is_processed_image(self.image_path)
        if is_processed:
            prompt = f"You have unsaved changes. Overwrite {filename} with your changes before continuing?"
        else:
            prompt = f"{filename} has unsaved changes. Save before continuing?"
        response = messagebox.askyesnocancel("Unsaved Changes", prompt)
        if response is None:
            return False
        if response:
            if self.selection_box is not None and not self._crop_to_selection():
                return False
            # Already confirmed above (with overwrite-specific wording if applicable) - don't ask again.
            return self._save_current(show_confirmation=False, confirm_overwrite=False)
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
        """Return (width, height) of selection_box in image pixels, or None if
        there's no selection or it's currently zero-sized (e.g. the instant a new
        selection drag starts, before the pointer has moved)."""
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
        width, height = round(crop_right - crop_left), round(crop_bottom - crop_top)
        if width <= 0 or height <= 0:
            return None
        return width, height

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
            self.status_output_var.set("")
        else:
            dirty_marker = " *" if self._has_unsaved_changes() else ""
            self.status_name_var.set(
                f"{os.path.basename(self.image_path)} ({self.current_image.width} x {self.current_image.height})"
                f"{dirty_marker}"
            )
            save_width, save_height = self._planned_save_size()
            self.status_output_var.set(f"Save size: {save_width} x {save_height}")
        self._refresh_message()

    def _refresh_message(self):
        """Set the message panel: while there's an active selection, show its live
        size (formerly its own status bar panel) and the crop hint in place of the
        base message, updating as the user drags to move or resize it; otherwise
        fall back to the current base message."""
        selection_size = self._selection_image_size()
        if selection_size:
            text = f"Selection: {selection_size[0]} x {selection_size[1]}   |   Double click to crop and save."
        else:
            text = self._status_message_base
        self.status_message_var.set(text)

    def _refresh_max_size_status(self):
        if self.max_size_enabled and self.max_width and self.max_height:
            self.max_size_status_var.set(f"Max Save Size: {self.max_width} x {self.max_height}")
        else:
            self.max_size_status_var.set("Max Save Size: not set")

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
            x, y = self._clamp_to_image(event.x, event.y)
            self.selection_start = (x, y)
            self.selection_box = (x, y, x, y)
            self._redraw_selection()

    def _clamp_to_image(self, x, y):
        """Clamp a canvas-space point to the bounds of the displayed image, so a
        crop selection can never extend past the image into the surrounding panel."""
        off_x, off_y = self.display_offset
        disp_w = self.current_image.width * self.display_scale
        disp_h = self.current_image.height * self.display_scale
        return (
            max(off_x, min(x, off_x + disp_w)),
            max(off_y, min(y, off_y + disp_h)),
        )

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
            x, y = self._clamp_to_image(event.x, event.y)
            self.selection_box = (x0, y0, x, y)
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
        if self._drag_mode == "new" and self.selection_box is not None:
            x0, y0, x1, y1 = self.selection_box
            if abs(x1 - x0) < SELECTION_MIN_SIZE or abs(y1 - y0) < SELECTION_MIN_SIZE:
                # A plain click (no real drag) or a click outside an existing
                # selection - don't leave a degenerate selection box behind,
                # since any non-None selection_box counts as an unsaved change.
                self.clear_selection()
                self._redraw_selection()
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

    def _is_processed_image(self, path):
        """True if path is a file already living in the processed folder (i.e. it
        was opened by selecting a processed child node, not a source node)."""
        return bool(self.target_folder) and os.path.dirname(os.path.abspath(path)) == os.path.abspath(
            self.target_folder
        )

    def _save_current(self, show_confirmation, confirm_overwrite=True):
        """Write current_image to disk. Returns True on success.

        A source image is written as a new file in the processed folder using the
        `{root}_NN{ext}` auto-suffix convention (_next_suffix). An image already
        living in the processed folder (opened via a processed child node) is
        instead overwritten in place - editing an already-processed photo replaces
        it rather than spawning another copy - guarded by a confirmation prompt
        when there are unsaved edits that would be overwritten. Pass
        confirm_overwrite=False when the caller already obtained equivalent
        consent (e.g. _confirm_discard_changes' own prompt) to avoid asking twice.
        """
        if self.current_image is None:
            messagebox.showinfo("Save", "No image loaded to save.")
            return False
        if not self.target_folder:
            messagebox.showwarning("Save", "Please set a processed folder first.")
            return False
        filename = os.path.basename(self.image_path)
        if self._is_processed_image(self.image_path):
            if (
                confirm_overwrite
                and self.is_dirty
                and not messagebox.askyesno(
                    "Save", f"You have unsaved changes. Overwrite {filename} with your changes?"
                )
            ):
                return False
            path = self.image_path
        else:
            root, ext = os.path.splitext(filename)
            suffix = self._next_suffix(root, ext)
            path = os.path.join(self.target_folder, f"{root}_{suffix:02d}{ext}")
        try:
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
        self._refresh_processed_children(self.image_path)
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
        was_processed = self._is_processed_image(self.image_path)
        if not self._save_current(show_confirmation=False):
            return
        if was_processed:
            # Overwritten in place, not renamed - re-highlight the same node
            # instead of advancing, since "next source image" doesn't apply.
            self._select_tree_node_for_current_image()
        else:
            self._select_next_file()

    def _select_next_file(self):
        """Advance to the next source image after Process & Save. Selecting the node
        triggers on_tree_select, which does the actual load."""
        source_iids = self.file_tree.get_children("")
        if not source_iids:
            return
        names = [self.file_tree.item(iid, "text") for iid in source_iids]
        current_name = os.path.basename(self.image_path) if self.image_path else None
        try:
            next_index = names.index(current_name) + 1
        except ValueError:
            next_index = 0
        if next_index >= len(source_iids):
            return
        next_iid = source_iids[next_index]
        self.file_tree.selection_set(next_iid)
        self.file_tree.focus(next_iid)
        self.file_tree.see(next_iid)

    # ---------- Help ----------
    def show_user_guide(self):
        messagebox.showinfo(
            "User Guide",
            "1. File > Select Folders... to choose a source and processed folder.\n"
            "2. Pick an image from the file list to load it.\n"
            "3. Drag on the image to select a crop area, then Actions > Crop to Selection. Drag an "
            "edge or corner of an existing selection to resize it, or drag inside it to move it; "
            "while a selection is active, the status bar shows its size in place of the usual "
            "message.\n"
            "4. Use Actions > Rotate Left/Right or Reverse Image to change orientation.\n"
            "5. File > Save (or Actions > Process & Save) to write the result to the processed folder.\n"
            "6. Reset restores the image to how it was loaded.\n"
            "7. File > Max Save Size... sets a maximum width/height applied to images when "
            "they're saved, shrinking them (preserving aspect ratio) if they're larger. Images "
            "are never enlarged. This does not change the image on screen, only the saved file. "
            "When active, it's noted in the status bar.\n"
            "8. Most of these actions - Select Folders, Open Processed Folder, Rotate, Crop to "
            "Selection, and Save - are also available as icon buttons in the toolbar, as a shortcut "
            "to the File/Actions menus.",
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

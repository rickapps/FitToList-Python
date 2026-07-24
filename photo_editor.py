import json
import os
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


class DirectoryPicker(tk.Toplevel):
    """Modal folder browser whose result always matches the path on screen.

    Tk's native directory chooser resolves "OK" differently depending on the
    exact click sequence (a highlighted row vs. the directory currently
    browsed into), which can silently return a folder other than the one
    displayed. This picker shows the whole folder hierarchy as an expandable
    tree (children are loaded lazily, on expand) and keeps the path label in
    sync with whichever folder is highlighted - that's always what
    "Select This Folder" returns.
    """

    _PLACEHOLDER_SUFFIX = "\x00placeholder"

    def __init__(self, parent, initial_dir, title="Select Folder"):
        super().__init__(parent)
        self.title(title)
        self.geometry("480x480")
        self.transient(parent)
        self.result = None

        if initial_dir and os.path.isdir(initial_dir):
            target_dir = os.path.abspath(initial_dir)
        else:
            target_dir = os.path.abspath(os.path.expanduser("~"))

        self.path_var = tk.StringVar()
        path_label = tk.Label(
            self, textvariable=self.path_var, anchor="w", relief=tk.SUNKEN, wraplength=460
        )
        path_label.pack(fill=tk.X, padx=8, pady=(8, 4))

        tree_container = tk.Frame(self)
        tree_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        scrollbar = tk.Scrollbar(tree_container, orient=tk.VERTICAL)
        self.tree = ttk.Treeview(tree_container, show="tree", selectmode="browse", yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewOpen>>", self._on_open)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        btn_frame = tk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=8, pady=8)
        tk.Button(btn_frame, text="Select This Folder", command=self._select).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        tk.Button(btn_frame, text="Cancel", command=self._cancel).pack(side=tk.RIGHT)

        root_path = os.path.abspath(os.sep)
        self._insert_node("", root_path, text=root_path)
        self._expand_to(target_dir)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()
        self.focus_set()

    # ---------- tree population ----------
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
            self.tree.insert(path, tk.END, iid=path + self._PLACEHOLDER_SUFFIX, text="")

    def _populate_children(self, iid):
        children = self.tree.get_children(iid)
        if len(children) == 1 and children[0] == iid + self._PLACEHOLDER_SUFFIX:
            self.tree.delete(children[0])
            for name in self._list_subdirs(iid):
                self._insert_node(iid, os.path.join(iid, name), text=name)

    def _expand_to(self, target_path):
        ancestors = []
        path = target_path
        root_path = os.path.abspath(os.sep)
        while True:
            ancestors.append(path)
            if path == root_path:
                break
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
        if selection and not selection[0].endswith(self._PLACEHOLDER_SUFFIX):
            self.path_var.set(selection[0])

    def _select(self):
        candidate = self.path_var.get()
        if candidate and os.path.isdir(candidate):
            self.result = candidate
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def choose_directory(parent, initial_dir, title="Select Folder"):
    picker = DirectoryPicker(parent, initial_dir, title)
    parent.wait_window(picker)
    return picker.result


class PhotoEditorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FitToList - Photo Crop & Resize")
        self.geometry("1000x700")
        self.minsize(600, 400)

        config = load_config()
        self.source_folder = config.get("source_folder") or os.getcwd()
        self.target_folder = config.get("target_folder")
        self.image_path = None
        self.original_image = None   # PIL.Image as loaded from disk
        self.current_image = None    # PIL.Image after edits
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
        file_menu.add_command(label="Open Folder...", command=self.open_folder)
        file_menu.add_command(label="Set Target Folder...", command=self.choose_target_folder)
        file_menu.add_command(label="Save", command=self.save)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        self.config(menu=menubar)

    def _build_layout(self):
        top_frame = tk.Frame(self)
        top_frame.pack(fill=tk.X, side=tk.TOP)
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
        self.folder_label = tk.Label(
            parent, text=self.source_folder, anchor="w", wraplength=230, justify="left"
        )
        self.folder_label.pack(fill=tk.X, padx=5, pady=(5, 0))

        open_btn = tk.Button(parent, text="Open Folder...", command=self.open_folder)
        open_btn.pack(fill=tk.X, padx=5, pady=(0, 5))

        self.target_folder_label = tk.Label(
            parent,
            text=self.target_folder or "Target folder not set",
            anchor="w",
            wraplength=230,
            justify="left",
        )
        self.target_folder_label.pack(fill=tk.X, padx=5, pady=(5, 0))

        target_btn = tk.Button(parent, text="Set Target Folder...", command=self.choose_target_folder)
        target_btn.pack(fill=tk.X, padx=5, pady=5)

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

    def _build_controls(self, parent):
        controls = tk.Frame(parent)
        controls.pack(fill=tk.X, padx=5, pady=5)
        for col in range(4):
            controls.grid_columnconfigure(col, weight=1)

        tk.Button(controls, text="Crop to Selection", command=self.apply_crop).grid(
            row=0, column=0, padx=2, pady=2, sticky="ew"
        )
        tk.Button(controls, text="Clear Selection", command=self.clear_selection).grid(
            row=0, column=1, padx=2, pady=2, sticky="ew"
        )
        tk.Button(controls, text="Reset", command=self.reset_image).grid(
            row=0, column=2, padx=2, pady=2, sticky="ew"
        )
        tk.Button(controls, text="Save", command=self.save).grid(
            row=0, column=3, padx=2, pady=2, sticky="ew"
        )

        tk.Label(controls, text="Resize:").grid(row=1, column=0, padx=2, pady=2, sticky="w")
        self.scale_var = tk.IntVar(value=100)
        self.scale_slider = tk.Scale(
            controls,
            from_=10,
            to=200,
            orient=tk.HORIZONTAL,
            variable=self.scale_var,
            command=self._on_scale_change,
            showvalue=False,
        )
        self.scale_slider.grid(row=1, column=1, columnspan=2, sticky="ew", padx=2)
        self.scale_pct_label = tk.Label(controls, text="100%", width=5)
        self.scale_pct_label.grid(row=1, column=3, sticky="w")

        tk.Button(controls, text="Apply Resize", command=self.apply_resize).grid(
            row=2, column=0, columnspan=4, padx=2, pady=2, sticky="ew"
        )

    def _build_right_pane(self, parent):
        self.canvas = tk.Canvas(parent, background="#333333", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self.canvas.bind("<Motion>", self._on_hover)

        self.status_var = tk.StringVar(value="No image loaded")
        status_bar = tk.Label(parent, textvariable=self.status_var, anchor="w", relief=tk.SUNKEN)
        status_bar.pack(fill=tk.X, padx=5, pady=(0, 5))

    # ---------- Folder persistence ----------
    def _persist_config(self):
        save_config({"source_folder": self.source_folder, "target_folder": self.target_folder})

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

    def open_folder(self):
        folder = choose_directory(self, self.source_folder, title="Select Source Folder")
        if not folder:
            return
        if self.target_folder and os.path.abspath(folder) == os.path.abspath(self.target_folder):
            messagebox.showerror("Source Folder", "Source folder cannot be the same as the target folder.")
            return
        self.source_folder = folder
        self.folder_label.config(text=self.source_folder)
        self._populate_file_list()
        self._clear_image_state()
        self._persist_config()

    def choose_target_folder(self):
        folder = choose_directory(self, self.target_folder or self.source_folder, title="Select Target Folder")
        if not folder:
            return
        if os.path.abspath(folder) == os.path.abspath(self.source_folder):
            messagebox.showerror("Target Folder", "Target folder cannot be the same as the source folder.")
            return
        self.target_folder = folder
        self.target_folder_label.config(text=self.target_folder)
        self._persist_config()

    def on_file_selected(self, event):
        selection = self.file_listbox.curselection()
        if not selection:
            return
        filename = self.file_listbox.get(selection[0])
        path = os.path.join(self.source_folder, filename)
        self._load_image(path)

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
        self.scale_var.set(100)
        self.scale_pct_label.config(text="100%")
        self.clear_selection()
        self._redraw()
        self.status_var.set(f"{os.path.basename(path)} - {image.width} x {image.height}")

    def _clear_image_state(self):
        self.image_path = None
        self.original_image = None
        self.current_image = None
        self.clear_selection()
        self.canvas.delete("all")
        self.status_var.set("No image loaded")

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

    def apply_crop(self):
        if self.current_image is None or self.selection_box is None:
            return
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
            return

        box = (int(crop_left), int(crop_top), int(crop_right), int(crop_bottom))
        self.current_image = self.current_image.crop(box)
        self.clear_selection()
        self._redraw()
        self.status_var.set(f"Cropped to {self.current_image.width} x {self.current_image.height}")

    # ---------- Resize ----------
    def _on_scale_change(self, value):
        self.scale_pct_label.config(text=f"{int(float(value))}%")

    def apply_resize(self):
        if self.current_image is None:
            return
        pct = self.scale_var.get()
        img_w, img_h = self.current_image.size
        new_w = max(1, int(img_w * pct / 100))
        new_h = max(1, int(img_h * pct / 100))
        self.current_image = self.current_image.resize((new_w, new_h), Image.LANCZOS)
        self.scale_var.set(100)
        self.scale_pct_label.config(text="100%")
        self.clear_selection()
        self._redraw()
        self.status_var.set(f"Resized to {new_w} x {new_h}")

    # ---------- Reset / Save ----------
    def reset_image(self):
        if self.original_image is None:
            return
        self.current_image = self.original_image.copy()
        self.scale_var.set(100)
        self.scale_pct_label.config(text="100%")
        self.clear_selection()
        self._redraw()
        self.status_var.set(f"Reset - {self.current_image.width} x {self.current_image.height}")

    def save(self):
        if self.current_image is None:
            messagebox.showinfo("Save", "No image loaded to save.")
            return
        if not self.target_folder:
            messagebox.showwarning("Save", "Please set a target folder first.")
            return
        filename = os.path.basename(self.image_path)
        path = os.path.join(self.target_folder, filename)
        try:
            image_to_save = self.current_image
            if os.path.splitext(path)[1].lower() in (".jpg", ".jpeg") and image_to_save.mode in ("RGBA", "P"):
                image_to_save = image_to_save.convert("RGB")
            image_to_save.save(path)
        except Exception as exc:
            messagebox.showerror("Error", f"Could not save image:\n{exc}")
            return
        messagebox.showinfo("Save", f"Saved to {path}")


def main():
    app = PhotoEditorApp()
    app.mainloop()


if __name__ == "__main__":
    main()

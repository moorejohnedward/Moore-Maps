"""Moore Maps desktop window (Tkinter)."""

from __future__ import annotations

import json
import os
import queue
import random
import re
import subprocess
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk

from . import __version__, APP_NAME
from . import updater
from .render import MapOptions, PAPERS, build_model, preview_image, export_all
from .terrain import TerrainOptions, load_picture

SCALES = {"1:10,000": 10000, "1:24,000": 24000, "1:25,000": 25000, "1:50,000": 50000}
INTERVALS = {"Auto": 0, "10 ft": 10, "20 ft": 20, "40 ft": 40, "50 ft": 50, "100 ft": 100}


def resource_path(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)


def documents_dir() -> str:
    home = os.path.expanduser("~")
    for d in (os.path.join(home, "Documents"), home):
        if os.path.isdir(d):
            return d
    return home


def open_folder(path: str):
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self, start_file: str | None = None, just_updated: bool = False):
        super().__init__()
        self.title(f"{APP_NAME} {__version__}")
        self.geometry("1440x920")
        self.minsize(1100, 720)
        try:
            self.iconbitmap(resource_path(os.path.join("assets", "app.ico")))
        except Exception:
            pass
        self._apply_theme()

        self.picture_path: str | None = None
        self.picture: Image.Image | None = None
        self.model = None
        self.previews: dict = {}
        self._job = 0
        self._after_id = None
        self._photo = None
        self.update_info = None

        self._ui_queue = queue.Queue()      # background threads hand results back through this
        self.after(80, self._pump)
        self._make_vars()
        self._load_settings()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        updater.cleanup_after_update()
        if just_updated:
            self.status.set(f"Updated to Moore Maps {__version__}. See Help > What's new for the changes.")
        if start_file and os.path.isfile(start_file):
            self.after(200, lambda: self.open_picture(start_file))
        if updater.get_check_on_startup() and "--selftest" not in sys.argv:
            self.after(2500, lambda: self.check_updates(manual=False))

    # ------------------------------------------------------------------ threads
    def _pump(self):
        """Run callbacks queued by background threads (Tk must only be touched from the main thread)."""
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                try:
                    fn()
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass
        self.after(80, self._pump)

    def _ui(self, fn):
        self._ui_queue.put(fn)

    # ------------------------------------------------------------------ theme
    def _apply_theme(self):
        try:
            import sv_ttk
            sv_ttk.set_theme("dark")
            self._dark = True
        except Exception:
            style = ttk.Style(self)
            for t in ("vista", "clam"):
                if t in style.theme_names():
                    style.theme_use(t)
                    break
            self._dark = False
        style = ttk.Style(self)
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 17))
        style.configure("Section.TLabel", font=("Segoe UI Semibold", 11))
        style.configure("Small.TLabel", font=("Segoe UI", 8))
        style.configure("Banner.TFrame", background="#1d5c2e")
        style.configure("Banner.TLabel", background="#1d5c2e", foreground="white", font=("Segoe UI Semibold", 10))

    # ------------------------------------------------------------------ vars
    def _make_vars(self):
        t, m = TerrainOptions(), MapOptions()
        self.v = {
            # terrain
            "invert": tk.BooleanVar(value=t.invert),
            "smoothing": tk.DoubleVar(value=t.smoothing),
            "detail": tk.DoubleVar(value=t.detail),
            "roughness": tk.DoubleVar(value=t.roughness),
            "gamma": tk.DoubleVar(value=t.gamma),
            "seed": tk.IntVar(value=t.seed),
            "low_ft": tk.IntVar(value=int(t.low_ft)),
            "high_ft": tk.IntVar(value=int(t.high_ft)),
            # map
            "title": tk.StringVar(value=m.title),
            "sheet": tk.StringVar(value=m.sheet),
            "scale": tk.StringVar(value="1:25,000"),
            "paper": tk.StringVar(value=m.paper),
            "interval": tk.StringVar(value="Auto"),
            "grid_zone": tk.StringVar(value=m.grid_zone),
            "square_id": tk.StringVar(value=m.square_id),
            "easting_km": tk.IntVar(value=m.easting_km),
            "northing_km": tk.IntVar(value=m.northing_km),
            "gm_angle_deg": tk.DoubleVar(value=m.gm_angle_deg),
            "vegetation": tk.BooleanVar(value=m.vegetation),
            "woods_cover": tk.DoubleVar(value=m.woods_cover),
            "streams": tk.BooleanVar(value=m.streams),
            "hillshade": tk.BooleanVar(value=m.hillshade),
            "photo_underlay": tk.DoubleVar(value=m.photo_underlay),
            "lettered_points": tk.BooleanVar(value=m.lettered_points),
            "course": tk.BooleanVar(value=m.course),
            "num_checkpoints": tk.IntVar(value=m.num_checkpoints),
            "dpi": tk.IntVar(value=m.dpi),
            # view
            "view": tk.StringVar(value="Student map"),
        }
        self.status = tk.StringVar(value="Open a picture to start (File > Open picture, or the button on the left).")

    def _settings_file(self):
        return os.path.join(updater.settings_dir(), "settings.json")

    def _load_settings(self):
        try:
            with open(self._settings_file(), "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, val in data.get("vars", {}).items():
                if k in self.v and k != "view":
                    self.v[k].set(val)
            self.last_dir = data.get("last_dir") or documents_dir()
            self.export_dir = data.get("export_dir") or os.path.join(documents_dir(), "Moore Maps")
        except Exception:
            self.last_dir = documents_dir()
            self.export_dir = os.path.join(documents_dir(), "Moore Maps")

    def _save_settings(self):
        try:
            data = {"vars": {k: var.get() for k, var in self.v.items() if k != "view"},
                    "last_dir": self.last_dir, "export_dir": self.export_dir}
            with open(self._settings_file(), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _on_close(self):
        self._save_settings()
        self.destroy()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self._build_menu()

        top = ttk.Frame(self, padding=(14, 10, 14, 4))
        top.pack(fill="x")
        try:
            logo = Image.open(resource_path(os.path.join("assets", "logo.png"))).resize((40, 40), Image.LANCZOS)
            self._logo = ImageTk.PhotoImage(logo)
            ttk.Label(top, image=self._logo).pack(side="left", padx=(0, 10))
        except Exception:
            pass
        ttk.Label(top, text="Moore Maps", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="  Any picture → military topographic training map").pack(side="left", pady=(6, 0))
        ttk.Button(top, text="Check for updates", command=lambda: self.check_updates(manual=True)).pack(side="right")
        ttk.Label(top, text=f"v{__version__}   ").pack(side="right")

        # update banner (shown when a new version is out)
        self.banner = ttk.Frame(self, style="Banner.TFrame", padding=(14, 6))
        self.banner_text = tk.StringVar()
        ttk.Label(self.banner, textvariable=self.banner_text, style="Banner.TLabel").pack(side="left")
        ttk.Button(self.banner, text="Skip this version", command=self._skip_update).pack(side="right", padx=4)
        ttk.Button(self.banner, text="See what's new / update", command=self._show_update_dialog).pack(side="right")

        body = ttk.Frame(self, padding=(10, 4, 10, 4))
        body.pack(fill="both", expand=True)
        self.body = body

        # left: scrollable controls
        left_outer = ttk.Frame(body)
        left_outer.pack(side="left", fill="y")
        canvas = tk.Canvas(left_outer, width=360, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(left_outer, orient="vertical", command=canvas.yview)
        self.controls = ttk.Frame(canvas, padding=(4, 0, 12, 10))
        self.controls.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.controls, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="y", expand=False)
        sb.pack(side="right", fill="y")
        try:
            canvas.configure(bg=ttk.Style(self).lookup("TFrame", "background") or "#1c1c1c")
        except Exception:
            pass

        def _wheel(e):
            canvas.yview_scroll(int(-e.delta / 120) if e.delta else 0, "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        self._build_controls(self.controls)

        # right: preview
        right = ttk.Frame(body, padding=(10, 0, 0, 0))
        right.pack(side="left", fill="both", expand=True)
        bar = ttk.Frame(right)
        bar.pack(fill="x", pady=(0, 6))
        for name in ("Student map", "Answer key", "Original picture"):
            ttk.Radiobutton(bar, text=name, value=name, variable=self.v["view"],
                            command=self._show_current).pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="Export training packet…", style="Accent.TButton",
                   command=self.export).pack(side="right")
        self.view_canvas = tk.Canvas(right, bg="#2b2b2b", highlightthickness=0)
        self.view_canvas.pack(fill="both", expand=True)
        self.view_canvas.bind("<Configure>", lambda e: self._show_current())

        statusbar = ttk.Frame(self, padding=(14, 4))
        statusbar.pack(fill="x", side="bottom")
        self.progress = ttk.Progressbar(statusbar, mode="indeterminate", length=160)
        self.progress.pack(side="right")
        ttk.Label(statusbar, textvariable=self.status).pack(side="left")

    def _build_menu(self):
        mb = tk.Menu(self)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="Open picture…", command=self.open_picture, accelerator="Ctrl+O")
        fm.add_command(label="Export training packet…", command=self.export, accelerator="Ctrl+E")
        fm.add_separator()
        fm.add_command(label="Exit", command=self._on_close)
        mb.add_cascade(label="File", menu=fm)
        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="Check for updates", command=lambda: self.check_updates(manual=True))
        self._auto_check = tk.BooleanVar(value=updater.get_check_on_startup())
        hm.add_checkbutton(label="Check for updates when Moore Maps starts", variable=self._auto_check,
                           command=lambda: updater.set_check_on_startup(self._auto_check.get()))
        hm.add_command(label="What's new (all versions)", command=lambda: webbrowser.open(
            f"https://github.com/{updater.GITHUB_OWNER}/{updater.GITHUB_REPO}/releases"))
        hm.add_separator()
        hm.add_command(label="How to use Moore Maps", command=self._help)
        hm.add_command(label="About", command=lambda: messagebox.showinfo(
            "About Moore Maps", f"Moore Maps {__version__}\nTurns any picture into a military-style "
            "topographic training map for teaching terrain features and land navigation.\n\nBy John Moore."))
        mb.add_cascade(label="Help", menu=hm)
        self.config(menu=mb)
        self.bind_all("<Control-o>", lambda e: self.open_picture())
        self.bind_all("<Control-e>", lambda e: self.export())

    # controls helpers
    def _section(self, parent, text):
        ttk.Label(parent, text=text, style="Section.TLabel").pack(anchor="w", pady=(14, 4))

    def _slider(self, parent, key, label, lo, hi, tip="", fmt="{:.2f}"):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=2)
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text=label).pack(side="left")
        val = ttk.Label(top, text=fmt.format(self.v[key].get()), width=6, anchor="e")
        val.pack(side="right")
        s = ttk.Scale(f, from_=lo, to=hi, variable=self.v[key],
                      command=lambda _=None: (val.configure(text=fmt.format(self.v[key].get())),
                                              self._schedule()))
        s.pack(fill="x")
        if tip:
            ttk.Label(f, text=tip, style="Small.TLabel", foreground="#9a9a9a", wraplength=330).pack(anchor="w")

    def _check(self, parent, key, label):
        ttk.Checkbutton(parent, text=label, variable=self.v[key], command=self._schedule).pack(anchor="w", pady=2)

    def _entry(self, parent, key, label, width=18):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=2)
        ttk.Label(f, text=label, width=16).pack(side="left")
        e = ttk.Entry(f, textvariable=self.v[key], width=width)
        e.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda ev: self._schedule(0))
        e.bind("<FocusOut>", lambda ev: self._schedule())

    def _combo(self, parent, key, label, values):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=2)
        ttk.Label(f, text=label, width=16).pack(side="left")
        c = ttk.Combobox(f, textvariable=self.v[key], values=list(values), state="readonly", width=20)
        c.pack(side="left", fill="x", expand=True)
        c.bind("<<ComboboxSelected>>", lambda e: self._schedule(0))

    def _spin(self, parent, key, label, lo, hi, inc=1):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=2)
        ttk.Label(f, text=label, width=16).pack(side="left")
        s = ttk.Spinbox(f, textvariable=self.v[key], from_=lo, to=hi, increment=inc, width=8,
                        command=self._schedule)
        s.pack(side="left")
        s.bind("<Return>", lambda ev: self._schedule(0))
        s.bind("<FocusOut>", lambda ev: self._schedule())
        return f

    def _build_controls(self, p):
        ttk.Button(p, text="Open picture…", style="Accent.TButton", command=self.open_picture).pack(fill="x", pady=(6, 2))
        self.pic_label = ttk.Label(p, text="No picture yet", style="Small.TLabel", wraplength=330)
        self.pic_label.pack(anchor="w")

        self._section(p, "Picture → ground")
        self._check(p, "invert", "Invert (dark parts become high ground)")
        self._slider(p, "detail", "Picture likeness", 0.0, 1.0,
                     "Higher keeps more of the picture's shapes in the contours.")
        self._slider(p, "smoothing", "Smoothness", 0.8, 6.0, "Higher = rounder, gentler hills.", "{:.1f}")
        self._slider(p, "roughness", "Natural bumps", 0.0, 0.3, "Adds small random knolls and folds.")
        self._slider(p, "gamma", "Peak steepness", 0.5, 2.0, "Above 1 makes high ground steeper.")
        f = self._spin(p, "seed", "Random seed", 0, 99999)
        ttk.Button(f, text="New random", command=self._new_seed).pack(side="left", padx=6)

        self._section(p, "Elevation")
        self._spin(p, "low_ft", "Lowest (ft)", -1000, 29000, 50)
        self._spin(p, "high_ft", "Highest (ft)", -1000, 29000, 50)
        self._combo(p, "interval", "Contour interval", INTERVALS.keys())

        self._section(p, "Map sheet")
        self._entry(p, "title", "Map title")
        self._entry(p, "sheet", "Sheet number")
        self._combo(p, "scale", "Scale", SCALES.keys())
        self._combo(p, "paper", "Paper", PAPERS.keys())
        self._entry(p, "grid_zone", "Grid zone", 6)
        self._entry(p, "square_id", "100k square ID", 6)
        self._spin(p, "easting_km", "First easting", 0, 99)
        self._spin(p, "northing_km", "First northing", 0, 99)
        self._spin(p, "gm_angle_deg", "G-M angle °(E+)", -30, 30, 0.5)

        self._section(p, "What's on the map")
        self._check(p, "vegetation", "Woods (green)")
        self._slider(p, "woods_cover", "Woods amount", 0.05, 0.8)
        self._check(p, "streams", "Streams (blue)")
        self._check(p, "hillshade", "Relief shading")
        self._slider(p, "photo_underlay", "Show picture under map", 0.0, 0.8,
                     "0 = classic map. Turn up to reveal the picture.")
        self._check(p, "lettered_points", "Lettered terrain-feature points (A, B, C…)")
        self._check(p, "course", "Land-nav course (SP + checkpoints)")
        self._spin(p, "num_checkpoints", "Checkpoints", 2, 10)

        self._section(p, "Export")
        self._combo(p, "dpi", "Print quality (dpi)", [150, 200, 300, 400])
        ttk.Label(p, text="300 dpi is print-shop quality. Larger paper sizes take longer.",
                  style="Small.TLabel", foreground="#9a9a9a", wraplength=330).pack(anchor="w")

    # ------------------------------------------------------------------ options
    def _read_options(self):
        g = lambda k: self.v[k].get()     # noqa: E731
        low, high = float(g("low_ft")), float(g("high_ft"))
        if high - low < 50:
            high = low + 50
        topt = TerrainOptions(smoothing=float(g("smoothing")), detail=float(g("detail")), invert=bool(g("invert")),
                              gamma=float(g("gamma")), roughness=float(g("roughness")), seed=int(g("seed")),
                              low_ft=low, high_ft=high)
        sq = re.sub(r"[^A-Za-z]", "", g("square_id")).upper()[:2] or "KV"
        mopt = MapOptions(title=g("title") or "TRAINING AREA", sheet=g("sheet") or "MM 001",
                          scale=SCALES.get(g("scale"), 25000), paper=g("paper"),
                          contour_interval_ft=INTERVALS.get(g("interval"), 0),
                          grid_zone=(g("grid_zone") or "5Q").upper()[:4], square_id=sq,
                          easting_km=int(g("easting_km")) % 100, northing_km=int(g("northing_km")) % 100,
                          gm_angle_deg=float(g("gm_angle_deg")), vegetation=bool(g("vegetation")),
                          woods_cover=float(g("woods_cover")), streams=bool(g("streams")),
                          hillshade=bool(g("hillshade")), photo_underlay=float(g("photo_underlay")),
                          lettered_points=bool(g("lettered_points")), course=bool(g("course")),
                          num_checkpoints=max(2, min(10, int(g("num_checkpoints")))), dpi=int(g("dpi")))
        return topt, mopt

    def _new_seed(self):
        self.v["seed"].set(random.randint(1, 99999))
        self._schedule(0)

    # ------------------------------------------------------------------ actions
    def open_picture(self, path: str | None = None):
        if not path:
            path = filedialog.askopenfilename(
                title="Choose a picture", initialdir=self.last_dir,
                filetypes=[("Pictures", "*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.picture = load_picture(path)
        except Exception as e:
            messagebox.showerror("Moore Maps", f"Couldn't open that picture:\n{e}")
            return
        self.picture_path = path
        self.last_dir = os.path.dirname(path)
        base = os.path.splitext(os.path.basename(path))[0]
        self.pic_label.configure(text=f"{os.path.basename(path)}  ({self.picture.width} x {self.picture.height})")
        if self.v["title"].get() in ("", "TRAINING AREA"):
            self.v["title"].set(re.sub(r"[_\-]+", " ", base).upper()[:40] + " TRAINING AREA")
        self.previews = {"Original picture": self.picture.copy()}
        self._schedule(0)

    def _schedule(self, delay_ms: int = 700):
        if self.picture is None:
            return
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(delay_ms, self._render)

    def _render(self):
        self._after_id = None
        self._job += 1
        job = self._job
        topt, mopt = self._read_options()
        pic = self.picture
        self.status.set("Building terrain and drawing the map…")
        self.progress.start(12)

        def work():
            try:
                model = build_model(pic, topt, mopt)
                student = preview_image(model, key=False, max_px=1800)
                key = preview_image(model, key=True, max_px=1800)
                self._ui(lambda: self._render_done(job, model, student, key, None))
            except Exception:
                err = traceback.format_exc()
                self._ui(lambda: self._render_done(job, None, None, None, err))

        threading.Thread(target=work, daemon=True).start()

    def _render_done(self, job, model, student, key, err):
        if job != self._job:
            return                      # a newer render is already running
        self.progress.stop()
        if err:
            self.status.set("Something went wrong drawing the map (details in the pop-up).")
            messagebox.showerror("Moore Maps", err[-1500:])
            return
        self.model = model
        self.previews["Student map"] = student
        self.previews["Answer key"] = key
        f = model.feats
        counts = ", ".join(f"{len(getattr(f, n))} {n}" for n in
                           ("hilltops", "saddles", "depressions", "valleys", "ridges", "draws", "spurs"))
        self.status.set(f"Ready. Contour interval {model.ci_ft:g} ft. Found {counts}, {len(f.cliffs)} cliffs.")
        self._show_current()

    def _show_current(self):
        img = self.previews.get(self.v["view"].get())
        c = self.view_canvas
        c.delete("all")
        cw, ch = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        if img is None:
            c.create_text(cw / 2, ch / 2, fill="#bbbbbb", font=("Segoe UI", 13),
                          text="Open a picture to make a map.\n\nTip: pictures with clear light and dark areas\n"
                               "make the best hills and valleys.", justify="center")
            return
        s = min(cw / img.width, ch / img.height)
        disp = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(disp)
        c.create_image(cw / 2, ch / 2, image=self._photo)

    def export(self):
        if self.picture is None:
            messagebox.showinfo("Moore Maps", "Open a picture first.")
            return
        os.makedirs(self.export_dir, exist_ok=True)
        folder = filedialog.askdirectory(title="Save the training packet in…", initialdir=self.export_dir)
        if not folder:
            return
        self.export_dir = folder
        topt, mopt = self._read_options()
        base = re.sub(r'[<>:"/\\|?*]+', "", mopt.title).strip() or "Moore Map"
        pic = self.picture
        self.status.set(f"Exporting at {mopt.dpi} dpi… (this can take a minute for big paper)")
        self.progress.start(12)

        def work():
            try:
                model = build_model(pic, topt, mopt)
                paths = export_all(model, folder, base)
                self._ui(lambda: self._export_done(folder, paths, None))
            except Exception:
                err = traceback.format_exc()
                self._ui(lambda: self._export_done(folder, None, err))

        threading.Thread(target=work, daemon=True).start()

    def _export_done(self, folder, paths, err):
        self.progress.stop()
        if err:
            self.status.set("Export failed.")
            messagebox.showerror("Moore Maps", err[-1500:])
            return
        self._save_settings()
        self.status.set(f"Saved {len(paths)} files to {folder}")
        names = "\n".join("• " + os.path.basename(p) for p in paths)
        messagebox.showinfo("Training packet saved",
                            f"Saved to {folder}:\n\n{names}\n\nThe PDF has the student map, exercise sheet, "
                            f"reference card, answer-key map and answer sheet.")
        open_folder(folder)

    # ------------------------------------------------------------------ updates
    def check_updates(self, manual: bool):
        if manual:
            self.status.set("Checking GitHub for a newer version…")

        def work():
            try:
                info = updater.check(quiet=not manual)
                self._ui(lambda: self._update_checked(info, None, manual))
            except Exception as e:
                self._ui(lambda e=e: self._update_checked(None, e, manual))

        threading.Thread(target=work, daemon=True).start()

    def _update_checked(self, info, err, manual):
        if err is not None:
            if isinstance(err, updater.NoReleasesYet):
                self.status.set("No updates published yet.")
                messagebox.showinfo("Moore Maps", f"You have Moore Maps {__version__}. No updates have been "
                                                  "published on GitHub yet.")
            else:
                self.status.set("Couldn't check for updates.")
                messagebox.showwarning("Moore Maps", f"Couldn't reach GitHub to check for updates.\n\n{err}")
            return
        if info is None:
            if manual:
                self.status.set(f"You're up to date (v{__version__}).")
                messagebox.showinfo("Moore Maps", f"You're up to date. Moore Maps {__version__} is the newest version.")
            return
        self.update_info = info
        if not manual and updater.is_skipped(info):
            return
        self.banner_text.set(f"Moore Maps {info.version_text} is ready (you have {__version__}).")
        self.banner.pack(fill="x", before=self.body)
        if manual:
            self._show_update_dialog()

    def _skip_update(self):
        if self.update_info:
            updater.skip(self.update_info)
        self.banner.pack_forget()

    def _show_update_dialog(self):
        info = self.update_info
        if info is None:
            return
        d = tk.Toplevel(self)
        d.title("Update Moore Maps")
        d.geometry("620x480")
        d.transient(self)
        d.grab_set()
        frm = ttk.Frame(d, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=f"Moore Maps {info.version_text} is ready", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frm, text=f"You have {__version__}. Here's what's new:").pack(anchor="w", pady=(2, 8))
        txt = tk.Text(frm, wrap="word", height=14, relief="flat")
        txt.insert("1.0", info.notes.strip() or "(No notes for this version.)")
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True)
        pb = ttk.Progressbar(frm, mode="determinate", maximum=1.0)
        pb.pack(fill="x", pady=8)
        msg = tk.StringVar(value="The app downloads the new version, checks it, and restarts itself.")
        ttk.Label(frm, textvariable=msg).pack(anchor="w")
        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(10, 0))

        def go():
            if not updater.is_frozen():
                messagebox.showinfo("Moore Maps", "You're running from the source code, so there's no .exe to swap.\n"
                                                  "Opening the Releases page instead.", parent=d)
                webbrowser.open(info.page_url)
                return
            for b in btns.winfo_children():
                b.configure(state="disabled")
            msg.set("Downloading…")

            def work():
                try:
                    updater.download_and_install(info, progress=lambda f: self._ui(lambda: pb.configure(value=f)))
                    self._ui(lambda: (self._save_settings(), self.destroy()))
                except Exception as e:
                    self._ui(lambda e=e: (msg.set(str(e)),
                                           [b.configure(state="normal") for b in btns.winfo_children()]))

            threading.Thread(target=work, daemon=True).start()

        ttk.Button(btns, text="Update now", style="Accent.TButton", command=go).pack(side="right")
        ttk.Button(btns, text="Later", command=d.destroy).pack(side="right", padx=6)
        ttk.Button(btns, text="Skip this version", command=lambda: (self._skip_update(), d.destroy())).pack(side="left")

    def _help(self):
        messagebox.showinfo("How to use Moore Maps", (
            "1. Open a picture. Bright areas become high ground, dark areas low ground (tick Invert to flip it).\n"
            "2. Adjust 'Picture likeness' and 'Smoothness' until the hills and valleys look right.\n"
            "3. Set the map title, scale and paper size.\n"
            "4. Check the Answer key view: every lettered point is labeled with its terrain feature, and the "
            "land-nav legs show azimuths and distances.\n"
            "5. Export training packet: student map and answer-key map as PNG, plus a PDF with the student map, "
            "exercise sheet, terrain-feature reference card, answer-key map and answer sheet.\n\n"
            "'New random' changes the bumps, woods, lettered points and course but keeps the picture's shape."))


def selftest(picture: str, report: str):
    """Opens the real window, draws a map, writes 'ok' to the report file and closes.
    The GitHub build runs this on the .exe before publishing a release."""
    import time
    t0 = time.time()
    app = App(start_file=picture)

    def poll():
        if app.model is not None and app._photo is not None:
            with open(report, "w") as f:
                f.write(f"ok {__version__} {app.status.get()}")
            app.destroy()
        elif time.time() - t0 > 120:
            with open(report, "w") as f:
                f.write("timeout " + app.status.get())
            app.destroy()
        else:
            app.after(300, poll)

    app.after(500, poll)
    app.mainloop()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--selftest"] and len(argv) >= 3:
        selftest(argv[1], argv[2])
        return
    just_updated = "--updated" in argv
    files = [a for a in argv if not a.startswith("--")]
    app = App(start_file=files[0] if files else None, just_updated=just_updated)
    app.mainloop()

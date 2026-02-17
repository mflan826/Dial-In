"""
Sniper Drag Tuner - Main Application GUI
"""

import os
import sys
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime
from typing import Optional, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dlz_parser import parse_dlz_file, generate_sample_datalog, SniperDatalog
from config_generator import (
    VehicleSpec, TimeSlipData, SniperConfigGenerator,
    TuningRecommendation, export_config_json, export_report_txt
)
from tuning_agent import TuningAgent, ModelManager, EFIKnowledgeBase

# ─── Theme ──────────────────────────────────────────────
C = {
    "bg": "#0D1117", "panel": "#161B22", "card": "#1E2736",
    "input": "#1C2333", "hover": "#252E3F",
    "red": "#E8372C", "orange": "#FF8C00", "green": "#22C55E", "blue": "#58A6FF",
    "text": "#E6EDF3", "dim": "#8B949E", "bright": "#FFFFFF",
    "border": "#30363D",
}
FONT = "Segoe UI"


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Sniper Drag Tuner — Holley EFI Tuning Assistant")
        self.root.geometry("1280x860")
        self.root.minsize(1024, 700)
        self.root.configure(bg=C["bg"])

        self.spec = VehicleSpec()
        self.time_slips: List[TimeSlipData] = []
        self.datalog: Optional[SniperDatalog] = None
        self.analysis: Optional[Dict] = None
        self.recs: List[TuningRecommendation] = []
        self.agent = TuningAgent()
        self.vars = {}

        self.data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(self.data_dir, exist_ok=True)
        self._load_state()
        self._styles()
        self._build()

    # ─── Helpers ─────────────────────────────────────────
    def _styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TNotebook", background=C["bg"], borderwidth=0)
        s.configure("TNotebook.Tab", background=C["panel"], foreground=C["dim"],
                    font=(FONT, 10, "bold"), padding=(14, 7))
        s.map("TNotebook.Tab",
              background=[("selected", C["card"])], foreground=[("selected", C["red"])])

    def _frame(self, parent, bg=None):
        f = tk.Frame(parent, bg=bg or C["panel"], highlightthickness=1,
                     highlightbackground=C["border"], padx=14, pady=10)
        f.pack(fill=tk.X, padx=16, pady=6)
        return f

    def _label(self, parent, text, size=10, bold=False, fg=None, bg=None, **kw):
        weight = "bold" if bold else "normal"
        lbl = tk.Label(parent, text=text, font=(FONT, size, weight),
                       bg=bg or parent.cget("bg"), fg=fg or C["text"], **kw)
        return lbl

    def _entry(self, parent, var_name, default="", width=20):
        v = tk.StringVar(value=default)
        self.vars[var_name] = v
        e = tk.Entry(parent, textvariable=v, width=width,
                     bg=C["input"], fg=C["text"], insertbackground=C["text"],
                     font=(FONT, 10), relief=tk.FLAT, highlightthickness=1,
                     highlightbackground=C["border"])
        return e

    def _combo(self, parent, var_name, values, default=""):
        v = tk.StringVar(value=default)
        self.vars[var_name] = v
        cb = ttk.Combobox(parent, textvariable=v, values=values, state="readonly", width=18)
        cb.set(default)
        return cb

    def _check(self, parent, var_name, default=False):
        v = tk.BooleanVar(value=default)
        self.vars[var_name] = v
        cb = tk.Checkbutton(parent, variable=v, bg=parent.cget("bg"),
                            fg=C["text"], selectcolor=C["input"],
                            activebackground=parent.cget("bg"),
                            font=(FONT, 10))
        return cb

    def _btn(self, parent, text, command, accent=False, **kw):
        bg = C["red"] if accent else C["input"]
        fg = C["bright"] if accent else C["text"]
        b = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                      font=(FONT, 10, "bold" if accent else "normal"),
                      relief=tk.FLAT, padx=14, pady=6, cursor="hand2",
                      activebackground=C["hover"], **kw)
        return b

    def _section(self, parent, title):
        tk.Label(parent, text=title, font=(FONT, 12, "bold"),
                bg=C["bg"], fg=C["red"]).pack(anchor=tk.W, padx=18, pady=(12, 2))

    def _field_row(self, parent, label_text, var_name, default, row, width=14, field_type="entry", options=None):
        lbl = tk.Label(parent, text=label_text, font=(FONT, 10),
                      bg=parent.cget("bg"), fg=C["text"], anchor=tk.W)
        lbl.grid(row=row, column=0, sticky=tk.W, padx=(8, 12), pady=3)
        if field_type == "combo":
            w = self._combo(parent, var_name, options or [], default)
        elif field_type == "check":
            w = self._check(parent, var_name, default)
        else:
            w = self._entry(parent, var_name, str(default), width)
        w.grid(row=row, column=1, sticky=tk.W, padx=4, pady=3)
        return w

    def _scrollable(self, parent):
        canvas = tk.Canvas(parent, bg=C["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=C["bg"])
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        return inner

    # ─── Build UI ─────────────────────────────────────
    def _build(self):
        # Header
        hdr = tk.Frame(self.root, bg=C["panel"], height=52)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🏁 SNIPER DRAG TUNER", font=(FONT, 15, "bold"),
                bg=C["panel"], fg=C["bright"]).pack(side=tk.LEFT, padx=16)
        tk.Label(hdr, text="Holley EFI Local Tuning Assistant", font=(FONT, 9),
                bg=C["panel"], fg=C["dim"]).pack(side=tk.LEFT, padx=8)
        self.status_lbl = tk.Label(hdr, text="● Expert System Active", font=(FONT, 9),
                                   bg=C["panel"], fg=C["green"])
        self.status_lbl.pack(side=tk.RIGHT, padx=16)

        # Notebook
        nb = ttk.Notebook(self.root)
        nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=(2, 6))

        tabs = [
            ("  🚗 Vehicle Setup  ", self._build_vehicle),
            ("  📊 Datalog (.DLZ)  ", self._build_datalog),
            ("  🏎️ Time Slips  ", self._build_timeslip),
            ("  🔧 Analysis  ", self._build_analysis),
            ("  💬 Tuning Chat  ", self._build_chat),
            ("  ⚙️ Settings  ", self._build_settings),
        ]
        for title, builder in tabs:
            frame = tk.Frame(nb, bg=C["bg"])
            nb.add(frame, text=title)
            builder(frame)

        # Status bar
        self.sbar = tk.Label(self.root, text="Ready", bg=C["panel"], fg=C["dim"],
                            font=(FONT, 9), anchor=tk.W, padx=16, pady=3)
        self.sbar.pack(fill=tk.X, side=tk.BOTTOM)

    # ═══════════════════════════════════════════════════
    # TAB 1: Vehicle Setup
    # ═══════════════════════════════════════════════════
    def _build_vehicle(self, parent):
        inner = self._scrollable(parent)
        top = tk.Frame(inner, bg=C["bg"])
        top.pack(fill=tk.X, padx=16, pady=8)

        self._label(top, "Enter your vehicle and engine details. These are critical for accurate tuning.",
                   size=10, fg=C["dim"]).pack(anchor=tk.W)

        # ── Engine ──
        self._section(inner, "ENGINE SPECIFICATIONS")
        ef = self._frame(inner)
        ef.columnconfigure(0, minsize=250)
        r = 0
        self._field_row(ef, "Engine Displacement (ci)", "disp", self.spec.engine_displacement_ci, r); r+=1
        self._field_row(ef, "Engine Type", "etype", self.spec.engine_type, r,
                       field_type="combo", options=["SBC","BBC","SBF","BBF","LS","LT","Hemi","Pontiac","Buick","Olds","AMC"]); r+=1
        self._field_row(ef, "Cylinder Count", "cyl", self.spec.cylinder_count, r, width=6); r+=1
        self._field_row(ef, "Compression Ratio", "comp", self.spec.compression_ratio, r, width=8); r+=1
        self._field_row(ef, "Cam Profile", "cam", self.spec.cam_type, r,
                       field_type="combo", options=["stock_mild","street_strip","race"]); r+=1
        self._field_row(ef, "Cam Duration Intake @.050\"", "cam_int", self.spec.cam_duration_intake, r, width=8); r+=1
        self._field_row(ef, "Cam Duration Exhaust @.050\"", "cam_exh", self.spec.cam_duration_exhaust, r, width=8); r+=1
        self._field_row(ef, "Cam Lift Intake", "lift_int", self.spec.cam_lift_intake, r, width=8); r+=1
        self._field_row(ef, "Cam Lift Exhaust", "lift_exh", self.spec.cam_lift_exhaust, r, width=8); r+=1
        self._field_row(ef, "Cam LSA", "lsa", self.spec.cam_lsa, r, width=6); r+=1
        self._field_row(ef, "Idle Vacuum (inHg)", "vac", self.spec.idle_vacuum_inhg, r, width=8); r+=1
        self._field_row(ef, "Fuel Type", "fuel", self.spec.fuel_type, r,
                       field_type="combo", options=["pump_87","pump_91","pump_93","e85","race_100","race_110"]); r+=1

        # ── EFI System ──
        self._section(inner, "HOLLEY SNIPER EFI SYSTEM")
        sf = self._frame(inner)
        sf.columnconfigure(0, minsize=250)
        r = 0
        self._field_row(sf, "Sniper Model", "smodel", self.spec.sniper_model, r,
                       field_type="combo", options=["4150","4500","2300","QuadraJet","Super Sniper"]); r+=1
        self._field_row(sf, "HP Rating", "shp", self.spec.sniper_flow_hp, r,
                       field_type="combo", options=["550","650","800","1250"]); r+=1
        self._field_row(sf, "Injector Flow (lb/hr)", "inj_flow", self.spec.injector_flow_lbhr, r, width=8); r+=1
        self._field_row(sf, "Fuel Pressure (PSI)", "fp", self.spec.fuel_pressure_psi, r, width=8); r+=1
        self._field_row(sf, "Timing Control", "tc", self.spec.has_timing_control, r, field_type="check"); r+=1
        self._field_row(sf, "Ignition Type", "ign", self.spec.ignition_type, r,
                       field_type="combo", options=["hyperspark","hei","msd_6al","msd_digital","points","other"]); r+=1

        # ── Drivetrain ──
        self._section(inner, "DRIVETRAIN")
        df = self._frame(inner)
        df.columnconfigure(0, minsize=250)
        r = 0
        self._field_row(df, "Transmission Type", "trans_type", self.spec.transmission_type, r,
                       field_type="combo", options=["auto","manual"]); r+=1
        self._field_row(df, "Transmission Model", "trans", self.spec.transmission_model, r,
                       field_type="combo", options=["TH350","TH400","700R4/4L60","4L60E","4L80E","200-4R",
                                                    "Powerglide","C4","C6","AOD","T56","T5","Muncie","Tremec_TKX","Other"]); r+=1
        self._field_row(df, "Converter Stall (RPM)", "stall", self.spec.converter_stall, r, width=8); r+=1
        self._field_row(df, "Rear Gear Ratio", "gear", self.spec.rear_gear_ratio, r, width=8); r+=1
        self._field_row(df, "Tire Diameter (in)", "tire_d", self.spec.tire_diameter_in, r, width=8); r+=1
        self._field_row(df, "Tire Type", "tire_t", self.spec.tire_type, r,
                       field_type="combo", options=["street","drag_radial","slick","et_street"]); r+=1

        # ── Vehicle ──
        self._section(inner, "VEHICLE")
        vf = self._frame(inner)
        vf.columnconfigure(0, minsize=250)
        r = 0
        self._field_row(vf, "Year", "vyear", self.spec.vehicle_year, r, width=8); r+=1
        self._field_row(vf, "Make", "vmake", self.spec.vehicle_make, r); r+=1
        self._field_row(vf, "Model", "vmodel", self.spec.vehicle_model, r); r+=1
        self._field_row(vf, "Race Weight (lbs)", "weight", self.spec.vehicle_weight_lbs, r, width=8); r+=1

        # ── Power Adders ──
        self._section(inner, "POWER ADDERS")
        pf = self._frame(inner)
        pf.columnconfigure(0, minsize=250)
        r = 0
        self._field_row(pf, "Nitrous", "nos", self.spec.use_nitrous, r, field_type="check"); r+=1
        self._field_row(pf, "Nitrous HP", "nos_hp", self.spec.nitrous_hp, r, width=8); r+=1
        self._field_row(pf, "Forced Induction", "boost", self.spec.use_boost, r, field_type="check"); r+=1
        self._field_row(pf, "Boost PSI", "boost_psi", self.spec.boost_psi, r, width=8); r+=1

        # Save button
        bf = tk.Frame(inner, bg=C["bg"])
        bf.pack(fill=tk.X, padx=16, pady=12)
        self._btn(bf, "💾  Save Vehicle Setup", self._save_vehicle, accent=True).pack(side=tk.LEFT)
        self._btn(bf, "📋  Load Saved Setup", self._load_vehicle_dialog).pack(side=tk.LEFT, padx=8)

    def _save_vehicle(self):
        try:
            s = self.spec
            v = self.vars
            s.engine_displacement_ci = int(float(v.get("disp", tk.StringVar()).get() or 350))
            s.engine_type = v.get("etype", tk.StringVar()).get() or "SBC"
            s.cylinder_count = int(float(v.get("cyl", tk.StringVar()).get() or 8))
            s.compression_ratio = float(v.get("comp", tk.StringVar()).get() or 9.5)
            s.cam_type = v.get("cam", tk.StringVar()).get() or "stock_mild"
            s.cam_duration_intake = int(float(v.get("cam_int", tk.StringVar()).get() or 210))
            s.cam_duration_exhaust = int(float(v.get("cam_exh", tk.StringVar()).get() or 218))
            s.cam_lift_intake = float(v.get("lift_int", tk.StringVar()).get() or 0.48)
            s.cam_lift_exhaust = float(v.get("lift_exh", tk.StringVar()).get() or 0.48)
            s.cam_lsa = int(float(v.get("lsa", tk.StringVar()).get() or 112))
            s.idle_vacuum_inhg = float(v.get("vac", tk.StringVar()).get() or 14)
            s.fuel_type = v.get("fuel", tk.StringVar()).get() or "pump_93"
            s.sniper_model = v.get("smodel", tk.StringVar()).get() or "4150"
            s.sniper_flow_hp = int(float(v.get("shp", tk.StringVar()).get() or 650))
            s.injector_flow_lbhr = float(v.get("inj_flow", tk.StringVar()).get() or 36)
            s.fuel_pressure_psi = float(v.get("fp", tk.StringVar()).get() or 58.5)
            s.has_timing_control = v.get("tc", tk.BooleanVar()).get()
            s.ignition_type = v.get("ign", tk.StringVar()).get() or "hyperspark"
            s.transmission_type = v.get("trans_type", tk.StringVar()).get() or "auto"
            s.transmission_model = v.get("trans", tk.StringVar()).get() or "TH400"
            s.converter_stall = int(float(v.get("stall", tk.StringVar()).get() or 2500))
            s.rear_gear_ratio = float(v.get("gear", tk.StringVar()).get() or 3.73)
            s.tire_diameter_in = float(v.get("tire_d", tk.StringVar()).get() or 28)
            s.tire_type = v.get("tire_t", tk.StringVar()).get() or "drag_radial"
            s.vehicle_year = int(float(v.get("vyear", tk.StringVar()).get() or 1969))
            s.vehicle_make = v.get("vmake", tk.StringVar()).get() or "Chevrolet"
            s.vehicle_model = v.get("vmodel", tk.StringVar()).get() or "Camaro"
            s.vehicle_weight_lbs = int(float(v.get("weight", tk.StringVar()).get() or 3400))
            s.use_nitrous = v.get("nos", tk.BooleanVar()).get()
            s.nitrous_hp = int(float(v.get("nos_hp", tk.StringVar()).get() or 0))
            s.use_boost = v.get("boost", tk.BooleanVar()).get()
            s.boost_psi = float(v.get("boost_psi", tk.StringVar()).get() or 0)

            path = os.path.join(self.data_dir, "vehicle_spec.json")
            with open(path, "w") as f:
                json.dump(s.to_dict(), f, indent=2)
            self.sbar.config(text=f"Vehicle spec saved: {s.vehicle_year} {s.vehicle_make} {s.vehicle_model}")
            messagebox.showinfo("Saved", "Vehicle setup saved successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save: {e}")

    def _load_vehicle_dialog(self):
        path = filedialog.askopenfilename(
            title="Load Vehicle Spec", filetypes=[("JSON", "*.json")],
            initialdir=self.data_dir)
        if path:
            try:
                with open(path) as f:
                    data = json.load(f)
                self.spec = VehicleSpec.from_dict(data)
                messagebox.showinfo("Loaded", "Vehicle spec loaded. Switch tabs and come back to refresh.")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    # ═══════════════════════════════════════════════════
    # TAB 2: Datalog
    # ═══════════════════════════════════════════════════
    def _build_datalog(self, parent):
        top = tk.Frame(parent, bg=C["bg"])
        top.pack(fill=tk.X, padx=16, pady=12)

        self._label(top, "Upload a Holley Sniper EFI datalog (.DLZ or .DL) from a drag strip pass.",
                   fg=C["dim"]).pack(anchor=tk.W)

        bf = tk.Frame(parent, bg=C["bg"])
        bf.pack(fill=tk.X, padx=16, pady=4)
        self._btn(bf, "📂  Open Datalog File (.DLZ / .DL)", self._open_datalog, accent=True).pack(side=tk.LEFT)
        self._btn(bf, "🧪  Load Sample Data", self._load_sample_datalog).pack(side=tk.LEFT, padx=8)

        self.dl_info = tk.Label(parent, text="No datalog loaded", font=(FONT, 10),
                               bg=C["bg"], fg=C["dim"], anchor=tk.W, wraplength=800, justify=tk.LEFT)
        self.dl_info.pack(fill=tk.X, padx=20, pady=8)

        self._label(parent, "Datalog Analysis:", size=11, bold=True, bg=C["bg"], fg=C["bright"]).pack(
            anchor=tk.W, padx=20, pady=(8, 2))

        self.dl_text = scrolledtext.ScrolledText(parent, width=100, height=30,
                                                  bg=C["card"], fg=C["text"],
                                                  font=("Consolas", 10),
                                                  insertbackground=C["text"],
                                                  relief=tk.FLAT, wrap=tk.WORD)
        self.dl_text.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))
        self.dl_text.insert(tk.END, "Upload a .DLZ datalog or load sample data to begin analysis.\n\n"
                           "The DLZ format is the compressed datalog format used by Holley Sniper EFI.\n"
                           "You can find these files on the SD card from your Sniper handheld\n"
                           "or record them via USB with the Holley EFI software.\n\n"
                           "Path: SD Card > Saved Datalogs > Sniper_XXXX.dlz")

    def _open_datalog(self):
        path = filedialog.askopenfilename(
            title="Open Holley Sniper Datalog",
            filetypes=[("Holley Datalogs", "*.dlz *.dl *.DLZ *.DL"),
                       ("CSV Exports", "*.csv"), ("All Files", "*.*")])
        if not path:
            return
        self.sbar.config(text=f"Parsing {os.path.basename(path)}...")
        self.root.update()

        try:
            self.datalog = parse_dlz_file(path)
            self._display_datalog()
        except Exception as e:
            messagebox.showerror("Error", f"Could not parse file: {e}")

    def _load_sample_datalog(self):
        self.sbar.config(text="Generating sample drag pass datalog...")
        self.root.update()
        self.datalog = generate_sample_datalog("drag_pass")
        self._display_datalog()

    def _display_datalog(self):
        dl = self.datalog
        if not dl:
            return

        info = f"File: {dl.filename}  |  Records: {len(dl.records)}  |  Duration: {dl.duration_seconds:.1f}s  |  Max RPM: {dl.max_rpm:.0f}"
        if dl.parse_errors:
            info += f"\n⚠ Notes: {'; '.join(dl.parse_errors)}"
        self.dl_info.config(text=info, fg=C["text"])

        self.analysis = dl.get_full_analysis()
        analysis_text = self.agent.analyze_datalog(self.analysis)

        self.dl_text.delete("1.0", tk.END)
        self.dl_text.insert(tk.END, analysis_text)
        self.sbar.config(text=f"Datalog loaded: {len(dl.records)} records analyzed")

    # ═══════════════════════════════════════════════════
    # TAB 3: Time Slips
    # ═══════════════════════════════════════════════════
    def _build_timeslip(self, parent):
        inner = self._scrollable(parent)

        top = tk.Frame(inner, bg=C["bg"])
        top.pack(fill=tk.X, padx=16, pady=8)
        self._label(top, "Enter your drag strip time slip data. Add multiple runs for consistency analysis.",
                   fg=C["dim"]).pack(anchor=tk.W)

        self._section(inner, "TIME SLIP ENTRY")
        tf = self._frame(inner)
        tf.columnconfigure(0, minsize=220)
        r = 0
        self._field_row(tf, "Reaction Time (s)", "ts_rt", "0.000", r, width=10); r+=1
        self._field_row(tf, "60-Foot (s)", "ts_60", "0.000", r, width=10); r+=1
        self._field_row(tf, "330-Foot (s)", "ts_330", "0.000", r, width=10); r+=1
        self._field_row(tf, "1/8 Mile ET (s)", "ts_8et", "0.000", r, width=10); r+=1
        self._field_row(tf, "1/8 Mile MPH", "ts_8mph", "0.0", r, width=10); r+=1
        self._field_row(tf, "1000-Foot (s)", "ts_1000", "0.000", r, width=10); r+=1
        self._field_row(tf, "1/4 Mile ET (s)", "ts_4et", "0.000", r, width=10); r+=1
        self._field_row(tf, "1/4 Mile MPH", "ts_4mph", "0.0", r, width=10); r+=1

        self._section(inner, "CONDITIONS")
        cf = self._frame(inner)
        cf.columnconfigure(0, minsize=220)
        r = 0
        self._field_row(cf, "Temperature (°F)", "ts_temp", "75", r, width=8); r+=1
        self._field_row(cf, "Humidity (%)", "ts_hum", "50", r, width=8); r+=1
        self._field_row(cf, "Barometer (inHg)", "ts_baro", "29.92", r, width=8); r+=1
        self._field_row(cf, "Tire Pressure (PSI)", "ts_tire_psi", "14", r, width=8); r+=1
        self._field_row(cf, "Launch RPM", "ts_launch_rpm", "0", r, width=8); r+=1
        self._field_row(cf, "Notes", "ts_notes", "", r, width=40); r+=1

        bf = tk.Frame(inner, bg=C["bg"])
        bf.pack(fill=tk.X, padx=16, pady=8)
        self._btn(bf, "➕ Add Time Slip", self._add_timeslip, accent=True).pack(side=tk.LEFT)
        self._btn(bf, "🗑️ Clear All", self._clear_timeslips).pack(side=tk.LEFT, padx=8)

        self._section(inner, "SAVED TIME SLIPS")
        self.ts_listbox = tk.Listbox(inner, bg=C["card"], fg=C["text"], font=("Consolas", 10),
                                     height=8, selectbackground=C["red"], relief=tk.FLAT)
        self.ts_listbox.pack(fill=tk.X, padx=20, pady=8)
        self._refresh_ts_list()

        self._section(inner, "TIME SLIP ANALYSIS")
        self.ts_analysis_text = scrolledtext.ScrolledText(inner, width=90, height=12,
                                                          bg=C["card"], fg=C["text"],
                                                          font=("Consolas", 10), relief=tk.FLAT, wrap=tk.WORD)
        self.ts_analysis_text.pack(fill=tk.X, padx=16, pady=(0, 12))

    def _add_timeslip(self):
        try:
            ts = TimeSlipData()
            ts.reaction_time = float(self.vars.get("ts_rt", tk.StringVar()).get() or 0)
            ts.ft_60 = float(self.vars.get("ts_60", tk.StringVar()).get() or 0)
            ts.ft_330 = float(self.vars.get("ts_330", tk.StringVar()).get() or 0)
            ts.eighth_et = float(self.vars.get("ts_8et", tk.StringVar()).get() or 0)
            ts.eighth_mph = float(self.vars.get("ts_8mph", tk.StringVar()).get() or 0)
            ts.ft_1000 = float(self.vars.get("ts_1000", tk.StringVar()).get() or 0)
            ts.quarter_et = float(self.vars.get("ts_4et", tk.StringVar()).get() or 0)
            ts.quarter_mph = float(self.vars.get("ts_4mph", tk.StringVar()).get() or 0)
            ts.temperature_f = float(self.vars.get("ts_temp", tk.StringVar()).get() or 75)
            ts.humidity_pct = float(self.vars.get("ts_hum", tk.StringVar()).get() or 50)
            ts.barometer_inhg = float(self.vars.get("ts_baro", tk.StringVar()).get() or 29.92)
            ts.tire_pressure_psi = float(self.vars.get("ts_tire_psi", tk.StringVar()).get() or 14)
            ts.launch_rpm = int(float(self.vars.get("ts_launch_rpm", tk.StringVar()).get() or 0))
            ts.notes = self.vars.get("ts_notes", tk.StringVar()).get()
            ts.date = datetime.now().strftime("%Y-%m-%d")

            self.time_slips.append(ts)
            self._refresh_ts_list()
            self._analyze_timeslips()
            self._save_timeslips()
            self.sbar.config(text=f"Time slip #{len(self.time_slips)} added")
        except Exception as e:
            messagebox.showerror("Error", f"Invalid time slip data: {e}")

    def _clear_timeslips(self):
        if messagebox.askyesno("Confirm", "Clear all time slips?"):
            self.time_slips = []
            self._refresh_ts_list()
            self.ts_analysis_text.delete("1.0", tk.END)

    def _refresh_ts_list(self):
        self.ts_listbox.delete(0, tk.END)
        for i, ts in enumerate(self.time_slips):
            et = f"{ts.quarter_et:.3f}s" if ts.quarter_et > 0 else f"1/8: {ts.eighth_et:.3f}s"
            mph = f"@ {ts.quarter_mph:.1f}" if ts.quarter_mph > 0 else f"@ {ts.eighth_mph:.1f}"
            self.ts_listbox.insert(tk.END, f"  #{i+1}  {et} {mph} MPH  |  60ft: {ts.ft_60:.3f}s  |  RT: {ts.reaction_time:.3f}")

    def _analyze_timeslips(self):
        self.ts_analysis_text.delete("1.0", tk.END)
        for i, ts in enumerate(self.time_slips):
            result = self.agent.analyze_time_slip(ts.to_dict(), self.spec.to_dict())
            self.ts_analysis_text.insert(tk.END, f"--- Run #{i+1} ---\n{result}\n\n")

    def _save_timeslips(self):
        path = os.path.join(self.data_dir, "time_slips.json")
        with open(path, "w") as f:
            json.dump([ts.to_dict() for ts in self.time_slips], f, indent=2)

    # ═══════════════════════════════════════════════════
    # TAB 4: Analysis & Recommendations
    # ═══════════════════════════════════════════════════
    def _build_analysis(self, parent):
        top = tk.Frame(parent, bg=C["bg"])
        top.pack(fill=tk.X, padx=16, pady=8)
        self._label(top, "Run comprehensive analysis combining datalog, time slips, and vehicle specs.",
                   fg=C["dim"]).pack(anchor=tk.W)

        bf = tk.Frame(parent, bg=C["bg"])
        bf.pack(fill=tk.X, padx=16, pady=8)
        self._btn(bf, "🔍  Run Full Analysis", self._run_analysis, accent=True).pack(side=tk.LEFT)
        self._btn(bf, "📄  Export Report (.txt)", self._export_report).pack(side=tk.LEFT, padx=8)
        self._btn(bf, "📋  Export Config (.json)", self._export_config).pack(side=tk.LEFT, padx=4)

        self.analysis_text = scrolledtext.ScrolledText(parent, width=100, height=40,
                                                        bg=C["card"], fg=C["text"],
                                                        font=("Consolas", 10),
                                                        insertbackground=C["text"],
                                                        relief=tk.FLAT, wrap=tk.WORD)
        self.analysis_text.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))
        self.analysis_text.insert(tk.END,
            "Click 'Run Full Analysis' to generate tuning recommendations.\n\n"
            "For best results, provide:\n"
            "  1. Vehicle specs (Vehicle Setup tab)\n"
            "  2. A datalog from a drag strip pass (Datalog tab)\n"
            "  3. One or more time slips (Time Slips tab)\n\n"
            "The analysis engine will:\n"
            "  • Analyze WOT air/fuel ratio for optimal power\n"
            "  • Check acceleration enrichment for clean launches\n"
            "  • Evaluate ignition timing for maximum ET improvement\n"
            "  • Assess 60-foot and incremental times\n"
            "  • Generate prioritized tuning recommendations\n")

    def _run_analysis(self):
        self.sbar.config(text="Running analysis...")
        self.root.update()

        self._save_vehicle()  # Ensure latest specs are saved

        gen = SniperConfigGenerator(self.spec)
        dl_analysis = self.analysis or {}
        self.recs = gen.analyze_and_recommend(dl_analysis, self.time_slips)

        # Generate report
        report = gen.generate_tuning_report(dl_analysis, self.time_slips)

        # Also get AI agent's comprehensive view
        ts_dicts = [ts.to_dict() for ts in self.time_slips]
        agent_analysis = self.agent.generate_comprehensive_analysis(dl_analysis, ts_dicts, self.spec.to_dict())

        self.analysis_text.delete("1.0", tk.END)
        self.analysis_text.insert(tk.END, report)
        self.analysis_text.insert(tk.END, "\n\n" + agent_analysis)

        self.sbar.config(text=f"Analysis complete: {len(self.recs)} recommendations generated")

    def _export_report(self):
        if not self.recs:
            messagebox.showwarning("No Data", "Run analysis first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save Tuning Report", defaultextension=".txt",
            filetypes=[("Text", "*.txt")],
            initialfile=f"tuning_report_{datetime.now():%Y%m%d}.txt")
        if path:
            content = self.analysis_text.get("1.0", tk.END)
            export_report_txt(content, path)
            self.sbar.config(text=f"Report exported: {path}")

    def _export_config(self):
        if not self.recs:
            messagebox.showwarning("No Data", "Run analysis first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save Config Parameters", defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=f"sniper_config_{datetime.now():%Y%m%d}.json")
        if path:
            gen = SniperConfigGenerator(self.spec)
            gen.recommendations = self.recs
            config = gen.generate_config_export()
            export_config_json(config, path)
            self.sbar.config(text=f"Config exported: {path}")

    # ═══════════════════════════════════════════════════
    # TAB 5: Tuning Chat
    # ═══════════════════════════════════════════════════
    def _build_chat(self, parent):
        top = tk.Frame(parent, bg=C["bg"])
        top.pack(fill=tk.X, padx=16, pady=8)
        self._label(top, "Ask the local tuning agent questions about your Sniper EFI setup.",
                   fg=C["dim"]).pack(anchor=tk.W)

        self.chat_display = scrolledtext.ScrolledText(parent, width=100, height=30,
                                                       bg=C["card"], fg=C["text"],
                                                       font=("Consolas", 10),
                                                       insertbackground=C["text"],
                                                       relief=tk.FLAT, wrap=tk.WORD,
                                                       state=tk.NORMAL)
        self.chat_display.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 4))

        self.chat_display.tag_configure("user", foreground=C["blue"], font=("Consolas", 10, "bold"))
        self.chat_display.tag_configure("agent", foreground=C["green"])
        self.chat_display.tag_configure("system", foreground=C["dim"])

        self.chat_display.insert(tk.END, "🔧 Sniper Drag Tuner - Local Tuning Agent\n", "system")
        self.chat_display.insert(tk.END, "─" * 50 + "\n", "system")
        self.chat_display.insert(tk.END, "Ask me about Holley Sniper EFI tuning for drag racing!\n", "system")
        self.chat_display.insert(tk.END, "Topics: AFR, timing, acceleration enrichment, launch, idle, learning\n\n", "system")

        # Quick question buttons
        qf = tk.Frame(parent, bg=C["bg"])
        qf.pack(fill=tk.X, padx=16, pady=4)
        quick_qs = [
            "What AFR for WOT?",
            "Fix lean hesitation",
            "Improve 60-foot",
            "Timing for drag racing",
            "AE tuning tips",
        ]
        for q in quick_qs:
            self._btn(qf, q, lambda q=q: self._ask_chat(q)).pack(side=tk.LEFT, padx=2)

        # Input
        inp_frame = tk.Frame(parent, bg=C["bg"])
        inp_frame.pack(fill=tk.X, padx=16, pady=(4, 12))
        self.chat_entry = tk.Entry(inp_frame, bg=C["input"], fg=C["text"],
                                   insertbackground=C["text"], font=(FONT, 11),
                                   relief=tk.FLAT)
        self.chat_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)
        self.chat_entry.bind("<Return>", lambda e: self._ask_chat())
        self._btn(inp_frame, "Send", lambda: self._ask_chat(), accent=True).pack(side=tk.RIGHT, padx=(8, 0))

    def _ask_chat(self, preset_q=None):
        question = preset_q or self.chat_entry.get().strip()
        if not question:
            return
        self.chat_entry.delete(0, tk.END)

        self.chat_display.insert(tk.END, f"\n🏁 You: {question}\n", "user")
        self.chat_display.see(tk.END)
        self.root.update()

        context = self.spec.to_dict()
        if self.analysis:
            context["datalog_analysis"] = {k: v for k, v in self.analysis.items() if k != "metadata"}

        response = self.agent.get_tuning_advice(question, context)
        self.chat_display.insert(tk.END, f"\n🔧 Agent: {response}\n", "agent")
        self.chat_display.see(tk.END)

    # ═══════════════════════════════════════════════════
    # TAB 6: Settings
    # ═══════════════════════════════════════════════════
    def _build_settings(self, parent):
        inner = self._scrollable(parent)

        self._section(inner, "LOCAL AI MODEL")
        mf = self._frame(inner)
        self._label(mf, "The expert system works without a model. An optional local LLM enhances chat quality.",
                   fg=C["dim"]).pack(anchor=tk.W, pady=(0, 8))

        bf = tk.Frame(mf, bg=mf.cget("bg"))
        bf.pack(fill=tk.X, pady=4)
        self._btn(bf, "📂  Select Model File (.gguf)", self._select_model).pack(side=tk.LEFT)
        self._btn(bf, "📋  Download Instructions", self._show_model_info).pack(side=tk.LEFT, padx=8)

        self.model_info_label = tk.Label(mf, text="No local LLM loaded (expert system active)",
                                         font=(FONT, 10), bg=mf.cget("bg"), fg=C["dim"])
        self.model_info_label.pack(anchor=tk.W, pady=8)

        # Available models
        models = ModelManager.list_available_models()
        if models:
            self._label(mf, "Found models:", bold=True).pack(anchor=tk.W, pady=(8, 4))
            for m in models:
                self._label(mf, f"  • {m['filename']} ({m['size_gb']:.1f} GB)", fg=C["text"]).pack(anchor=tk.W)

        self._section(inner, "DATA MANAGEMENT")
        df = self._frame(inner)
        self._btn(df, "📂  Open Data Folder", lambda: os.startfile(self.data_dir) if os.name == 'nt' else None).pack(
            side=tk.LEFT, pady=4)
        self._btn(df, "🗑️  Clear All Data", self._clear_data).pack(side=tk.LEFT, padx=8)

        self._section(inner, "ABOUT")
        af = self._frame(inner)
        about_text = (
            "Sniper Drag Tuner v1.0\n\n"
            "A local, offline tuning assistant for drag racers running\n"
            "Holley Sniper EFI systems. All analysis is performed locally.\n"
            "No internet or cloud APIs required.\n\n"
            "Features:\n"
            "  • Parse Holley Sniper .DLZ / .DL datalogs\n"
            "  • Analyze WOT fueling, AE, timing, and idle\n"
            "  • Time slip entry and incremental analysis\n"
            "  • AI-powered tuning recommendations\n"
            "  • Expert knowledge base for Sniper EFI\n"
            "  • Optional local LLM for enhanced chat\n"
            "  • Export tuning reports and config parameters\n\n"
            "Disclaimer: Always verify tuning changes with your Holley\n"
            "EFI software. Save backups before modifying your config."
        )
        tk.Label(af, text=about_text, font=(FONT, 10), bg=af.cget("bg"), fg=C["text"],
                justify=tk.LEFT, anchor=tk.W).pack(fill=tk.X)

    def _select_model(self):
        path = filedialog.askopenfilename(
            title="Select GGUF Model File",
            filetypes=[("GGUF Models", "*.gguf"), ("All Files", "*.*")],
            initialdir=ModelManager.get_model_dir())
        if path:
            self.sbar.config(text="Loading model... (this may take a minute)")
            self.root.update()
            try:
                self.agent = TuningAgent(model_path=path)
                if self.agent.llm_available:
                    self.model_info_label.config(text=f"✅ Model loaded: {os.path.basename(path)}", fg=C["green"])
                    self.status_lbl.config(text="● Expert + LLM Active", fg=C["green"])
                    self.sbar.config(text="Local LLM loaded successfully")
                else:
                    self.model_info_label.config(text="⚠ Could not load model", fg=C["orange"])
            except Exception as e:
                messagebox.showerror("Error", f"Could not load model: {e}")

    def _show_model_info(self):
        info = ModelManager.get_download_instructions()
        win = tk.Toplevel(self.root)
        win.title("Local Model Setup")
        win.geometry("600x500")
        win.configure(bg=C["bg"])
        text = scrolledtext.ScrolledText(win, bg=C["card"], fg=C["text"],
                                         font=("Consolas", 10), wrap=tk.WORD, relief=tk.FLAT)
        text.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        text.insert(tk.END, info)
        text.config(state=tk.DISABLED)

    def _clear_data(self):
        if messagebox.askyesno("Confirm", "Clear all saved data?"):
            for f in os.listdir(self.data_dir):
                try:
                    os.remove(os.path.join(self.data_dir, f))
                except:
                    pass
            self.sbar.config(text="All data cleared")

    # ─── State Management ─────────────────────────────
    def _save_state(self):
        try:
            path = os.path.join(self.data_dir, "vehicle_spec.json")
            with open(path, "w") as f:
                json.dump(self.spec.to_dict(), f, indent=2)
        except:
            pass

    def _load_state(self):
        try:
            path = os.path.join(self.data_dir, "vehicle_spec.json")
            if os.path.exists(path):
                with open(path) as f:
                    self.spec = VehicleSpec.from_dict(json.load(f))
        except:
            pass
        try:
            path = os.path.join(self.data_dir, "time_slips.json")
            if os.path.exists(path):
                with open(path) as f:
                    self.time_slips = [TimeSlipData.from_dict(d) for d in json.load(f)]
        except:
            pass

    def _check_for_models(self):
        models = ModelManager.list_available_models()
        if models:
            best = max(models, key=lambda m: m["size_gb"])
            try:
                self.agent = TuningAgent(model_path=best["path"])
                if self.agent.llm_available:
                    self.status_lbl.config(text=f"● Expert + LLM Active", fg=C["green"])
            except:
                pass

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = App()
    app.run()

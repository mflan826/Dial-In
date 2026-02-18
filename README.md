# 🏁 Dial-In

## Holley Sniper EFI Drag Racing Tuning Assistant

A Windows desktop application for drag racers running Holley Sniper EFI systems. Upload your datalogs, enter time slip data, and get AI-powered tuning recommendations — **all running locally on your machine** with no cloud APIs required.

---

## Features

### 📊 Datalog Analysis (.DLZ / .DL)
- Parse Holley Sniper EFI datalog files (compressed .DLZ and uncompressed .DL)
- Analyze WOT (Wide Open Throttle) air/fuel ratios for optimal power
- Detect lean spikes that could damage your engine
- Evaluate acceleration enrichment behavior for clean launches
- Assess ignition timing across RPM ranges
- Identify idle stability issues

### 🏎️ Time Slip Analysis
- Enter drag strip time slip data (reaction, 60ft, 330ft, 1/8, 1/4, MPH)
- Segment analysis (launch, 1st gear, 2nd gear, top end)
- 60-foot time quality assessment
- Estimated wheel horsepower from ET/weight
- Multi-run consistency tracking
- Weather condition logging

### 🚗 Vehicle Specification Profiling
Complete vehicle profiling including:
- **Engine**: Displacement, type, compression, cam specs (duration, lift, LSA)
- **Holley Sniper EFI**: Model (4150/4500/2300/QJet), HP rating, injector flow, fuel pressure
- **Ignition**: Type (HyperSpark, HEI, MSD), timing control status
- **Drivetrain**: Transmission, converter stall, gear ratio, tire size/type
- **Vehicle**: Year/make/model, race weight
- **Power adders**: Nitrous, forced induction

### 🔧 Expert Tuning Recommendations
- Prioritized recommendations sorted by impact and urgency
- WOT fueling optimization (base fuel table adjustments)
- Target AFR table settings for drag racing
- Acceleration enrichment tuning (the EFI "accelerator pump")
- Ignition timing optimization by RPM band
- Idle stability improvements
- Closed loop temperature settings for the strip
- Converter/cam mismatch detection
- Fuel type-specific guidance (E85, race gas)

### 💬 AI Tuning Chat
- Ask natural language questions about Sniper EFI tuning
- Built-in expert knowledge base covering:
  - Common Sniper EFI issues and solutions
  - AFR targets for all conditions
  - Timing ranges by cam profile
  - Drag racing-specific tips
  - Acceleration enrichment tuning methodology
- Optional local LLM enhancement (no internet required)

### 📄 Export
- Tuning reports (.txt) with complete analysis
- Config parameters (.json) for reference when using Holley software
- All data saved locally between sessions

---

## Installation

### Requirements
- **Windows 10/11** (also works on macOS/Linux with Python)
- **Python 3.10+** ([Download](https://www.python.org/downloads/))
  - ✅ Check "Add Python to PATH" during installation

### Quick Start
1. Download or extract the Sniper Drag Tuner folder
2. Double-click `Setup.bat` to install dependencies
3. Double-click `Start_Sniper_Drag_Tuner.bat` to launch

### Manual Setup
```bash
pip install llama-cpp-python
python sniper_drag_tuner.py
```

---

## Optional: Local LLM Support

The application works fully with its built-in expert system. For enhanced natural language chat, you can optionally download a local LLM model:

| Model | Size | RAM | Quality |
|-------|------|-----|---------|
| **TinyLlama 1.1B** (Recommended) | 700 MB | 2 GB | Good for tuning Q&A |
| **Phi-2 2.7B** | 1.8 GB | 4 GB | Better explanations |
| **Mistral 7B** | 4.4 GB | 8 GB | Best quality |

**To install:**
1. Download a `.gguf` file from [HuggingFace](https://huggingface.co/TheBloke)
2. Place it in the `models/` folder
3. In the app, go to **Settings > Select Model File**

---

## Vehicle Details Required

The following information improves tuning accuracy. Gather these before using the app:

### Engine
| Parameter | Where to Find | Why It Matters |
|-----------|---------------|----------------|
| Displacement (ci) | Engine build specs | Base fuel calculation |
| Compression ratio | Builder or measurement | Timing limits, fuel octane needs |
| Cam duration @.050" | Cam card | Base tune selection, idle tuning |
| Cam lift | Cam card | Airflow capacity |
| Cam LSA | Cam card | Idle quality, overlap |
| Idle vacuum (inHg) | Sniper handheld/gauge | Cam type classification |

### Holley Sniper EFI
| Parameter | Where to Find | Why It Matters |
|-----------|---------------|----------------|
| Model (4150/4500/2300) | Throttle body | Injector count and type |
| HP rating | Box/receipt | Flow capacity |
| Injector flow rate | Sniper software | Fuel delivery calculation |
| Fuel pressure | Gauge/Sniper display | Injector pulse width calc |
| Timing control Y/N | Sniper setup | Timing optimization available |
| Ignition type | Distributor | Timing signal type |

### Drivetrain
| Parameter | Where to Find | Why It Matters |
|-----------|---------------|----------------|
| Transmission type | Visual/receipts | Shift strategy |
| Converter stall RPM | Converter specs | Launch RPM matching |
| Rear gear ratio | Axle tag/measurement | RPM vs speed calculation |
| Tire diameter | Tire sidewall | Speed/RPM calculation |
| Tire type | Visual | Traction, pressure recommendations |

### Time Slip Fields
| Field | What It Tells Us |
|-------|-----------------|
| 60-foot | Launch quality (traction, converter, technique) |
| 330-foot | 1st gear acceleration |
| 1/8 mile ET + MPH | Mid-track performance |
| 1/4 mile ET + MPH | Overall performance, HP estimate |
| Weather conditions | Density altitude correction |

---

## How the DLZ Parser Works

Holley Sniper EFI systems record datalogs in two formats:
- **`.DLZ`** — Compressed datalog (zlib). Stored on the SD card.
- **`.DL`** — Uncompressed datalog. Created when .DLZ is opened in Holley software.

The parser:
1. Detects if the file is compressed (.DLZ) and decompresses it
2. Attempts text/CSV parsing (for exported datalogs)
3. Attempts binary format parsing (for native files)
4. Falls back to raw byte extraction if needed
5. Reports any parsing issues and suggests exporting from Holley software

**For best results:** Use the Holley EFI software to export your datalog as CSV before uploading.

---

## File Structure

```
sniper_tuner/
├── Start_Sniper_Drag_Tuner.bat    # Windows launcher
├── Setup.bat                       # Dependency installer
├── sniper_drag_tuner.py            # Main application GUI
├── dlz_parser.py                   # DLZ/DL datalog parser
├── config_generator.py             # Config & recommendation engine
├── tuning_agent.py                 # Local AI tuning agent
├── models/                         # Place .gguf models here
├── data/                           # Saved vehicle specs, time slips
├── exports/                        # Exported reports and configs
└── README.md                       # This file
```

---

## Disclaimer

This software provides tuning suggestions based on general EFI tuning principles and Holley Sniper EFI domain knowledge. **Always:**

- Save a backup of your Holley config file before making changes
- Make one change at a time and test
- Monitor for detonation/knock when adding timing
- Verify AFR with your wideband O2 sensor
- Use the Holley EFI software to apply changes to your ECU
- Consult a professional tuner for forced induction or nitrous applications

This tool does not directly modify your Sniper ECU. All changes must be applied through the official Holley EFI software.

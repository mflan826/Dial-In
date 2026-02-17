"""
Holley Sniper EFI .DLZ / .DL Datalog Parser

The DLZ format is a compressed version of the DL (datalog) format used by
Holley Sniper EFI systems. DLZ uses basic zlib compression.

The DL format is a binary file containing timestamped rows of sensor data
recorded by the ECU at configurable sample rates (1-100 Hz).

Key channels logged:
- RPM, MAP (kPa), TPS (%), Coolant Temp, IAT
- AFR (Air/Fuel Ratio), Target AFR, WBO2
- Fuel Flow (lb/hr), Injector Pulse Width
- Ignition Timing, Battery Voltage
- Closed Loop Compensation %, Learn %
- Acceleration Enrichment active flag
- Vehicle Speed, Gear
"""

import struct
import zlib
import csv
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import io


# Holley Sniper DL channel definitions
# These represent the data channels recorded in Sniper EFI datalogs
SNIPER_CHANNELS = {
    "timestamp_ms": {"unit": "ms", "desc": "Timestamp in milliseconds"},
    "rpm": {"unit": "RPM", "desc": "Engine RPM"},
    "map_kpa": {"unit": "kPa", "desc": "Manifold Absolute Pressure"},
    "tps_pct": {"unit": "%", "desc": "Throttle Position Sensor"},
    "coolant_temp_f": {"unit": "°F", "desc": "Engine Coolant Temperature"},
    "iat_f": {"unit": "°F", "desc": "Intake Air Temperature"},
    "afr": {"unit": ":1", "desc": "Air/Fuel Ratio (measured)"},
    "target_afr": {"unit": ":1", "desc": "Target Air/Fuel Ratio"},
    "fuel_flow_lbhr": {"unit": "lb/hr", "desc": "Fuel Flow Rate"},
    "inj_pw_ms": {"unit": "ms", "desc": "Injector Pulse Width"},
    "ign_timing_deg": {"unit": "°BTDC", "desc": "Ignition Timing"},
    "battery_v": {"unit": "V", "desc": "Battery Voltage"},
    "cl_comp_pct": {"unit": "%", "desc": "Closed Loop Compensation"},
    "learn_pct": {"unit": "%", "desc": "Learn Compensation"},
    "ae_active": {"unit": "bool", "desc": "Acceleration Enrichment Active"},
    "iac_counts": {"unit": "counts", "desc": "Idle Air Control Position"},
    "vss_mph": {"unit": "MPH", "desc": "Vehicle Speed"},
    "fuel_pressure_psi": {"unit": "PSI", "desc": "Fuel Pressure"},
    "cl_status": {"unit": "enum", "desc": "Closed Loop Status (0=Open, 1=Closed)"},
    "tps_roc": {"unit": "%/s", "desc": "TPS Rate of Change"},
    "map_roc": {"unit": "kPa/s", "desc": "MAP Rate of Change"},
}


class DatalogRecord:
    """Single timestamped record from a Sniper EFI datalog."""
    
    def __init__(self, data: Dict[str, float]):
        self.data = data
    
    def __getattr__(self, name):
        if name in self.__dict__.get('data', {}):
            return self.data[name]
        raise AttributeError(f"No channel '{name}'")
    
    def get(self, key, default=None):
        return self.data.get(key, default)


class SniperDatalog:
    """Parsed Holley Sniper EFI datalog with analysis capabilities."""
    
    def __init__(self):
        self.records: List[DatalogRecord] = []
        self.channels: List[str] = []
        self.sample_rate_hz: float = 10.0
        self.metadata: Dict = {}
        self.filename: str = ""
        self.parse_errors: List[str] = []
    
    @property
    def duration_seconds(self) -> float:
        if not self.records:
            return 0.0
        return len(self.records) / max(self.sample_rate_hz, 1)
    
    @property
    def max_rpm(self) -> float:
        return max((r.get("rpm", 0) for r in self.records), default=0)
    
    @property
    def max_tps(self) -> float:
        return max((r.get("tps_pct", 0) for r in self.records), default=0)
    
    def get_channel_data(self, channel: str) -> List[float]:
        return [r.get(channel, 0.0) for r in self.records]
    
    def get_wot_runs(self, tps_threshold: float = 85.0) -> List[Tuple[int, int]]:
        """Find Wide Open Throttle run segments."""
        runs = []
        in_wot = False
        start_idx = 0
        
        for i, rec in enumerate(self.records):
            tps = rec.get("tps_pct", 0)
            if tps >= tps_threshold and not in_wot:
                in_wot = True
                start_idx = i
            elif tps < tps_threshold and in_wot:
                in_wot = False
                if i - start_idx > 3:  # Min 3 samples
                    runs.append((start_idx, i))
        
        if in_wot and len(self.records) - start_idx > 3:
            runs.append((start_idx, len(self.records) - 1))
        
        return runs
    
    def analyze_wot_afr(self) -> Dict:
        """Analyze AFR during WOT conditions."""
        wot_runs = self.get_wot_runs()
        results = []
        
        for start, end in wot_runs:
            afr_values = [self.records[i].get("afr", 14.7) for i in range(start, end)]
            target_values = [self.records[i].get("target_afr", 12.8) for i in range(start, end)]
            rpm_values = [self.records[i].get("rpm", 0) for i in range(start, end)]
            
            if afr_values:
                results.append({
                    "start_idx": start,
                    "end_idx": end,
                    "avg_afr": sum(afr_values) / len(afr_values),
                    "min_afr": min(afr_values),
                    "max_afr": max(afr_values),
                    "avg_target": sum(target_values) / len(target_values),
                    "peak_rpm": max(rpm_values),
                    "afr_deviation": sum(abs(a - t) for a, t in zip(afr_values, target_values)) / len(afr_values),
                    "lean_spikes": sum(1 for a in afr_values if a > 14.0),
                    "rich_spots": sum(1 for a in afr_values if a < 11.5),
                })
        
        return {
            "wot_runs": results,
            "total_wot_runs": len(results),
            "overall_avg_afr": sum(r["avg_afr"] for r in results) / len(results) if results else 0,
        }
    
    def analyze_acceleration_enrichment(self) -> Dict:
        """Analyze acceleration enrichment behavior."""
        ae_events = []
        ae_active = False
        start_idx = 0
        
        for i, rec in enumerate(self.records):
            if rec.get("ae_active", 0) and not ae_active:
                ae_active = True
                start_idx = i
            elif not rec.get("ae_active", 0) and ae_active:
                ae_active = False
                ae_events.append({
                    "start": start_idx,
                    "end": i,
                    "duration_samples": i - start_idx,
                    "peak_tps_roc": max(self.records[j].get("tps_roc", 0) for j in range(start_idx, i)),
                    "afr_during": [self.records[j].get("afr", 14.7) for j in range(start_idx, min(i + 10, len(self.records)))],
                })
        
        lean_ae_events = 0
        rich_ae_events = 0
        for event in ae_events:
            avg_afr = sum(event["afr_during"]) / len(event["afr_during"]) if event["afr_during"] else 14.7
            if avg_afr > 14.0:
                lean_ae_events += 1
            elif avg_afr < 11.5:
                rich_ae_events += 1
        
        return {
            "total_ae_events": len(ae_events),
            "lean_ae_events": lean_ae_events,
            "rich_ae_events": rich_ae_events,
            "ae_events": ae_events[:20],  # Cap for display
        }
    
    def analyze_idle(self) -> Dict:
        """Analyze idle conditions."""
        idle_records = [r for r in self.records 
                       if r.get("rpm", 0) > 400 and r.get("rpm", 0) < 1200 
                       and r.get("tps_pct", 0) < 5]
        
        if not idle_records:
            return {"has_idle_data": False}
        
        rpms = [r.get("rpm", 0) for r in idle_records]
        afrs = [r.get("afr", 14.7) for r in idle_records]
        maps = [r.get("map_kpa", 0) for r in idle_records]
        
        return {
            "has_idle_data": True,
            "avg_rpm": sum(rpms) / len(rpms),
            "rpm_variance": max(rpms) - min(rpms),
            "avg_afr": sum(afrs) / len(afrs),
            "afr_variance": max(afrs) - min(afrs),
            "avg_map": sum(maps) / len(maps),
            "map_variance": max(maps) - min(maps),
            "idle_samples": len(idle_records),
        }
    
    def analyze_timing(self) -> Dict:
        """Analyze ignition timing data."""
        timing_data = [r.get("ign_timing_deg", 0) for r in self.records if r.get("rpm", 0) > 500]
        rpm_data = [r.get("rpm", 0) for r in self.records if r.get("rpm", 0) > 500]
        
        if not timing_data:
            return {"has_timing_data": False}
        
        # Find timing at different RPM ranges
        timing_by_rpm = {}
        for timing, rpm in zip(timing_data, rpm_data):
            rpm_band = (int(rpm) // 500) * 500
            if rpm_band not in timing_by_rpm:
                timing_by_rpm[rpm_band] = []
            timing_by_rpm[rpm_band].append(timing)
        
        timing_summary = {}
        for rpm_band, timings in timing_by_rpm.items():
            timing_summary[rpm_band] = {
                "avg": sum(timings) / len(timings),
                "min": min(timings),
                "max": max(timings),
            }
        
        return {
            "has_timing_data": True,
            "overall_avg": sum(timing_data) / len(timing_data),
            "overall_max": max(timing_data),
            "overall_min": min(timing_data),
            "by_rpm_band": timing_summary,
        }
    
    def get_full_analysis(self) -> Dict:
        """Run all analyses and return comprehensive results."""
        return {
            "file": self.filename,
            "duration_sec": self.duration_seconds,
            "sample_rate": self.sample_rate_hz,
            "total_records": len(self.records),
            "max_rpm": self.max_rpm,
            "max_tps": self.max_tps,
            "wot_analysis": self.analyze_wot_afr(),
            "ae_analysis": self.analyze_acceleration_enrichment(),
            "idle_analysis": self.analyze_idle(),
            "timing_analysis": self.analyze_timing(),
            "metadata": self.metadata,
        }
    
    def to_csv(self, filepath: str):
        """Export datalog to CSV for review."""
        if not self.records:
            return
        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.channels)
            writer.writeheader()
            for rec in self.records:
                writer.writerow(rec.data)


def parse_dlz_file(filepath: str) -> SniperDatalog:
    """
    Parse a Holley Sniper EFI .DLZ or .DL datalog file.
    
    DLZ files are zlib-compressed DL files. The DL format is a binary
    format with a header section followed by timestamped data rows.
    
    Since the exact binary format is proprietary, this parser handles
    both the native binary format and attempts CSV-like parsing for
    exported datalogs. For truly binary DLZ files that can't be parsed,
    it generates synthetic data based on typical Sniper log patterns
    to demonstrate the analysis pipeline.
    """
    datalog = SniperDatalog()
    datalog.filename = os.path.basename(filepath)
    
    try:
        with open(filepath, 'rb') as f:
            raw_data = f.read()
        
        # Try decompressing if DLZ
        decompressed = None
        if filepath.lower().endswith('.dlz'):
            try:
                decompressed = zlib.decompress(raw_data)
            except zlib.error:
                # Some DLZ files use different compression or are already DL
                try:
                    decompressed = zlib.decompress(raw_data, -15)  # Raw deflate
                except:
                    decompressed = raw_data
        else:
            decompressed = raw_data
        
        # Try to parse as text/CSV first (exported datalogs)
        try:
            text_data = decompressed.decode('utf-8', errors='replace')
            if ',' in text_data[:500] or '\t' in text_data[:500]:
                datalog = _parse_text_datalog(text_data, filepath)
                if datalog.records:
                    return datalog
        except:
            pass
        
        # Try binary parsing
        datalog = _parse_binary_datalog(decompressed, filepath)
        if datalog.records:
            return datalog
        
        # If we couldn't parse the format, note it and try to extract
        # whatever information we can from the raw bytes
        datalog.parse_errors.append(
            f"Could not fully parse proprietary DLZ format. "
            f"File size: {len(raw_data)} bytes. "
            f"For best results, export from Holley software as CSV."
        )
        datalog = _extract_from_raw(decompressed, filepath)
        
    except Exception as e:
        datalog.parse_errors.append(f"Error reading file: {str(e)}")
    
    return datalog


def _parse_text_datalog(text: str, filepath: str) -> SniperDatalog:
    """Parse text/CSV format datalog."""
    datalog = SniperDatalog()
    datalog.filename = os.path.basename(filepath)
    
    lines = text.strip().split('\n')
    if len(lines) < 2:
        return datalog
    
    # Detect delimiter
    header = lines[0]
    delimiter = ',' if ',' in header else '\t'
    
    columns = [c.strip().strip('"') for c in header.split(delimiter)]
    
    # Map common Holley column names to our internal names
    column_map = {
        'rpm': 'rpm', 'engine rpm': 'rpm', 'eng rpm': 'rpm',
        'map': 'map_kpa', 'map kpa': 'map_kpa', 'manifold pressure': 'map_kpa',
        'tps': 'tps_pct', 'tps %': 'tps_pct', 'throttle': 'tps_pct',
        'clt': 'coolant_temp_f', 'coolant': 'coolant_temp_f', 'ect': 'coolant_temp_f',
        'iat': 'iat_f', 'intake temp': 'iat_f',
        'afr': 'afr', 'air fuel': 'afr', 'wbo2': 'afr', 'a/f': 'afr',
        'target afr': 'target_afr', 'tgt afr': 'target_afr',
        'fuel flow': 'fuel_flow_lbhr', 'fuel': 'fuel_flow_lbhr',
        'pw': 'inj_pw_ms', 'pulse width': 'inj_pw_ms', 'injpw': 'inj_pw_ms',
        'timing': 'ign_timing_deg', 'spark': 'ign_timing_deg', 'ign timing': 'ign_timing_deg',
        'battery': 'battery_v', 'batt': 'battery_v', 'bat v': 'battery_v',
        'cl comp': 'cl_comp_pct', 'clc': 'cl_comp_pct',
        'learn': 'learn_pct',
        'ae': 'ae_active', 'accel enrich': 'ae_active',
        'iac': 'iac_counts',
        'speed': 'vss_mph', 'vss': 'vss_mph', 'mph': 'vss_mph',
        'fp': 'fuel_pressure_psi', 'fuel pres': 'fuel_pressure_psi',
        'time': 'timestamp_ms',
    }
    
    mapped_columns = []
    for col in columns:
        col_lower = col.lower().strip()
        mapped = column_map.get(col_lower, col_lower.replace(' ', '_'))
        mapped_columns.append(mapped)
    
    datalog.channels = mapped_columns
    
    for line in lines[1:]:
        values = line.split(delimiter)
        if len(values) != len(mapped_columns):
            continue
        
        record_data = {}
        for col_name, val in zip(mapped_columns, values):
            try:
                record_data[col_name] = float(val.strip().strip('"'))
            except ValueError:
                record_data[col_name] = 0.0
        
        datalog.records.append(DatalogRecord(record_data))
    
    return datalog


def _parse_binary_datalog(data: bytes, filepath: str) -> SniperDatalog:
    """
    Attempt to parse binary DL format.
    
    The Holley DL binary format typically starts with a header containing:
    - Magic bytes / version identifier
    - Channel count and definitions
    - Sample rate configuration
    Followed by packed binary data rows.
    """
    datalog = SniperDatalog()
    datalog.filename = os.path.basename(filepath)
    
    if len(data) < 64:
        return datalog
    
    # Look for recognizable patterns in the header
    # Holley DL files typically have identifiable signatures
    try:
        # Check for common header patterns
        # Version byte is often near the start
        header_candidates = []
        
        # Scan for float-like patterns that could be RPM, kPa, etc.
        offset = 0
        while offset < min(len(data), 256):
            try:
                val = struct.unpack_from('<f', data, offset)[0]
                if 0 < val < 10000:
                    header_candidates.append((offset, val))
            except:
                pass
            offset += 1
        
        # Try to find the data section
        # Look for repeating patterns that suggest data rows
        for start_offset in range(64, min(len(data), 512)):
            # Assume 4 bytes per channel, try different channel counts
            for num_channels in [12, 16, 20, 24, 28, 32]:
                row_size = num_channels * 4
                if start_offset + row_size * 10 > len(data):
                    continue
                
                # Read first few rows and check for reasonable values
                rows_valid = True
                test_rows = []
                for row_idx in range(10):
                    row_offset = start_offset + row_idx * row_size
                    row_vals = []
                    for ch in range(num_channels):
                        try:
                            val = struct.unpack_from('<f', data, row_offset + ch * 4)[0]
                            row_vals.append(val)
                        except:
                            rows_valid = False
                            break
                    
                    if not rows_valid:
                        break
                    
                    # Check if values are in reasonable ranges
                    # RPM: 0-8000, MAP: 10-250 kPa, TPS: 0-100%, AFR: 8-22
                    has_rpm_like = any(0 <= v <= 8000 for v in row_vals[:4])
                    has_map_like = any(10 <= v <= 250 for v in row_vals[:8])
                    
                    if has_rpm_like and has_map_like:
                        test_rows.append(row_vals)
                    else:
                        rows_valid = False
                        break
                
                if rows_valid and len(test_rows) >= 5:
                    # We found a plausible data section
                    channel_names = list(SNIPER_CHANNELS.keys())[:num_channels]
                    datalog.channels = channel_names
                    
                    total_rows = (len(data) - start_offset) // row_size
                    for row_idx in range(total_rows):
                        row_offset = start_offset + row_idx * row_size
                        if row_offset + row_size > len(data):
                            break
                        
                        record_data = {}
                        for ch_idx, ch_name in enumerate(channel_names):
                            try:
                                val = struct.unpack_from('<f', data, row_offset + ch_idx * 4)[0]
                                record_data[ch_name] = val
                            except:
                                record_data[ch_name] = 0.0
                        
                        datalog.records.append(DatalogRecord(record_data))
                    
                    if datalog.records:
                        return datalog
    except Exception as e:
        datalog.parse_errors.append(f"Binary parse attempt failed: {str(e)}")
    
    return datalog


def _extract_from_raw(data: bytes, filepath: str) -> SniperDatalog:
    """
    Last-resort extraction from raw binary data.
    Looks for any recognizable numeric patterns.
    """
    datalog = SniperDatalog()
    datalog.filename = os.path.basename(filepath)
    datalog.channels = list(SNIPER_CHANNELS.keys())
    
    # Try to extract any float sequences from the file
    floats_found = []
    for i in range(0, len(data) - 4, 4):
        try:
            val = struct.unpack_from('<f', data, i)[0]
            if -1000 < val < 10000 and val == val:  # Not NaN
                floats_found.append(val)
        except:
            pass
    
    if floats_found:
        datalog.metadata["raw_floats_found"] = len(floats_found)
        datalog.metadata["file_size_bytes"] = len(data)
    
    return datalog


def generate_sample_datalog(scenario: str = "drag_pass") -> SniperDatalog:
    """
    Generate a realistic sample Sniper EFI datalog for testing/demonstration.
    
    Scenarios:
    - drag_pass: A typical quarter-mile drag strip pass
    - street_cruise: Normal street driving
    - idle_tuning: Extended idle session
    """
    import random
    
    datalog = SniperDatalog()
    datalog.filename = f"sample_{scenario}.dl"
    datalog.channels = list(SNIPER_CHANNELS.keys())
    datalog.sample_rate_hz = 30  # 30 Hz PC logging
    
    if scenario == "drag_pass":
        # Simulate a drag pass: staging -> launch -> WOT pull -> shutdown
        # ~15 seconds total at 30 Hz = 450 samples
        
        random.seed(42)
        
        # Phase 1: Staging/idle (3 seconds, 90 samples)
        for i in range(90):
            t = i / 30.0
            rec = {
                "timestamp_ms": i * 33.33,
                "rpm": 850 + random.uniform(-30, 30),
                "map_kpa": 42 + random.uniform(-2, 2),
                "tps_pct": 2.5 + random.uniform(-0.5, 0.5),
                "coolant_temp_f": 185 + random.uniform(-1, 1),
                "iat_f": 95 + random.uniform(-2, 2),
                "afr": 13.8 + random.uniform(-0.3, 0.3),
                "target_afr": 13.8,
                "fuel_flow_lbhr": 8.5 + random.uniform(-0.5, 0.5),
                "inj_pw_ms": 3.2 + random.uniform(-0.2, 0.2),
                "ign_timing_deg": 18 + random.uniform(-1, 1),
                "battery_v": 14.1 + random.uniform(-0.1, 0.1),
                "cl_comp_pct": 2 + random.uniform(-1, 1),
                "learn_pct": 1.5,
                "ae_active": 0,
                "iac_counts": 15 + random.uniform(-2, 2),
                "vss_mph": 0,
                "fuel_pressure_psi": 58 + random.uniform(-0.5, 0.5),
                "cl_status": 1,
                "tps_roc": random.uniform(-1, 1),
                "map_roc": random.uniform(-1, 1),
            }
            datalog.records.append(DatalogRecord(rec))
        
        # Phase 2: Launch + WOT pull (10 seconds, 300 samples)
        for i in range(300):
            t = i / 30.0
            progress = i / 300.0
            
            # RPM ramps up with shift points
            if progress < 0.02:  # Launch
                rpm = 4500 + progress * 50000  # Quick rev from staging
                gear = 1
            elif progress < 0.25:  # 1st gear
                rpm = 4500 + (progress - 0.02) * 12000
                gear = 1
            elif progress < 0.27:  # 1-2 shift
                rpm = 6800 - (progress - 0.25) * 15000
                gear = 2
            elif progress < 0.55:  # 2nd gear
                rpm = 4300 + (progress - 0.27) * 9000
                gear = 2
            elif progress < 0.57:  # 2-3 shift
                rpm = 6500 - (progress - 0.55) * 12000
                gear = 3
            elif progress < 0.85:  # 3rd gear
                rpm = 4100 + (progress - 0.57) * 8500
                gear = 3
            else:  # 3-4 shift and top
                rpm = 6300 - (progress - 0.85) * 5000 if progress < 0.87 else 5200 + (progress - 0.87) * 6000
                gear = 4
            
            rpm = max(3500, min(7000, rpm)) + random.uniform(-50, 50)
            
            speed = min(130, 10 + progress * 140)
            
            # AFR should be rich under WOT (~12.5-12.8 target)
            # Add some realistic lean spikes during shifts
            if 0.25 <= progress <= 0.27 or 0.55 <= progress <= 0.57:
                afr = 14.5 + random.uniform(-0.5, 1.5)  # Lean during shift
            else:
                afr = 12.6 + random.uniform(-0.4, 0.6)  # Slightly lean of target
            
            tps = 95 + random.uniform(-3, 5)
            if 0.25 <= progress <= 0.27 or 0.55 <= progress <= 0.57:
                tps = 30 + random.uniform(-10, 10)  # TPS drop during shift
            
            rec = {
                "timestamp_ms": (90 + i) * 33.33,
                "rpm": rpm,
                "map_kpa": 95 + random.uniform(-3, 5),  # Near atmospheric under WOT
                "tps_pct": min(100, tps),
                "coolant_temp_f": 188 + progress * 5 + random.uniform(-1, 1),
                "iat_f": 98 + progress * 8 + random.uniform(-2, 2),
                "afr": afr,
                "target_afr": 12.8,
                "fuel_flow_lbhr": 45 + rpm / 200 + random.uniform(-2, 2),
                "inj_pw_ms": 12 + rpm / 1500 + random.uniform(-0.5, 0.5),
                "ign_timing_deg": 32 - (rpm / 1000) + random.uniform(-1, 1),
                "battery_v": 13.8 + random.uniform(-0.2, 0.2),
                "cl_comp_pct": 0,  # Open loop at WOT
                "learn_pct": 0,
                "ae_active": 1 if i < 5 else 0,
                "iac_counts": 0,
                "vss_mph": speed + random.uniform(-1, 1),
                "fuel_pressure_psi": 57 + random.uniform(-1, 1),
                "cl_status": 0,  # Open loop
                "tps_roc": random.uniform(0, 5) if i < 5 else random.uniform(-2, 2),
                "map_roc": random.uniform(0, 10) if i < 5 else random.uniform(-3, 3),
            }
            datalog.records.append(DatalogRecord(rec))
        
        # Phase 3: Shutdown/coast (2 seconds, 60 samples)
        for i in range(60):
            t = i / 30.0
            progress = i / 60.0
            
            rec = {
                "timestamp_ms": (390 + i) * 33.33,
                "rpm": 6000 - progress * 4000 + random.uniform(-100, 100),
                "map_kpa": 95 - progress * 50 + random.uniform(-3, 3),
                "tps_pct": 5 + random.uniform(-2, 2),
                "coolant_temp_f": 193 + random.uniform(-1, 1),
                "iat_f": 106 + random.uniform(-2, 2),
                "afr": 15.5 + progress * 2 + random.uniform(-1, 1),  # Lean on decel
                "target_afr": 14.7,
                "fuel_flow_lbhr": 5 + random.uniform(-1, 1),
                "inj_pw_ms": 2 + random.uniform(-0.3, 0.3),
                "ign_timing_deg": 20 + random.uniform(-2, 2),
                "battery_v": 14.0 + random.uniform(-0.1, 0.1),
                "cl_comp_pct": 3 + random.uniform(-1, 1),
                "learn_pct": 1.5,
                "ae_active": 0,
                "iac_counts": 12 + random.uniform(-2, 2),
                "vss_mph": 120 - progress * 60 + random.uniform(-2, 2),
                "fuel_pressure_psi": 58 + random.uniform(-0.5, 0.5),
                "cl_status": 1,
                "tps_roc": random.uniform(-5, 0),
                "map_roc": random.uniform(-5, 0),
            }
            datalog.records.append(DatalogRecord(rec))
    
    datalog.metadata = {
        "scenario": scenario,
        "generated": True,
        "description": f"Sample {scenario} datalog for demonstration",
    }
    
    return datalog

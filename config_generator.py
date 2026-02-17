"""
Holley Sniper EFI Configuration Generator

Generates tuning recommendations and .sniper config file parameters
based on datalog analysis, time slip data, and vehicle specifications.

The .sniper file is a binary configuration file format used by the Holley
Sniper EFI system. It contains all tuning parameters including:
- Engine parameters (displacement, injector specs, etc.)
- Base fuel table (RPM vs MAP, values in lb/hr)
- Target AFR table (RPM vs MAP)
- Ignition timing table (RPM vs MAP)
- Acceleration enrichment parameters
- Startup/warmup enrichment tables
- Closed loop / learn parameters
- Rev limiter / safety settings
- Idle control parameters

Since modifying proprietary binary files requires the Holley software,
this module generates human-readable tuning recommendations and exports
parameter changes in a format that can be manually applied.
"""

import json
import os
from typing import Dict, List, Optional
from datetime import datetime


# Standard Sniper base fuel table dimensions
FUEL_TABLE_RPM_AXIS = [500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000, 6500, 7000]
FUEL_TABLE_MAP_AXIS = [20, 30, 40, 50, 60, 70, 80, 90, 100, 110]  # kPa

# Standard target AFR ranges for drag racing
DRAG_RACING_AFR_TARGETS = {
    "idle": 13.5,      # Slightly rich for stability
    "cruise": 14.2,    # Lean cruise
    "light_accel": 13.2,
    "wot": 12.5,       # Rich for power & safety
    "wot_boost": 11.8, # Extra rich if boosted
}

# Timing ranges for common V8 combos
TIMING_RANGES = {
    "stock_mild": {"idle": 18, "cruise": 34, "wot": 32},
    "street_strip": {"idle": 16, "cruise": 36, "wot": 34},
    "race": {"idle": 14, "cruise": 38, "wot": 36},
}


class VehicleSpec:
    """Vehicle and engine specifications required for tuning."""
    
    def __init__(self):
        # Engine specs
        self.engine_displacement_ci: int = 350
        self.engine_type: str = "SBC"  # SBC, BBC, SBF, BBF, LS, etc.
        self.cylinder_count: int = 8
        self.compression_ratio: float = 9.5
        self.cam_type: str = "stock_mild"  # stock_mild, street_strip, race
        self.cam_duration_intake: int = 210  # @ .050"
        self.cam_duration_exhaust: int = 218
        self.cam_lift_intake: float = 0.480
        self.cam_lift_exhaust: float = 0.480
        self.cam_lsa: int = 112  # Lobe Separation Angle
        self.idle_vacuum_inhg: float = 14.0
        self.has_timing_control: bool = True
        self.ignition_type: str = "hyperspark"  # hyperspark, hei, msd, points
        self.fuel_type: str = "pump_93"  # pump_87, pump_91, pump_93, e85, race
        
        # Sniper EFI specs
        self.sniper_model: str = "4150"  # 4150, 4500, 2300, quadrajet
        self.sniper_flow_hp: int = 650    # 550, 650, 800, 1250
        self.injector_flow_lbhr: float = 36.0
        self.fuel_pressure_psi: float = 58.5
        self.has_wideband_o2: bool = True
        
        # Drivetrain
        self.transmission_type: str = "auto"  # auto, manual
        self.transmission_model: str = "TH400"
        self.converter_stall: int = 2500
        self.rear_gear_ratio: float = 3.73
        self.tire_diameter_in: float = 28.0
        self.tire_type: str = "drag_radial"  # street, drag_radial, slick
        
        # Vehicle
        self.vehicle_weight_lbs: int = 3400
        self.vehicle_year: int = 1969
        self.vehicle_make: str = "Chevrolet"
        self.vehicle_model: str = "Camaro"
        
        # Performance goals
        self.target_et: float = 0.0  # Desired ET (0 = unset)
        self.current_best_et: float = 0.0
        self.use_nitrous: bool = False
        self.nitrous_hp: int = 0
        self.use_boost: bool = False
        self.boost_psi: float = 0.0
    
    def to_dict(self) -> Dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'VehicleSpec':
        spec = cls()
        for k, v in data.items():
            if hasattr(spec, k):
                setattr(spec, k, v)
        return spec
    
    def estimated_hp(self) -> float:
        """Rough HP estimate based on specs."""
        base_hp_per_ci = 1.0  # Stock
        if self.cam_type == "street_strip":
            base_hp_per_ci = 1.3
        elif self.cam_type == "race":
            base_hp_per_ci = 1.5
        
        hp = self.engine_displacement_ci * base_hp_per_ci
        
        if self.compression_ratio > 10.5:
            hp *= 1.05
        
        if self.use_nitrous:
            hp += self.nitrous_hp
        
        if self.use_boost:
            hp *= (1 + self.boost_psi * 0.06)
        
        return hp
    
    def cam_profile_desc(self) -> str:
        return (f"{self.cam_duration_intake}°/{self.cam_duration_exhaust}° @ .050\", "
                f".{int(self.cam_lift_intake*1000)}/{int(self.cam_lift_exhaust*1000)} lift, "
                f"{self.cam_lsa}° LSA")


class TimeSlipData:
    """Drag strip time slip data."""
    
    def __init__(self):
        self.date: str = ""
        self.track_name: str = ""
        self.lane: str = ""  # left/right
        self.reaction_time: float = 0.0
        self.ft_60: float = 0.0
        self.ft_330: float = 0.0
        self.eighth_et: float = 0.0
        self.eighth_mph: float = 0.0
        self.ft_1000: float = 0.0
        self.quarter_et: float = 0.0
        self.quarter_mph: float = 0.0
        self.dial_in: float = 0.0
        
        # Weather conditions
        self.temperature_f: float = 75.0
        self.humidity_pct: float = 50.0
        self.barometer_inhg: float = 29.92
        self.density_altitude_ft: float = 0.0
        self.wind_mph: float = 0.0
        self.wind_direction: str = ""  # head, tail, cross
        
        # Notes
        self.notes: str = ""
        self.tire_pressure_psi: float = 0.0
        self.launch_rpm: int = 0
    
    def to_dict(self) -> Dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TimeSlipData':
        ts = cls()
        for k, v in data.items():
            if hasattr(ts, k):
                setattr(ts, k, v)
        return ts
    
    def calculated_hp(self, weight_lbs: float) -> float:
        """Estimate wheel HP from ET and weight using ET-HP formula."""
        if self.quarter_et <= 0 or weight_lbs <= 0:
            return 0
        # HP = Weight / (ET/5.825)^3
        return weight_lbs / ((self.quarter_et / 5.825) ** 3)
    
    def predicted_quarter_from_eighth(self) -> float:
        """Predict quarter-mile ET from eighth-mile ET."""
        if self.eighth_et <= 0:
            return 0
        # Common conversion: 1/4 mile ET ≈ 1/8 mile ET × 1.5455
        return self.eighth_et * 1.5455
    
    def sixty_foot_quality(self) -> str:
        """Assess 60-foot time quality."""
        if self.ft_60 <= 0:
            return "N/A"
        if self.ft_60 < 1.4:
            return "Excellent (race-ready)"
        elif self.ft_60 < 1.6:
            return "Very Good"
        elif self.ft_60 < 1.8:
            return "Good"
        elif self.ft_60 < 2.0:
            return "Average"
        elif self.ft_60 < 2.2:
            return "Below Average - traction/launch issue"
        else:
            return "Poor - significant traction/launch problems"


class TuningRecommendation:
    """A specific tuning recommendation."""
    
    def __init__(self, category: str, parameter: str, current_value: str,
                 recommended_value: str, reason: str, priority: int = 5,
                 impact: str = "medium"):
        self.category = category
        self.parameter = parameter
        self.current_value = current_value
        self.recommended_value = recommended_value
        self.reason = reason
        self.priority = priority  # 1=critical, 10=nice-to-have
        self.impact = impact  # high, medium, low
    
    def to_dict(self) -> Dict:
        return self.__dict__


class SniperConfigGenerator:
    """
    Generates tuning recommendations and config parameters
    based on analysis of datalogs, time slips, and vehicle specs.
    """
    
    def __init__(self, vehicle_spec: VehicleSpec):
        self.spec = vehicle_spec
        self.recommendations: List[TuningRecommendation] = []
    
    def analyze_and_recommend(self, datalog_analysis: Dict,
                               time_slips: List[TimeSlipData]) -> List[TuningRecommendation]:
        """Generate comprehensive tuning recommendations."""
        self.recommendations = []
        
        # Analyze WOT AFR
        self._analyze_wot_fueling(datalog_analysis)
        
        # Analyze acceleration enrichment
        self._analyze_ae(datalog_analysis)
        
        # Analyze idle
        self._analyze_idle(datalog_analysis)
        
        # Analyze timing
        self._analyze_timing(datalog_analysis)
        
        # Analyze time slips
        self._analyze_time_slips(time_slips)
        
        # Vehicle-specific recommendations
        self._vehicle_specific_recs()
        
        # Sort by priority
        self.recommendations.sort(key=lambda r: r.priority)
        
        return self.recommendations
    
    def _analyze_wot_fueling(self, analysis: Dict):
        """Analyze WOT fueling and recommend changes."""
        wot = analysis.get("wot_analysis", {})
        runs = wot.get("wot_runs", [])
        
        if not runs:
            self.recommendations.append(TuningRecommendation(
                "Data Quality", "WOT Data",
                "No WOT runs found", "Record a full-throttle pass",
                "Need WOT data to optimize fuel delivery for drag racing.",
                priority=1, impact="high"
            ))
            return
        
        for i, run in enumerate(runs):
            avg_afr = run.get("avg_afr", 14.7)
            target = DRAG_RACING_AFR_TARGETS["wot"]
            
            if self.spec.use_boost:
                target = DRAG_RACING_AFR_TARGETS["wot_boost"]
            
            if avg_afr > target + 0.5:
                self.recommendations.append(TuningRecommendation(
                    "WOT Fueling", f"Base Fuel Table (WOT Run #{i+1})",
                    f"Avg AFR: {avg_afr:.1f}",
                    f"Target: {target:.1f}",
                    f"WOT AFR is lean by {avg_afr - target:.1f} ratio points. "
                    f"This costs power and risks engine damage. Increase base fuel table values "
                    f"in the high-MAP/high-RPM cells by {int((avg_afr - target) * 5)}% to {int((avg_afr - target) * 8)}%.",
                    priority=1, impact="high"
                ))
            elif avg_afr < target - 0.8:
                self.recommendations.append(TuningRecommendation(
                    "WOT Fueling", f"Base Fuel Table (WOT Run #{i+1})",
                    f"Avg AFR: {avg_afr:.1f}",
                    f"Target: {target:.1f}",
                    f"WOT AFR is overly rich by {target - avg_afr:.1f} ratio points. "
                    f"Excess fuel kills power. Reduce base fuel table values in "
                    f"high-MAP/high-RPM cells by {int((target - avg_afr) * 4)}% to {int((target - avg_afr) * 6)}%.",
                    priority=2, impact="high"
                ))
            
            # Check for lean spikes
            if run.get("lean_spikes", 0) > 2:
                self.recommendations.append(TuningRecommendation(
                    "WOT Fueling", "Lean Spike Prevention",
                    f"{run['lean_spikes']} lean spikes detected",
                    "Zero lean spikes at WOT",
                    f"Lean spikes at WOT are dangerous. Add 5-10% fuel in the specific RPM "
                    f"cells where lean spikes occur. Also verify fuel pressure stability under load.",
                    priority=1, impact="high"
                ))
        
        # Target AFR table recommendation
        overall_avg = wot.get("overall_avg_afr", 14.7)
        ideal_wot_target = 12.5 if not self.spec.use_boost else 11.8
        
        self.recommendations.append(TuningRecommendation(
            "Target AFR Table", "WOT Target AFR",
            f"Current measured avg: {overall_avg:.1f}",
            f"Set WOT target to {ideal_wot_target}",
            f"For drag racing with {'boost' if self.spec.use_boost else 'NA'}, "
            f"a WOT target of {ideal_wot_target}:1 provides optimal power with safety margin. "
            f"Use Simple mode: set WOT to {ideal_wot_target}.",
            priority=2, impact="high"
        ))
    
    def _analyze_ae(self, analysis: Dict):
        """Analyze acceleration enrichment."""
        ae = analysis.get("ae_analysis", {})
        
        lean_events = ae.get("lean_ae_events", 0)
        rich_events = ae.get("rich_ae_events", 0)
        total = ae.get("total_ae_events", 0)
        
        if lean_events > 0:
            self.recommendations.append(TuningRecommendation(
                "Acceleration Enrichment", "AE vs TPS RoC",
                f"{lean_events} lean AE events",
                "Zero lean events during AE",
                "Lean stumble on throttle application hurts launch and shift recovery. "
                "Increase AE vs TPS Rate of Change values by 15-25% in the first 4-5 cells. "
                "This acts like increasing accelerator pump shot on a carb.",
                priority=2, impact="high"
            ))
        
        if rich_events > total * 0.5 and total > 3:
            self.recommendations.append(TuningRecommendation(
                "Acceleration Enrichment", "AE Reduction",
                f"{rich_events}/{total} rich AE events",
                "Balanced AE fueling",
                "Excessive AE enrichment causes rich bog on launch. "
                "Reduce AE vs TPS RoC values by 10-20% starting from the middle cells.",
                priority=3, impact="medium"
            ))
        
        # Blanking value recommendation for drag racing
        self.recommendations.append(TuningRecommendation(
            "Acceleration Enrichment", "TPS RoC Blanking",
            "Check current value",
            "Set to 7-10 for drag racing",
            "For drag strip use, the TPS RoC Blanking value should be 7-10. "
            "Too low (default 5) causes unwanted Open Loop transitions. "
            "Too high misses needed enrichment during quick throttle snaps.",
            priority=4, impact="medium"
        ))
    
    def _analyze_idle(self, analysis: Dict):
        """Analyze idle conditions."""
        idle = analysis.get("idle_analysis", {})
        
        if not idle.get("has_idle_data", False):
            return
        
        rpm_var = idle.get("rpm_variance", 0)
        if rpm_var > 150:
            self.recommendations.append(TuningRecommendation(
                "Idle", "Idle Stability",
                f"RPM variance: {rpm_var:.0f} RPM",
                "Variance < 80 RPM",
                "Unstable idle affects staging consistency and launch RPM reliability. "
                "Check for vacuum leaks, verify IAC counts (should be 3-20 at warm idle). "
                "Consider a fixed-orifice PCV valve to reduce MAP fluctuations.",
                priority=3, impact="medium"
            ))
        
        afr_var = idle.get("afr_variance", 0)
        if afr_var > 1.5:
            self.recommendations.append(TuningRecommendation(
                "Idle", "Idle AFR Stability",
                f"AFR variance: {afr_var:.1f}",
                "Variance < 0.8",
                "Wide AFR swings at idle indicate the base fuel table is far from the target "
                "and CLC is working overtime. Transfer Learning to Base, then smooth the table.",
                priority=3, impact="medium"
            ))
    
    def _analyze_timing(self, analysis: Dict):
        """Analyze ignition timing."""
        timing = analysis.get("timing_analysis", {})
        
        if not timing.get("has_timing_data", False):
            if self.spec.has_timing_control:
                self.recommendations.append(TuningRecommendation(
                    "Ignition Timing", "Timing Control",
                    "No timing data in log",
                    "Enable timing control",
                    "Timing control is one of the biggest performance gains available. "
                    "Enable it through the Sniper software with a proper timing sync procedure.",
                    priority=1, impact="high"
                ))
            return
        
        # Check timing at WOT RPM ranges
        by_rpm = timing.get("by_rpm_band", {})
        
        cam_timing = TIMING_RANGES.get(self.spec.cam_type, TIMING_RANGES["stock_mild"])
        
        for rpm_band, data in by_rpm.items():
            if rpm_band >= 3000:  # WOT relevant RPMs
                avg_timing = data.get("avg", 0)
                target = cam_timing["wot"]
                
                if avg_timing < target - 4:
                    self.recommendations.append(TuningRecommendation(
                        "Ignition Timing", f"Timing @ {rpm_band} RPM",
                        f"Avg: {avg_timing:.1f}° BTDC",
                        f"Target: ~{target}° BTDC",
                        f"Timing is conservative by {target - avg_timing:.1f}°. "
                        f"Adding timing at WOT typically gains significant ET. "
                        f"Add 2° at a time and monitor for knock. Use {self.spec.fuel_type} fuel.",
                        priority=2, impact="high"
                    ))
    
    def _analyze_time_slips(self, time_slips: List[TimeSlipData]):
        """Analyze time slip data for improvement areas."""
        if not time_slips:
            return
        
        best_slip = min(time_slips, key=lambda s: s.quarter_et if s.quarter_et > 0 else 999)
        
        if best_slip.quarter_et <= 0:
            return
        
        # 60-foot analysis
        quality = best_slip.sixty_foot_quality()
        if best_slip.ft_60 > 1.8:
            improvement = best_slip.ft_60 - 1.6
            et_gain = improvement * 2  # ~2:1 ratio
            self.recommendations.append(TuningRecommendation(
                "Launch/60-Foot", "60-Foot Time",
                f"{best_slip.ft_60:.3f}s ({quality})",
                f"Target: 1.5-1.7s",
                f"Improving your 60-foot from {best_slip.ft_60:.3f}s to ~1.6s could gain "
                f"~{et_gain:.2f}s in ET. Focus on: launch RPM, converter stall match, "
                f"tire pressure (try 12-16 PSI on drag radials), suspension setup.",
                priority=2, impact="high"
            ))
        
        # MPH vs ET analysis
        if best_slip.quarter_mph > 0:
            hp_estimate = best_slip.calculated_hp(self.spec.vehicle_weight_lbs)
            self.recommendations.append(TuningRecommendation(
                "Performance", "Estimated Wheel HP",
                f"ET: {best_slip.quarter_et:.3f}s @ {best_slip.quarter_mph:.1f} MPH",
                f"Est. WHP: {hp_estimate:.0f}",
                f"Your trap speed of {best_slip.quarter_mph:.1f} MPH at "
                f"{self.spec.vehicle_weight_lbs} lbs suggests ~{hp_estimate:.0f} WHP. "
                f"ET improvements will come from better launches and optimized fueling.",
                priority=5, impact="low"
            ))
        
        # Consistency analysis
        if len(time_slips) >= 3:
            ets = [s.quarter_et for s in time_slips if s.quarter_et > 0]
            if ets:
                variance = max(ets) - min(ets)
                if variance > 0.3:
                    self.recommendations.append(TuningRecommendation(
                        "Consistency", "ET Variance",
                        f"Spread: {variance:.3f}s over {len(ets)} runs",
                        "Variance < 0.15s",
                        f"ET varies by {variance:.3f}s. For bracket racing, consistency is key. "
                        f"Check: consistent staging depth, tire pressure, water temp at launch, "
                        f"and use the same throttle application technique every pass.",
                        priority=4, impact="medium"
                    ))
    
    def _vehicle_specific_recs(self):
        """Vehicle and setup-specific recommendations."""
        # Converter stall vs cam match
        if self.spec.cam_type == "street_strip" and self.spec.converter_stall < 2800:
            self.recommendations.append(TuningRecommendation(
                "Drivetrain", "Torque Converter",
                f"Stall: {self.spec.converter_stall} RPM",
                "2800-3500 RPM for street/strip cam",
                "Your cam profile suggests the engine makes peak torque above your converter "
                "stall speed. A higher-stall converter allows the engine to launch in its "
                "powerband, significantly improving 60-foot times.",
                priority=3, impact="high"
            ))
        
        # Closed loop temperature
        self.recommendations.append(TuningRecommendation(
            "Closed Loop", "CL Enable Temperature",
            "Default: 160°F",
            "Set to 120°F for drag racing",
            "At the drag strip, between runs the engine may cool below 160°F. "
            "Lowering the CL enable temp to 120°F ensures the system stays in "
            "Closed Loop between rounds, preventing Open Loop fueling surprises.",
            priority=3, impact="medium"
        ))
        
        # Fuel type specific
        if self.spec.fuel_type == "e85":
            self.recommendations.append(TuningRecommendation(
                "Fuel System", "E85 Fueling",
                f"Fuel type: {self.spec.fuel_type}",
                "Increase base fuel ~30% over gasoline",
                "E85 requires approximately 30% more fuel volume than gasoline. "
                "Ensure your injectors have sufficient flow capacity and increase "
                "base fuel table values accordingly. Target AFR for E85 at WOT: 9.8:1.",
                priority=1, impact="high"
            ))
    
    def generate_config_export(self) -> Dict:
        """Generate a config parameter export for the Sniper software."""
        config = {
            "metadata": {
                "generated_by": "Sniper Drag Tuner",
                "date": datetime.now().isoformat(),
                "vehicle": f"{self.spec.vehicle_year} {self.spec.vehicle_make} {self.spec.vehicle_model}",
                "engine": f"{self.spec.engine_displacement_ci}ci {self.spec.engine_type}",
            },
            "engine_parameters": {
                "displacement_ci": self.spec.engine_displacement_ci,
                "cylinder_count": self.spec.cylinder_count,
                "cam_type": self.spec.cam_type,
                "ignition_type": self.spec.ignition_type,
            },
            "target_afr_simple": {
                "idle": DRAG_RACING_AFR_TARGETS["idle"],
                "cruise": DRAG_RACING_AFR_TARGETS["cruise"],
                "wot": DRAG_RACING_AFR_TARGETS["wot_boost"] if self.spec.use_boost 
                       else DRAG_RACING_AFR_TARGETS["wot"],
            },
            "acceleration_enrichment": {
                "tps_roc_blanking": 8,
                "map_roc_blanking": 10,
                "note": "Values in this section should be applied via Holley EFI software",
            },
            "closed_loop": {
                "enable_temperature_f": 120,
                "cl_comp_limit_pct": 25,
                "learn_enabled": True,
                "learn_rate": 3,
            },
            "recommendations": [r.to_dict() for r in self.recommendations],
        }
        
        # Add timing recommendations if applicable
        if self.spec.has_timing_control:
            cam_timing = TIMING_RANGES.get(self.spec.cam_type, TIMING_RANGES["stock_mild"])
            config["timing_targets"] = {
                "idle_timing_btdc": cam_timing["idle"],
                "cruise_timing_btdc": cam_timing["cruise"],
                "wot_timing_btdc": cam_timing["wot"],
                "note": "These are starting points. Add/remove 2° at a time monitoring for knock.",
            }
        
        return config
    
    def generate_tuning_report(self, datalog_analysis: Dict,
                                time_slips: List[TimeSlipData]) -> str:
        """Generate a human-readable tuning report."""
        report = []
        report.append("=" * 70)
        report.append("HOLLEY SNIPER EFI DRAG RACING TUNING REPORT")
        report.append("=" * 70)
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        report.append("")
        
        # Vehicle info
        report.append("VEHICLE SPECIFICATIONS")
        report.append("-" * 40)
        report.append(f"Vehicle: {self.spec.vehicle_year} {self.spec.vehicle_make} {self.spec.vehicle_model}")
        report.append(f"Engine: {self.spec.engine_displacement_ci}ci {self.spec.engine_type}")
        report.append(f"Cam: {self.spec.cam_profile_desc()}")
        report.append(f"Sniper: {self.spec.sniper_model} ({self.spec.sniper_flow_hp}HP)")
        report.append(f"Trans: {self.spec.transmission_model} (Stall: {self.spec.converter_stall})")
        report.append(f"Gear: {self.spec.rear_gear_ratio} / Tire: {self.spec.tire_diameter_in}\"")
        report.append(f"Weight: {self.spec.vehicle_weight_lbs} lbs")
        report.append(f"Fuel: {self.spec.fuel_type}")
        report.append(f"Est. HP: {self.spec.estimated_hp():.0f}")
        report.append("")
        
        # Time slip summary
        if time_slips:
            report.append("TIME SLIP DATA")
            report.append("-" * 40)
            for i, ts in enumerate(time_slips):
                if ts.quarter_et > 0:
                    report.append(f"Run #{i+1}: {ts.quarter_et:.3f}s @ {ts.quarter_mph:.1f} MPH")
                    report.append(f"  60ft: {ts.ft_60:.3f}s | 1/8: {ts.eighth_et:.3f}s @ {ts.eighth_mph:.1f}")
                    report.append(f"  60ft Quality: {ts.sixty_foot_quality()}")
                elif ts.eighth_et > 0:
                    report.append(f"Run #{i+1}: 1/8 mile: {ts.eighth_et:.3f}s @ {ts.eighth_mph:.1f} MPH")
                    report.append(f"  60ft: {ts.ft_60:.3f}s")
                    pred = ts.predicted_quarter_from_eighth()
                    if pred > 0:
                        report.append(f"  Predicted 1/4: {pred:.3f}s")
            report.append("")
        
        # Datalog summary
        if datalog_analysis:
            report.append("DATALOG ANALYSIS")
            report.append("-" * 40)
            report.append(f"Duration: {datalog_analysis.get('duration_sec', 0):.1f}s")
            report.append(f"Max RPM: {datalog_analysis.get('max_rpm', 0):.0f}")
            report.append(f"Max TPS: {datalog_analysis.get('max_tps', 0):.0f}%")
            
            wot = datalog_analysis.get("wot_analysis", {})
            report.append(f"WOT Runs Found: {wot.get('total_wot_runs', 0)}")
            if wot.get("overall_avg_afr"):
                report.append(f"Avg WOT AFR: {wot['overall_avg_afr']:.1f}")
            report.append("")
        
        # Recommendations
        report.append("TUNING RECOMMENDATIONS")
        report.append("-" * 40)
        report.append("(Sorted by priority: 1=Critical, 10=Nice-to-have)")
        report.append("")
        
        for i, rec in enumerate(self.recommendations, 1):
            impact_icon = "🔴" if rec.impact == "high" else "🟡" if rec.impact == "medium" else "🟢"
            report.append(f"{i}. [{rec.category}] {rec.parameter}")
            report.append(f"   Priority: {rec.priority}/10 | Impact: {rec.impact.upper()}")
            report.append(f"   Current: {rec.current_value}")
            report.append(f"   Recommended: {rec.recommended_value}")
            report.append(f"   Reason: {rec.reason}")
            report.append("")
        
        report.append("=" * 70)
        report.append("IMPORTANT: Always make changes one at a time and test.")
        report.append("Save your current config before making any modifications.")
        report.append("Use 'Save As' in Holley software to create a backup.")
        report.append("=" * 70)
        
        return "\n".join(report)


def export_config_json(config: Dict, filepath: str):
    """Export config to JSON file."""
    with open(filepath, 'w') as f:
        json.dump(config, f, indent=2, default=str)


def export_report_txt(report: str, filepath: str):
    """Export tuning report to text file."""
    with open(filepath, 'w') as f:
        f.write(report)

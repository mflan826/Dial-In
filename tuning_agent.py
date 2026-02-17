"""
Local EFI Tuning Agent

This module implements a local AI tuning agent that analyzes Holley Sniper EFI
data and provides expert tuning recommendations. It uses a hybrid approach:

1. Rule-based expert system with domain-specific knowledge about EFI tuning
2. Statistical analysis of datalog patterns
3. Optional local LLM integration via llama-cpp-python for natural language
   interaction (requires downloading a GGUF model)

The agent does NOT require any cloud API calls - everything runs locally.
"""

import json
import os
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime

# Try to import llama-cpp-python for optional LLM support
try:
    from llama_cpp import Llama
    LLAMA_AVAILABLE = True
except ImportError:
    LLAMA_AVAILABLE = False


class EFIKnowledgeBase:
    """
    Domain-specific knowledge base for Holley Sniper EFI tuning.
    Encodes expert tuning rules gathered from Holley forums, technical
    bulletins, and professional tuner experience.
    """
    
    # AFR targets for different conditions
    AFR_RULES = {
        "idle_stock": {"target": 14.0, "range": (13.2, 14.7), "note": "Richer idle for stock cams"},
        "idle_cam": {"target": 13.5, "range": (12.8, 14.2), "note": "Big cams need richer idle"},
        "cruise": {"target": 14.5, "range": (14.0, 15.0), "note": "Lean cruise for economy"},
        "light_accel": {"target": 13.2, "range": (12.8, 13.8), "note": "Slightly rich for response"},
        "wot_na": {"target": 12.5, "range": (12.0, 13.0), "note": "WOT naturally aspirated"},
        "wot_nitrous": {"target": 11.8, "range": (11.2, 12.3), "note": "Richer for nitrous safety"},
        "wot_boost": {"target": 11.5, "range": (11.0, 12.0), "note": "Rich for boost safety"},
        "wot_e85": {"target": 9.8, "range": (9.0, 10.5), "note": "E85 stoich is ~9.8:1"},
    }
    
    # Timing rules by cam type and RPM range
    TIMING_RULES = {
        "stock_mild": {
            "idle": (16, 22, "Stock cams tolerate moderate idle timing"),
            "cruise_2k": (30, 36, "Good cruise economy range"),
            "cruise_3k": (32, 38, "Mid-range timing for cruise"),
            "wot_low": (28, 34, "WOT timing below 3500 RPM"),
            "wot_high": (30, 36, "WOT timing above 3500 RPM"),
        },
        "street_strip": {
            "idle": (14, 20, "Moderate cams - slightly less idle timing"),
            "cruise_2k": (32, 38, "Street/strip cruise"),
            "cruise_3k": (34, 40, "Mid-range for street/strip"),
            "wot_low": (30, 36, "WOT for street/strip low RPM"),
            "wot_high": (32, 38, "WOT for street/strip high RPM"),
        },
        "race": {
            "idle": (12, 18, "Race cams need less idle timing"),
            "cruise_2k": (34, 40, "Race cruise (rarely used)"),
            "cruise_3k": (36, 42, "Race mid-range"),
            "wot_low": (32, 38, "Race WOT low RPM"),
            "wot_high": (34, 40, "Race WOT high RPM"),
        },
    }
    
    # Common Sniper EFI issues and solutions
    COMMON_ISSUES = {
        "lean_hesitation": {
            "symptoms": ["hesitation on throttle tip-in", "stumble off idle", "lean spike after throttle"],
            "causes": [
                "Acceleration Enrichment too low",
                "Base fuel table too lean in transition cells",
                "TPS RoC Blanking value too high",
                "Vacuum leak",
            ],
            "solutions": [
                "Increase AE vs TPS RoC values by 15-25%",
                "Add 5-10% fuel in 30-60% TPS / 40-70 kPa cells",
                "Lower TPS RoC Blanking to 5-7",
                "Check all vacuum connections and intake gaskets",
            ],
        },
        "rich_bog": {
            "symptoms": ["bog on hard acceleration", "black smoke at WOT", "rich smell from exhaust"],
            "causes": [
                "Acceleration Enrichment too high",
                "Base fuel table too rich at WOT",
                "Target AFR too rich",
                "Fuel pressure too high",
            ],
            "solutions": [
                "Reduce AE vs TPS RoC values by 10-20%",
                "Reduce fuel in high-MAP/high-RPM cells by 5-10%",
                "Set WOT target AFR to 12.5-12.8",
                "Check fuel pressure regulator (should be 58-59 PSI)",
            ],
        },
        "unstable_idle": {
            "symptoms": ["hunting idle", "RPM fluctuates", "stalling"],
            "causes": [
                "IAC counts too high or too low",
                "Vacuum leak",
                "Spring-type PCV valve causing MAP fluctuation",
                "Base fuel table not well-learned in idle area",
            ],
            "solutions": [
                "IAC should be 3-20 at warm idle; adjust throttle blade",
                "Smoke test for vacuum leaks",
                "Use fixed-orifice PCV valve",
                "Transfer Learning to Base, then smooth table",
            ],
        },
        "poor_60ft": {
            "symptoms": ["slow 60-foot time", "spinning tires", "bog off line"],
            "causes": [
                "Wrong converter stall for cam",
                "Tire pressure too high",
                "Acceleration enrichment not matched",
                "Launch RPM not optimized",
                "Timing too aggressive causing tire spin",
            ],
            "solutions": [
                "Match converter stall to cam torque peak",
                "Run 10-16 PSI on drag radials, 8-12 on slicks",
                "Tune AE to eliminate any hesitation on launch",
                "Experiment with launch RPM in 200 RPM increments",
                "Reduce timing by 2-4° at launch RPM range",
            ],
        },
        "shift_lean_spike": {
            "symptoms": ["lean spike during gear changes", "AFR spikes above 15:1 during shifts"],
            "causes": [
                "Normal TPS closure during shift drops into Open Loop",
                "Base fuel table not tuned in decel/closed throttle area",
                "AE needs to fire on throttle re-application after shift",
            ],
            "solutions": [
                "Ensure base fuel table is well-tuned across all RPM ranges",
                "Set TPS RoC Blanking to 10-12 to stay in CL through shifts",
                "Add fuel in high-RPM / low-MAP cells for shift recovery",
            ],
        },
    }
    
    # Drag racing specific tips
    DRAG_TIPS = {
        "staging": "Stage shallow for maximum rollout. The ET clock starts when the front tire clears the stage beam.",
        "burnout": "Heat the tires to ~200°F surface temp. Sniper systems handle WOT burnouts well once tuned.",
        "launch_rpm": "Start with converter stall RPM + 500 and adjust in 200 RPM increments. Higher isn't always better.",
        "tire_pressure": "Drag radials: 12-18 PSI. Slicks: 8-12 PSI. Lower = more footprint = better 60ft (to a point).",
        "water_temp": "Launch at consistent water temp every pass. Between 160-180°F is ideal. Don't let it drop below CL enable temp.",
        "cl_temp": "Lower Closed Loop enable temperature to 120°F to prevent Open Loop surprises between rounds.",
        "timing_at_launch": "Consider pulling 2-4° timing at launch RPM to manage tire spin, especially on sticky tracks.",
        "shift_points": "Shift at peak HP RPM minus 200. Shifting too high wastes time in the powerband falloff.",
        "fuel_curve": "WOT fuel should be slightly rich of peak power (12.5-12.8:1). Safety first, tune from rich to lean.",
    }
    
    @classmethod
    def get_afr_recommendation(cls, condition: str, fuel_type: str = "pump_93") -> Dict:
        """Get AFR recommendation for a specific condition."""
        if fuel_type == "e85" and "wot" in condition:
            return cls.AFR_RULES.get("wot_e85", cls.AFR_RULES["wot_na"])
        return cls.AFR_RULES.get(condition, cls.AFR_RULES["wot_na"])
    
    @classmethod
    def diagnose_issue(cls, symptoms: List[str]) -> List[Dict]:
        """Match symptoms to known issues and return diagnoses."""
        diagnoses = []
        for issue_name, issue_data in cls.COMMON_ISSUES.items():
            match_count = 0
            for symptom in symptoms:
                symptom_lower = symptom.lower()
                for known_symptom in issue_data["symptoms"]:
                    if any(word in symptom_lower for word in known_symptom.lower().split()):
                        match_count += 1
                        break
            
            if match_count > 0:
                diagnoses.append({
                    "issue": issue_name,
                    "confidence": match_count / len(issue_data["symptoms"]),
                    "causes": issue_data["causes"],
                    "solutions": issue_data["solutions"],
                })
        
        diagnoses.sort(key=lambda d: d["confidence"], reverse=True)
        return diagnoses


class TuningAgent:
    """
    Local AI tuning agent that combines rule-based expert knowledge
    with optional LLM-powered natural language interaction.
    """
    
    def __init__(self, model_path: Optional[str] = None):
        self.kb = EFIKnowledgeBase()
        self.llm = None
        self.llm_available = False
        self.model_path = model_path
        self.conversation_history: List[Dict] = []
        
        # Try to load local LLM if path provided
        if model_path and os.path.exists(model_path) and LLAMA_AVAILABLE:
            try:
                self.llm = Llama(
                    model_path=model_path,
                    n_ctx=4096,
                    n_threads=4,
                    n_gpu_layers=0,  # CPU only by default
                    verbose=False,
                )
                self.llm_available = True
            except Exception as e:
                print(f"Could not load LLM: {e}")
                self.llm_available = False
    
    def analyze_datalog(self, analysis: Dict) -> str:
        """Provide expert analysis of a datalog."""
        findings = []
        
        # WOT analysis
        wot = analysis.get("wot_analysis", {})
        runs = wot.get("wot_runs", [])
        
        if runs:
            findings.append("=== WOT Analysis ===")
            for i, run in enumerate(runs):
                avg_afr = run.get("avg_afr", 0)
                target = 12.8  # Default WOT target
                deviation = abs(avg_afr - target)
                
                status = "GOOD" if deviation < 0.3 else "ATTENTION" if deviation < 0.8 else "CRITICAL"
                findings.append(f"WOT Run #{i+1}: AFR {avg_afr:.1f} (target {target}) - {status}")
                
                if run.get("lean_spikes", 0) > 0:
                    findings.append(f"  ⚠ {run['lean_spikes']} lean spikes detected - DANGEROUS")
                
                if run.get("rich_spots", 0) > 3:
                    findings.append(f"  ℹ {run['rich_spots']} rich points - losing power")
        else:
            findings.append("No WOT runs found in datalog. Need full-throttle data for drag tuning.")
        
        # AE analysis
        ae = analysis.get("ae_analysis", {})
        if ae.get("lean_ae_events", 0) > 0:
            findings.append(f"\n=== Acceleration Enrichment ===")
            findings.append(f"⚠ {ae['lean_ae_events']} lean events during throttle tip-in")
            findings.append("Action: Increase AE vs TPS RoC values")
        
        # Idle analysis
        idle = analysis.get("idle_analysis", {})
        if idle.get("has_idle_data"):
            findings.append(f"\n=== Idle Analysis ===")
            findings.append(f"Avg RPM: {idle.get('avg_rpm', 0):.0f} (variance: {idle.get('rpm_variance', 0):.0f})")
            findings.append(f"Avg AFR: {idle.get('avg_afr', 0):.1f} (variance: {idle.get('afr_variance', 0):.1f})")
            
            if idle.get("rpm_variance", 0) > 150:
                findings.append("⚠ Idle is unstable - check vacuum leaks, IAC, PCV")
        
        # Timing analysis
        timing = analysis.get("timing_analysis", {})
        if timing.get("has_timing_data"):
            findings.append(f"\n=== Timing Analysis ===")
            findings.append(f"Overall avg: {timing.get('overall_avg', 0):.1f}° BTDC")
            findings.append(f"Range: {timing.get('overall_min', 0):.1f}° to {timing.get('overall_max', 0):.1f}°")
        
        return "\n".join(findings)
    
    def analyze_time_slip(self, slip: Dict, vehicle: Dict) -> str:
        """Provide expert analysis of a time slip."""
        findings = []
        
        quarter_et = slip.get("quarter_et", 0)
        eighth_et = slip.get("eighth_et", 0)
        ft_60 = slip.get("ft_60", 0)
        quarter_mph = slip.get("quarter_mph", 0)
        weight = vehicle.get("vehicle_weight_lbs", 3400)
        
        findings.append("=== Time Slip Analysis ===")
        
        if quarter_et > 0:
            findings.append(f"Quarter Mile: {quarter_et:.3f}s @ {quarter_mph:.1f} MPH")
            hp = weight / ((quarter_et / 5.825) ** 3)
            findings.append(f"Estimated Wheel HP: {hp:.0f} (at {weight} lbs)")
        
        if eighth_et > 0:
            findings.append(f"Eighth Mile: {eighth_et:.3f}s")
            if quarter_et <= 0:
                pred = eighth_et * 1.5455
                findings.append(f"Predicted Quarter: {pred:.3f}s")
        
        if ft_60 > 0:
            findings.append(f"\n60-Foot: {ft_60:.3f}s")
            if ft_60 < 1.4:
                findings.append("  Excellent launch - near pro level")
            elif ft_60 < 1.6:
                findings.append("  Very good launch")
            elif ft_60 < 1.8:
                findings.append("  Good launch - some room to improve")
            elif ft_60 < 2.0:
                findings.append("  Average - significant ET left on table")
                improvement = ft_60 - 1.6
                findings.append(f"  Improving to 1.6s could gain ~{improvement * 2:.2f}s ET")
            else:
                findings.append("  ⚠ Poor launch - major traction/technique issue")
                findings.append("  Check: tires, pressure, converter, launch RPM, suspension")
        
        # Analyze incremental times
        ft_330 = slip.get("ft_330", 0)
        if ft_60 > 0 and ft_330 > 0 and eighth_et > 0:
            seg1 = ft_60  # 0-60ft
            seg2 = ft_330 - ft_60  # 60-330ft
            seg3 = eighth_et - ft_330  # 330-660ft
            
            findings.append(f"\n=== Segment Analysis ===")
            findings.append(f"0-60ft:    {seg1:.3f}s (launch/traction)")
            findings.append(f"60-330ft:  {seg2:.3f}s (1st gear pull)")
            findings.append(f"330-660ft: {seg3:.3f}s (2nd gear pull)")
            
            if quarter_et > 0:
                seg4 = quarter_et - eighth_et
                findings.append(f"660-1320ft: {seg4:.3f}s (top end)")
                
                # MPH pickup analysis
                eighth_mph = slip.get("eighth_mph", 0)
                if eighth_mph > 0 and quarter_mph > 0:
                    mph_gain = quarter_mph - eighth_mph
                    findings.append(f"\nMPH gain 1/8 to 1/4: {mph_gain:.1f} MPH")
                    if mph_gain > 30:
                        findings.append("  Strong top-end pull - engine making good power")
                    elif mph_gain < 20:
                        findings.append("  ⚠ Weak top-end - check timing, fuel, or engine health")
        
        return "\n".join(findings)
    
    def get_tuning_advice(self, question: str, context: Dict = None) -> str:
        """
        Answer a tuning question using the knowledge base and optional LLM.
        
        If an LLM is loaded, it enhances the response with natural language.
        Otherwise, uses the rule-based expert system.
        """
        question_lower = question.lower()
        
        # Check for common issue patterns
        symptoms = []
        if "hesitat" in question_lower or "stumble" in question_lower:
            symptoms.append("hesitation")
        if "lean" in question_lower:
            symptoms.append("lean")
        if "rich" in question_lower or "bog" in question_lower:
            symptoms.append("rich bog")
        if "idle" in question_lower and ("hunt" in question_lower or "rough" in question_lower or "stall" in question_lower):
            symptoms.append("unstable idle")
        if "60" in question_lower and ("foot" in question_lower or "ft" in question_lower):
            symptoms.append("poor 60ft")
        if "shift" in question_lower and "lean" in question_lower:
            symptoms.append("shift lean spike")
        
        response_parts = []
        
        # Symptom-based diagnosis
        if symptoms:
            diagnoses = self.kb.diagnose_issue(symptoms)
            if diagnoses:
                for diag in diagnoses[:2]:
                    response_parts.append(f"Possible issue: {diag['issue'].replace('_', ' ').title()}")
                    response_parts.append(f"Confidence: {diag['confidence']*100:.0f}%")
                    response_parts.append("\nLikely causes:")
                    for cause in diag["causes"]:
                        response_parts.append(f"  • {cause}")
                    response_parts.append("\nRecommended solutions:")
                    for sol in diag["solutions"]:
                        response_parts.append(f"  → {sol}")
                    response_parts.append("")
        
        # Topic-specific responses
        if "afr" in question_lower or "air fuel" in question_lower or "fuel" in question_lower:
            if "wot" in question_lower or "wide open" in question_lower:
                rec = self.kb.get_afr_recommendation("wot_na")
                response_parts.append(f"WOT AFR Target: {rec['target']}:1")
                response_parts.append(f"Safe range: {rec['range'][0]}-{rec['range'][1]}")
                response_parts.append(f"Note: {rec['note']}")
            elif "idle" in question_lower:
                rec = self.kb.get_afr_recommendation("idle_stock")
                response_parts.append(f"Idle AFR Target: {rec['target']}:1")
                response_parts.append(f"Range: {rec['range'][0]}-{rec['range'][1]}")
            elif "cruise" in question_lower:
                rec = self.kb.get_afr_recommendation("cruise")
                response_parts.append(f"Cruise AFR Target: {rec['target']}:1")
                response_parts.append(f"Range: {rec['range'][0]}-{rec['range'][1]}")
        
        if "timing" in question_lower or "ignition" in question_lower:
            cam_type = context.get("cam_type", "stock_mild") if context else "stock_mild"
            rules = self.kb.TIMING_RULES.get(cam_type, self.kb.TIMING_RULES["stock_mild"])
            response_parts.append(f"Timing recommendations for {cam_type} cam:")
            for zone, (low, high, note) in rules.items():
                response_parts.append(f"  {zone}: {low}-{high}° BTDC ({note})")
        
        if "drag" in question_lower or "strip" in question_lower or "launch" in question_lower:
            response_parts.append("\nDrag Racing Tips:")
            for tip_name, tip_text in list(self.kb.DRAG_TIPS.items())[:5]:
                response_parts.append(f"  {tip_name}: {tip_text}")
        
        if "ae" in question_lower or "acceleration enrichment" in question_lower or "accel" in question_lower:
            response_parts.append("Acceleration Enrichment Tips:")
            response_parts.append("  • AE acts like the accelerator pump on a carburetor")
            response_parts.append("  • TPS RoC Blanking: Set to 7-10 for drag racing")
            response_parts.append("  • If lean on tip-in: increase first 4-5 cells of AE vs TPS RoC by 15-25%")
            response_parts.append("  • If rich bog on tip-in: decrease middle cells by 10-20%")
            response_parts.append("  • AE only fires for fractions of a second during rapid throttle changes")
        
        if "learn" in question_lower or "self-tune" in question_lower:
            response_parts.append("Learning / Self-Tune Info:")
            response_parts.append("  • Learning only occurs above 160°F coolant (or your set temp)")
            response_parts.append("  • Transfer Learning to Base periodically for best results")
            response_parts.append("  • After transferring, smooth the base table once")
            response_parts.append("  • Learning does NOT tune the AFR target table - you must set that")
            response_parts.append("  • At WOT/heavy accel, system goes Open Loop - base table is king")
        
        # If we have an LLM, enhance the response
        if self.llm_available and self.llm:
            try:
                llm_context = "\n".join(response_parts) if response_parts else "No specific rules matched."
                if context:
                    llm_context += f"\n\nVehicle context: {json.dumps(context, indent=2)}"
                
                prompt = (
                    f"You are an expert Holley Sniper EFI tuner specializing in drag racing. "
                    f"Answer this question concisely based on the following knowledge:\n\n"
                    f"Knowledge base response:\n{llm_context}\n\n"
                    f"User question: {question}\n\n"
                    f"Provide a clear, actionable answer. Be specific about values and settings."
                )
                
                output = self.llm(
                    prompt,
                    max_tokens=512,
                    temperature=0.3,
                    stop=["User:", "\n\n\n"],
                )
                
                llm_response = output["choices"][0]["text"].strip()
                if llm_response:
                    response_parts.append("\n--- AI Enhanced Analysis ---")
                    response_parts.append(llm_response)
            except Exception as e:
                response_parts.append(f"\n(LLM enhancement unavailable: {str(e)[:50]})")
        
        if not response_parts:
            response_parts.append("I can help with Holley Sniper EFI tuning questions about:")
            response_parts.append("  • AFR/fuel tuning (idle, cruise, WOT)")
            response_parts.append("  • Ignition timing optimization")
            response_parts.append("  • Acceleration enrichment tuning")
            response_parts.append("  • Drag racing setup and launch tuning")
            response_parts.append("  • Idle stability issues")
            response_parts.append("  • Learning/self-tune process")
            response_parts.append("  • Time slip analysis")
            response_parts.append("\nTry asking about a specific symptom or tuning area!")
        
        return "\n".join(response_parts)
    
    def generate_comprehensive_analysis(self, datalog_analysis: Dict,
                                         time_slips: List[Dict],
                                         vehicle: Dict) -> str:
        """Generate a comprehensive analysis combining all data sources."""
        sections = []
        
        sections.append("╔══════════════════════════════════════════════════════════╗")
        sections.append("║     SNIPER DRAG TUNER - COMPREHENSIVE ANALYSIS          ║")
        sections.append("╚══════════════════════════════════════════════════════════╝")
        sections.append("")
        
        # Datalog analysis
        if datalog_analysis:
            sections.append(self.analyze_datalog(datalog_analysis))
            sections.append("")
        
        # Time slip analysis
        for i, slip in enumerate(time_slips):
            sections.append(f"\n--- Time Slip #{i+1} ---")
            sections.append(self.analyze_time_slip(slip, vehicle))
        
        # Overall assessment
        sections.append("\n" + "=" * 50)
        sections.append("OVERALL ASSESSMENT")
        sections.append("=" * 50)
        
        # Determine priority areas
        priorities = []
        
        wot = datalog_analysis.get("wot_analysis", {}) if datalog_analysis else {}
        if wot.get("overall_avg_afr", 12.8) > 13.5:
            priorities.append("🔴 CRITICAL: WOT fueling is lean - add fuel immediately")
        elif wot.get("overall_avg_afr", 12.8) < 11.5:
            priorities.append("🟡 ATTENTION: WOT fueling is very rich - losing power")
        
        for slip in time_slips:
            if slip.get("ft_60", 0) > 2.0:
                priorities.append("🔴 CRITICAL: 60-foot times need major improvement")
                break
            elif slip.get("ft_60", 0) > 1.8:
                priorities.append("🟡 ATTENTION: 60-foot times have room for improvement")
                break
        
        ae = datalog_analysis.get("ae_analysis", {}) if datalog_analysis else {}
        if ae.get("lean_ae_events", 0) > 0:
            priorities.append("🟡 ATTENTION: Lean events during acceleration - tune AE")
        
        if priorities:
            sections.append("\nPriority items:")
            for p in priorities:
                sections.append(f"  {p}")
        else:
            sections.append("\n✅ No critical issues detected. Fine-tuning recommended.")
        
        return "\n".join(sections)


class ModelManager:
    """Manages local model download and setup."""
    
    RECOMMENDED_MODELS = {
        "tinyllama-1.1b": {
            "name": "TinyLlama 1.1B (Recommended - Small & Fast)",
            "url": "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
            "size_gb": 0.7,
            "ram_required_gb": 2,
            "description": "Small model suitable for enhancing tuning explanations. Fast on CPU.",
        },
        "phi-2": {
            "name": "Phi-2 2.7B (Better Quality - Medium)",
            "url": "https://huggingface.co/TheBloke/phi-2-GGUF/resolve/main/phi-2.Q4_K_M.gguf",
            "size_gb": 1.8,
            "ram_required_gb": 4,
            "description": "Higher quality responses. Good balance of speed and quality.",
        },
        "mistral-7b": {
            "name": "Mistral 7B (Best Quality - Large)",
            "url": "https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf",
            "size_gb": 4.4,
            "ram_required_gb": 8,
            "description": "Best quality responses. Requires more RAM and disk space.",
        },
    }
    
    @staticmethod
    def get_model_dir() -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
    
    @classmethod
    def list_available_models(cls) -> List[Dict]:
        """List models that are downloaded and ready to use."""
        model_dir = cls.get_model_dir()
        available = []
        
        if os.path.exists(model_dir):
            for f in os.listdir(model_dir):
                if f.endswith('.gguf'):
                    filepath = os.path.join(model_dir, f)
                    size_gb = os.path.getsize(filepath) / (1024**3)
                    available.append({
                        "filename": f,
                        "path": filepath,
                        "size_gb": size_gb,
                    })
        
        return available
    
    @classmethod
    def get_download_instructions(cls) -> str:
        """Get instructions for downloading a model."""
        instructions = [
            "LOCAL MODEL SETUP",
            "=" * 50,
            "",
            "The tuning agent works without a local LLM using its built-in",
            "expert knowledge base. However, for enhanced natural language",
            "interaction, you can download a GGUF model file.",
            "",
            "OPTION 1: TinyLlama 1.1B (Recommended for most users)",
            f"  Size: ~700 MB | RAM needed: ~2 GB",
            f"  Download from: huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
            f"  File: tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
            "",
            "OPTION 2: Phi-2 2.7B (Better quality)",
            f"  Size: ~1.8 GB | RAM needed: ~4 GB",
            f"  Download from: huggingface.co/TheBloke/phi-2-GGUF",
            f"  File: phi-2.Q4_K_M.gguf",
            "",
            "OPTION 3: Mistral 7B (Best quality)",
            f"  Size: ~4.4 GB | RAM needed: ~8 GB",
            f"  Download from: huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF",
            f"  File: mistral-7b-instruct-v0.2.Q4_K_M.gguf",
            "",
            "INSTALLATION:",
            f"  1. Download a .gguf file from one of the above sources",
            f"  2. Place it in the 'models' folder next to this application",
            f"  3. In the app, go to Settings > Select Local Model",
            f"  4. Browse to and select the .gguf file",
            "",
            "NOTE: The expert system works fully without a model.",
            "The LLM only enhances natural language conversation quality.",
        ]
        return "\n".join(instructions)

"""
sec_lookup.py — BEE SEC Benchmark Lookup with Fuzzy Matching

Provides:
  - get_sec(process, material) -> dict with min/typical/max/yield_coefficient
  - get_emission_factor(process, material) -> float (kgCO2e/kg)
  - list_available_processes() -> list[str]
  - list_available_materials(process) -> list[str]

SEC data sourced from BEE India SME cluster benchmarks (forging, casting,
stamping, machining). Fuzzy matching handles real-world input variations like
"steel" -> "mild_steel", "aluminium alloy" -> "aluminium_alloy", etc.

Never raises on unknown input — logs a warning and returns a safe default.
"""

import json
import logging
import os
from pathlib import Path
from difflib import get_close_matches
from typing import Optional

logger = logging.getLogger(__name__)

# ── Path resolution ──────────────────────────────────────────────────────────
_BENCHMARK_DIR = Path(__file__).resolve().parents[3] / "data" / "sec_benchmarks"

# ── Default fallback SEC (conservative MSME estimate) ───────────────────────
_DEFAULT_SEC = {
    "min": 400,
    "typical": 700,
    "max": 1200,
    "yield_coefficient": 0.80,
    "notes": "DEFAULT — process/material not found in BEE benchmark database. Using conservative MSME estimate.",
    "_is_default": True,
}

# ── Alias map: normalise common user inputs to canonical benchmark keys ──────
# Format: "user_input_variant" -> "canonical_key_in_json"
_PROCESS_ALIASES = {
    # forging variants
    "forge": "forging",
    "hot_forging": "forging",
    "cold_forging": "forging",
    "drop_forging": "forging",
    "press_forging": "forging",
    # casting variants
    "cast": "casting",
    "foundry": "casting",
    "die_casting": "casting",
    "sand_casting": "casting",
    "investment_casting": "casting",
    # stamping variants
    "stamp": "stamping",
    "pressing": "stamping",
    "sheet_metal": "stamping",
    "blanking": "stamping",
    "deep_drawing": "stamping",
    "press_work": "stamping",
    # machining variants
    "machine": "machining",
    "machined": "machining",
    "turning": "machining",
    "milling": "machining",
    "grinding": "machining",
    "drilling": "machining",
    "cnc": "machining",
    "lathe": "machining",
}

_MATERIAL_ALIASES = {
    # steel variants
    "steel": "mild_steel",
    "ms": "mild_steel",
    "mild steel": "mild_steel",
    "carbon_steel": "mild_steel",
    "carbon steel": "mild_steel",
    "low_carbon_steel": "mild_steel",
    "is2062": "mild_steel",
    # alloy steel
    "alloy steel": "alloy_steel",
    "high_strength_steel": "alloy_steel",
    "hss": "alloy_steel",
    "tool_steel": "alloy_steel",
    "en8": "alloy_steel",
    "en24": "alloy_steel",
    "42crmo4": "alloy_steel",
    # stainless
    "ss": "stainless_steel",
    "stainless": "stainless_steel",
    "ss304": "stainless_steel",
    "ss316": "stainless_steel",
    "inox": "stainless_steel",
    # aluminium variants
    "aluminum": "aluminium",
    "al": "aluminium",
    "pure_aluminium": "aluminium",
    "aluminium alloy": "aluminium_alloy",
    "aluminum_alloy": "aluminium_alloy",
    "al_alloy": "aluminium_alloy",
    "6061": "aluminium_alloy",
    "7075": "aluminium_alloy",
    "lm6": "aluminium_alloy",
    "lm25": "aluminium_alloy",
    # cast iron
    "cast iron": "cast_iron_turning",
    "ci": "cast_iron_turning",
    "grey_iron": "grey_iron",
    "gray_iron": "grey_iron",
    "gi": "grey_iron",
    "ductile iron": "ductile_iron",
    "sg_iron": "ductile_iron",
    "nodular_iron": "ductile_iron",
    # brass / copper
    "bronze": "brass",
    "cu": "brass",
    "copper_alloy": "brass",
    # zinc
    "zinc": "zinc_alloy",
    "zn": "zinc_alloy",
    "zamak": "zinc_alloy",
    # stamping-specific
    "cold_stamping": "cold_stamping_mild_steel",
    "hot_stamping": "hot_stamping_steel",
    "sheet_steel": "cold_stamping_mild_steel",
}


# ── File loader with caching ─────────────────────────────────────────────────
_cache: dict[str, dict] = {}


def _load_benchmark(process: str) -> Optional[dict]:
    """Load JSON benchmark file for a process. Returns None if not found."""
    if process in _cache:
        return _cache[process]

    filepath = _BENCHMARK_DIR / f"{process}.json"
    if not filepath.exists():
        logger.warning(f"sec_lookup: no benchmark file for process '{process}' at {filepath}")
        return None

    try:
        with open(filepath, "r") as f:
            data = json.load(f)
        _cache[process] = data
        return data
    except Exception as e:
        logger.error(f"sec_lookup: failed to load {filepath}: {e}")
        return None


# ── Normalisation helpers ────────────────────────────────────────────────────

def _normalise_process(process: str) -> str:
    """Normalise process string to canonical benchmark filename."""
    p = process.lower().strip().replace(" ", "_").replace("-", "_")
    if p in _PROCESS_ALIASES:
        return _PROCESS_ALIASES[p]
    return p


def _normalise_material(material: str) -> str:
    """Normalise material string — apply alias map first, then return cleaned."""
    m = material.lower().strip().replace(" ", "_").replace("-", "_")
    # Check alias map (includes non-underscore originals too)
    m_orig = material.lower().strip()
    if m_orig in _MATERIAL_ALIASES:
        return _MATERIAL_ALIASES[m_orig]
    if m in _MATERIAL_ALIASES:
        return _MATERIAL_ALIASES[m]
    return m


def _fuzzy_match_material(material: str, available: list[str]) -> Optional[str]:
    """
    Try fuzzy matching material against available benchmark keys.
    Returns best match if similarity >= 0.6, else None.
    """
    matches = get_close_matches(material, available, n=1, cutoff=0.6)
    if matches:
        return matches[0]
    return None


# ── Public API ───────────────────────────────────────────────────────────────

def list_available_processes() -> list[str]:
    """Return list of processes with benchmark files in the data directory."""
    if not _BENCHMARK_DIR.exists():
        logger.error(f"sec_lookup: benchmark directory not found: {_BENCHMARK_DIR}")
        return []
    return sorted([
        p.stem for p in _BENCHMARK_DIR.glob("*.json")
    ])


def list_available_materials(process: str) -> list[str]:
    """
    Return list of material keys available for a given process.
    Returns empty list if process not found.
    """
    norm_process = _normalise_process(process)
    data = _load_benchmark(norm_process)
    if data is None:
        return []
    return list(data.get("benchmarks", {}).keys())


def get_sec(process: str, material: str) -> dict:
    """
    Look up SEC benchmark for a process + material combination.

    Returns dict with keys: min, typical, max, yield_coefficient, notes
    Always returns a valid dict — falls back to _DEFAULT_SEC with a warning
    if process or material is not found.

    Args:
        process: e.g. "forging", "casting", "stamping", "machining"
        material: e.g. "mild_steel", "grey_iron", "aluminium_alloy"

    Returns:
        dict with SEC values (kWh/tonne) and yield_coefficient
    """
    norm_process = _normalise_process(process)
    norm_material = _normalise_material(material)

    data = _load_benchmark(norm_process)
    if data is None:
        # Try fuzzy process match
        available_processes = list_available_processes()
        fuzzy_proc = _fuzzy_match_material(norm_process, available_processes)
        if fuzzy_proc:
            logger.warning(
                f"sec_lookup: process '{process}' not found; using fuzzy match '{fuzzy_proc}'"
            )
            norm_process = fuzzy_proc
            data = _load_benchmark(norm_process)
        else:
            logger.warning(
                f"sec_lookup: process '{process}' not found and no fuzzy match. "
                f"Available: {available_processes}. Returning default SEC."
            )
            return _DEFAULT_SEC.copy()

    benchmarks = data.get("benchmarks", {})
    available_materials = list(benchmarks.keys())

    # Direct lookup
    if norm_material in benchmarks:
        result = benchmarks[norm_material].copy()
        result["_process"] = norm_process
        result["_material"] = norm_material
        result["_is_default"] = False
        return result

    # Fuzzy match
    fuzzy_mat = _fuzzy_match_material(norm_material, available_materials)
    if fuzzy_mat:
        logger.warning(
            f"sec_lookup: material '{material}' (normalised: '{norm_material}') not found "
            f"in '{norm_process}'; using fuzzy match '{fuzzy_mat}'"
        )
        result = benchmarks[fuzzy_mat].copy()
        result["_process"] = norm_process
        result["_material"] = fuzzy_mat
        result["_fuzzy_matched"] = True
        result["_is_default"] = False
        return result

    # Fallback: return default with warning
    logger.warning(
        f"sec_lookup: material '{material}' not found in '{norm_process}'. "
        f"Available materials: {available_materials}. Returning default SEC."
    )
    fallback = _DEFAULT_SEC.copy()
    fallback["_process"] = norm_process
    fallback["_material"] = norm_material
    return fallback


def get_emission_factor(process: str, material: str) -> float:
    """
    Get material emission factor (kgCO2e/kg) for a process + material.

    Looks up emission_factors block in the benchmark JSON.
    Falls back to a conservative default (1.85 kgCO2e/kg = mild steel primary)
    if not found, with a warning.

    Returns:
        float: kgCO2e per kg of input material
    """
    _EMISSION_DEFAULT = 1.85  # mild steel primary — conservative fallback

    norm_process = _normalise_process(process)
    norm_material = _normalise_material(material)

    data = _load_benchmark(norm_process)
    if data is None:
        logger.warning(
            f"sec_lookup.get_emission_factor: process '{process}' not found. "
            f"Returning default {_EMISSION_DEFAULT} kgCO2e/kg."
        )
        return _EMISSION_DEFAULT

    ef_block = data.get("emission_factors", {})

    # Try: "{material}_primary_kg_co2e_per_kg" first, then "_scrap_", then bare
    candidates = [
        f"{norm_material}_primary_kg_co2e_per_kg",
        f"{norm_material}_kg_co2e_per_kg",
        f"{norm_material}_scrap_kg_co2e_per_kg",
    ]
    for key in candidates:
        if key in ef_block:
            return float(ef_block[key])

    # Fuzzy match on emission factor keys
    ef_keys = [k for k in ef_block.keys() if not k.startswith("_")]
    fuzzy_ef = _fuzzy_match_material(norm_material, ef_keys)
    if fuzzy_ef:
        logger.warning(
            f"sec_lookup.get_emission_factor: '{norm_material}' not found; "
            f"using fuzzy match '{fuzzy_ef}' = {ef_block[fuzzy_ef]}"
        )
        return float(ef_block[fuzzy_ef])

    logger.warning(
        f"sec_lookup.get_emission_factor: no emission factor for '{material}' "
        f"in '{process}'. Returning default {_EMISSION_DEFAULT} kgCO2e/kg."
    )
    return _EMISSION_DEFAULT


def get_grid_emission_factor(process: str, region: str = "india_national_grid") -> float:
    """
    Get grid emission factor (kgCO2e/kWh) for a region.
    Defaults to India national grid (0.716 kgCO2e/kWh, CEA Version 18).

    Args:
        process: any valid process (used to load the benchmark file for the EF block)
        region: one of india_national_grid, western_region, northern_region,
                southern_region, eastern_region

    Returns:
        float: kgCO2e per kWh
    """
    _GRID_DEFAULT = 0.716  # CEA India national grid

    norm_process = _normalise_process(process)
    data = _load_benchmark(norm_process)

    if data is None:
        return _GRID_DEFAULT

    gef_block = data.get("grid_emission_factor", {})
    norm_region = region.lower().strip().replace(" ", "_")

    if norm_region in gef_block:
        return float(gef_block[norm_region])

    logger.warning(
        f"sec_lookup.get_grid_emission_factor: region '{region}' not found. "
        f"Returning India national grid default {_GRID_DEFAULT}."
    )
    return _GRID_DEFAULT
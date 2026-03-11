import numpy as np
from core.emission_factors.factor_db import get_grid_ef, get_material_ef

N_SAMPLES = 1000
SEC_UNCERTAINTY = 0.15

def compute_carbon_estimates(
    energy_results: list[dict],
    material_results: list[dict],
    total_kwh: float,
    grid_zone: str = "india_national"
) -> list[dict]:
    grid_ef = get_grid_ef(grid_zone)
    
    outputs = []
    
    mat_lookup = {r.get("id", str(i)): r for i, r in enumerate(material_results)}
    
    for i, e_result in enumerate(energy_results):
        product_id = e_result.get("id", str(i))
        m_result = mat_lookup.get(product_id, {})
        
        material_type = e_result.get("material", "mild_steel")
        # is_scrap = e_result.get("assumed_scrap_based", True)
        mat_ef = get_material_ef(material_type)
        
        sec_mean = e_result["sec_benchmark"]["typical"]
        sec_std = sec_mean * SEC_UNCERTAINTY
        
        samples = []
        for _ in range(N_SAMPLES):
            sec_sample = np.random.normal(sec_mean, sec_std)
            sec_sample = max(sec_sample, e_result["sec_benchmark"]["min"])
            
            tonnes_per_unit = e_result["unit_weight_kg"] / 1000
            energy_per_unit = sec_sample * tonnes_per_unit
            
            co2e_energy = energy_per_unit * grid_ef
            
            mat_input = m_result.get("material_input_per_unit_kg", e_result["unit_weight_kg"])
            co2e_material = mat_input * mat_ef
            
            samples.append(co2e_energy + co2e_material)
        
        samples = np.array(samples)
        
        p5, p50, p95 = np.percentile(samples, [5, 50, 95])
        confidence = _compute_confidence(e_result, m_result)
        
        net_mass_tonnes = (e_result["quantity_units"] * e_result["unit_weight_kg"]) / 1000
        
        outputs.append({
            "product_id": product_id,
            "description": e_result.get("description", ""),
            "hs_code": e_result.get("hs_code", ""),
            "quantity_units": e_result["quantity_units"],
            "unit_weight_kg": e_result["unit_weight_kg"],
            "net_mass_tonnes": net_mass_tonnes,
            "co2e_min": round(p5 * e_result["quantity_units"], 2),
            "co2e_estimate": round(p50 * e_result["quantity_units"], 2),
            "co2e_max": round(p95 * e_result["quantity_units"], 2),
            "co2e_per_unit_min": round(p5, 3),
            "co2e_per_unit_estimate": round(p50, 3),
            "co2e_per_unit_max": round(p95, 3),
            "intensity_min": round(p5 * 1000 / e_result["unit_weight_kg"] / 1000, 3),
            "intensity_estimate": round(p50 * 1000 / e_result["unit_weight_kg"] / 1000, 3),
            "intensity_max": round(p95 * 1000 / e_result["unit_weight_kg"] / 1000, 3),
            "confidence_pct": confidence,
            "methodology": "physics_informed_bayesian_disaggregation"
        })
    
    return outputs

def _compute_confidence(energy_result: dict, material_result: dict) -> float:
    score = 100.0
    
    sec = energy_result.get("sec_benchmark", {})
    if sec:
        range_pct = (sec.get("max", 0) - sec.get("min", 0)) / sec.get("typical", 1)
        score -= range_pct * 20
    
    scale = material_result.get("material_scale_factor", 1.0)
    score -= abs(1.0 - scale) * 30
    
    return round(max(min(score, 95), 40), 1)
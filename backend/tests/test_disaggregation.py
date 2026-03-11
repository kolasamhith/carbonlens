import json
import os
from core.disaggregation.energy_attribution import attribute_energy
from core.disaggregation.material_attribution import attribute_material
from core.disaggregation.bayesian_engine import compute_carbon_estimates

def test_disaggregation_pipeline():
    data_path = os.path.join(os.path.dirname(__file__), "../../data/sample_inputs/sample_factory_input.json")
    with open(data_path) as f:
        data = json.load(f)
    
    total_kwh = data["energy"]["total_kwh"]
    products = data["products"]
    
    energy_res = attribute_energy(total_kwh, products)
    
    total_alloc_kwh = sum(p["allocated_kwh_total"] for p in energy_res)
    assert abs(total_alloc_kwh - total_kwh) < 0.1
    
    total_material = sum(m["quantity_kg"] for m in data["materials"])
    material_res = attribute_material(total_material, products)
    
    total_gross = sum(p["material_input_per_unit_kg"] * p["quantity_units"] for p in material_res)
    assert abs(total_gross - total_material) < 0.1
    
    carbon_res = compute_carbon_estimates(energy_res, material_res, total_kwh)
    
    for p in carbon_res:
        assert 40 <= p["confidence_pct"] <= 95
        assert p["co2e_estimate"] > 0
        assert p["co2e_min"] <= p["co2e_estimate"] <= p["co2e_max"]
from core.emission_factors.sec_lookup import get_yield_coefficient

def attribute_material(total_material_kg: float, products: list[dict]) -> list[dict]:
    demands = []
    for product in products:
        yield_coeff = get_yield_coefficient(product["process"], product["material"])
        gross_per_unit = product["unit_weight_kg"] / yield_coeff
        total_gross = gross_per_unit * product["quantity_units"]
        demands.append({
            "product": product,
            "yield_coeff": yield_coeff,
            "gross_per_unit": gross_per_unit,
            "total_gross_demand": total_gross
        })
    
    total_demand = sum(d["total_gross_demand"] for d in demands)
    
    scale = total_material_kg / total_demand if total_demand > 0 else 1.0
    
    results = []
    for d in demands:
        adjusted_gross_per_unit = d["gross_per_unit"] * scale
        results.append({
            **d["product"],
            "yield_coefficient": d["yield_coeff"],
            "material_input_per_unit_kg": adjusted_gross_per_unit,
            "material_output_per_unit_kg": d["product"]["unit_weight_kg"],
            "material_scale_factor": scale
        })
    
    return results
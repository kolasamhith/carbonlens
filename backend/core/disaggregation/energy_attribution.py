from core.emission_factors.sec_lookup import get_sec

def attribute_energy(total_kwh: float, products: list[dict]) -> list[dict]:
    weights = []
    for product in products:
        sec = get_sec(product["process"], product["material"])
        tonnes = (product["quantity_units"] * product["unit_weight_kg"]) / 1000
        weight = sec["typical"] * tonnes
        weights.append({
            "product": product,
            "sec": sec,
            "tonnes": tonnes,
            "weight": weight
        })
    
    total_weight = sum(w["weight"] for w in weights)
    
    results = []
    for w in weights:
        share = w["weight"] / total_weight if total_weight > 0 else 0
        allocated_total = total_kwh * share
        allocated_per_unit = allocated_total / w["product"]["quantity_units"]
        
        results.append({
            **w["product"],
            "sec_benchmark": w["sec"],
            "energy_share": share,
            "allocated_kwh_total": allocated_total,
            "allocated_kwh_per_unit": allocated_per_unit
        })
    
    return results
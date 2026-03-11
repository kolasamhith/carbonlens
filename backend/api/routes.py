from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import Response
from api.schemas import AnalyzeRequest, AnalyzeResponse
import uuid

# Import Core Engine Modules
from core.disaggregation.energy_attribution import attribute_energy
from core.disaggregation.material_attribution import attribute_material
from core.disaggregation.bayesian_engine import compute_carbon_estimates

# Import Extraction Modules
from core.extraction.document_handler import handle_upload, merge_extractions

# Import Export Utilities
from utils.pdf_generator import generate_pdf_report
from utils.cbam_export import generate_cbam_export

router = APIRouter()

# Issue #11: Simple in-memory job store
# Stores analysis results by job_id for later PDF/CBAM export
JOB_STORE = {}

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    """
    Issue #9: Main endpoint that takes structured factory data, 
    runs disaggregation engine, and returns per-product CO2e estimates.
    """
    try:
        # Convert Pydantic products to dicts for the core engine
        products_dict = [p.model_dump() for p in request.products]
        
        # 1. Attribute energy (Member 1 module)
        energy_results = attribute_energy(request.energy.total_kwh, products_dict)
        
        # 2. Attribute material (Member 1 module)
        total_material_kg = sum(m.quantity_kg for m in request.materials)
        material_results = attribute_material(total_material_kg, products_dict)
        
        # 3. Compute Bayesian estimates (Member 1 module)
        grid_zone = request.factory.grid_zone or "IN_NATIONAL"
        product_emissions = compute_carbon_estimates(
            energy_results=energy_results,
            material_results=material_results,
            total_kwh=request.energy.total_kwh,
            grid_zone=grid_zone
        )
        
        # Calculate factory totals
        factory_total_co2e = sum(p["co2e_estimate"] for p in product_emissions)
        
        # Generate Job ID and build response
        job_id = str(uuid.uuid4())
        response_data = {
            "job_id": job_id,
            "products": product_emissions,
            "factory_total_co2e": factory_total_co2e,
            "warnings": []
        }
        
        # Store in memory for exports
        JOB_STORE[job_id] = {
            "request": request.model_dump(),
            "response": response_data
        }
        
        return response_data

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze/upload")
async def analyze_upload(files: list[UploadFile] = File(...)):
    """
    Issue #10: Accepts PDF/CSV documents, extracts data via LLM, 
    merges them, and then runs the analysis pipeline.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
        
    try:
        extracted_extractions = []
        
        # Extract data from each uploaded file
        for file in files:
            extracted_data = await handle_upload(file)
            extracted_extractions.append(extracted_data)
            
        # Merge all extractions into a single factory input payload
        merged_payload = merge_extractions(extracted_extractions)
        
        # Validate merged payload against Pydantic schema
        analyze_request = AnalyzeRequest(**merged_payload)
        
        # Pass the validated payload to the standard analyze pipeline
        return await analyze(analyze_request)
        
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process upload: {str(e)}")


@router.get("/export/pdf/{job_id}")
async def export_pdf(job_id: str):
    """
    Issue #12: Returns PDF report for a completed analysis job.
    """
    if job_id not in JOB_STORE:
        raise HTTPException(status_code=404, detail="Job ID not found or expired")
        
    job_data = JOB_STORE[job_id]
    
    # Generate PDF bytes using Member 5's module
    pdf_bytes = generate_pdf_report(
        factory=job_data["request"]["factory"],
        reporting_period=job_data["request"]["reporting_period"],
        products=job_data["response"]["products"],
        factory_totals={"total_factory_co2e_estimate": job_data["response"]["factory_total_co2e"]}
    )
    
    # Return as downloadable file response
    return Response(
        content=pdf_bytes, 
        media_type="application/pdf", 
        headers={"Content-Disposition": f"attachment; filename=CarbonLens_Report_{job_id}.pdf"}
    )


@router.get("/export/cbam/{job_id}")
async def export_cbam(job_id: str):
    """
    Issue #12: Returns CBAM-formatted JSON export for a completed analysis job.
    """
    if job_id not in JOB_STORE:
        raise HTTPException(status_code=404, detail="Job ID not found or expired")
        
    job_data = JOB_STORE[job_id]
    
    # Generate CBAM export dictionary using Member 5's module
    cbam_dict = generate_cbam_export(
        factory=job_data["request"]["factory"],
        reporting_period=job_data["request"]["reporting_period"],
        products=job_data["response"]["products"],
        factory_totals={"total_factory_co2e_estimate": job_data["response"]["factory_total_co2e"]}
    )
    
    return cbam_dict
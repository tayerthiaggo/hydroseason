import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output" / "australia_rainfall_fetch_stress_test"
TEMPLATE_PATH = ROOT / "data" / "australia_50_sites_ground_truth_template.csv"

def main():
    if not OUTPUT_DIR.exists():
        print(f"Error: Output directory {OUTPUT_DIR} does not exist.")
        return 1

    records = []
    # Loop over sites 1 to 50
    for i in range(1, 51):
        site_id = f"aus_site_{i:03d}"
        site_file = OUTPUT_DIR / site_id / f"{site_id}_hydroseason_result.csv"
        
        if not site_file.exists():
            print(f"Warning: {site_file} not found. Skipping site.")
            continue
            
        df = pd.read_csv(site_file)
        
        # We need Date, Rainfall_mm, and SeasonType
        required_cols = ["Date", "Rainfall_mm", "SeasonType"]
        if not all(col in df.columns for col in required_cols):
            print(f"Warning: Missing required columns in {site_file}. Skipping.")
            continue
            
        site_df = df[required_cols].copy()
        site_df.insert(0, "Site_ID", site_id)
        site_df.rename(columns={"SeasonType": "Current_SeasonType_Prediction"}, inplace=True)
        site_df["GroundTruth_SeasonType"] = site_df["Current_SeasonType_Prediction"]
        
        records.append(site_df)
        
    if not records:
        print("Error: No site data found to aggregate.")
        return 1
        
    aggregated = pd.concat(records, ignore_index=True)
    
    # Sort by Site_ID and Date
    aggregated["Date"] = pd.to_datetime(aggregated["Date"])
    aggregated.sort_values(["Site_ID", "Date"], inplace=True)
    aggregated["Date"] = aggregated["Date"].dt.strftime("%Y-%m-%d")
    
    TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    aggregated.to_csv(TEMPLATE_PATH, index=False)
    print(f"Successfully generated template at {TEMPLATE_PATH}")
    print(f"Total rows: {len(aggregated)}")
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())

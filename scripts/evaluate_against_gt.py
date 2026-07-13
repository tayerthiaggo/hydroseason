import pandas as pd
import numpy as np
from pathlib import Path
import warnings
from hydroseason import classify_rainfall

# Suppress warnings for cleaner output
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
GT_PATH = ROOT / "data" / "australia_50_sites_ground_truth_template.csv"

def compute_month_distance(m1, m2):
    diff = abs(m1 - m2)
    return min(diff, 12 - diff)

def evaluate_method(gt_df, method_name):
    """Evaluate a segmentation method on the ground truth dataset."""
    all_preds = []
    
    # Store metrics across all sites
    total_months = 0
    correct_months = 0
    
    # Month-level confusion elements for F1
    tp, fp, fn, tn = 0, 0, 0, 0
    
    # Storm leaks: FP when Rainfall < 20mm
    storm_leaks = 0
    
    # Onset / Demise errors
    onset_errors = []
    demise_errors = []
    wet_year_mismatches = 0
    
    # Group GT by Site_ID
    for site_id, site_gt in gt_df.groupby("Site_ID"):
        # We need Date and Rainfall_mm to run classify_rainfall
        input_df = site_gt[["Date", "Rainfall_mm"]].copy()
        
        # Run classification
        try:
            artifacts = classify_rainfall(
                input_df,
                segmentation_method=method_name,
                raise_on_validation_error=False
            )
            pred_df = artifacts.result.copy()
        except Exception as e:
            print(f"Error running {method_name} for site {site_id}: {e}")
            continue
            
        # Merge prediction with GT on Date to align perfectly
        pred_df["Date"] = pd.to_datetime(pred_df["Date"]).dt.strftime("%Y-%m-%d")
        site_gt_aligned = site_gt.copy()
        site_gt_aligned["Date"] = pd.to_datetime(site_gt_aligned["Date"]).dt.strftime("%Y-%m-%d")
        
        pred_cols = pred_df[["Date", "SeasonType", "Hydro_Year_fixed"]].copy()
        pred_cols.rename(columns={"SeasonType": "SeasonType_Pred"}, inplace=True)
        merged = pd.merge(
            site_gt_aligned,
            pred_cols,
            on="Date"
        )
        
        # Calculate month-level metrics
        y_true = merged["GroundTruth_SeasonType"].astype(str)
        y_pred = merged["SeasonType_Pred"].astype(str)
        rain = merged["Rainfall_mm"].astype(float)
        
        for gt_val, pred_val, r_val in zip(y_true, y_pred, rain):
            total_months += 1
            if gt_val == pred_val:
                correct_months += 1
                
            if gt_val == "Wet" and pred_val == "Wet":
                tp += 1
            elif gt_val == "Dry" and pred_val == "Wet":
                fp += 1
                if r_val < 20.0:
                    storm_leaks += 1
            elif gt_val == "Wet" and pred_val == "Dry":
                fn += 1
            elif gt_val == "Dry" and pred_val == "Dry":
                tn += 1
                
        # Calculate onset/demise error within Hydro_Year_fixed groups
        for hy_fixed, group in merged.groupby("Hydro_Year_fixed"):
            gt_wet = group[group["GroundTruth_SeasonType"] == "Wet"]
            pred_wet = group[group["SeasonType_Pred"] == "Wet"]
            
            gt_has_wet = len(gt_wet) > 0
            pred_has_wet = len(pred_wet) > 0
            
            if gt_has_wet and pred_has_wet:
                # Onset = first month (coerced to dt)
                gt_onset_month = pd.to_datetime(gt_wet["Date"].iloc[0]).month
                pred_onset_month = pd.to_datetime(pred_wet["Date"].iloc[0]).month
                
                # Demise = last month
                gt_demise_month = pd.to_datetime(gt_wet["Date"].iloc[-1]).month
                pred_demise_month = pd.to_datetime(pred_wet["Date"].iloc[-1]).month
                
                onset_errors.append(compute_month_distance(gt_onset_month, pred_onset_month))
                demise_errors.append(compute_month_distance(gt_demise_month, pred_demise_month))
            elif gt_has_wet != pred_has_wet:
                wet_year_mismatches += 1
                
    # Compile metrics
    accuracy = correct_months / total_months if total_months > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    mean_onset_mae = np.mean(onset_errors) if onset_errors else np.nan
    mean_demise_mae = np.mean(demise_errors) if demise_errors else np.nan
    
    return {
        "Accuracy": accuracy,
        "Wet_F1": f1,
        "Wet_Precision": precision,
        "Wet_Recall": recall,
        "False_Positives_Total": fp,
        "Storm_Leaks_FP_lt_20mm": storm_leaks,
        "Onset_MAE_months": mean_onset_mae,
        "Demise_MAE_months": mean_demise_mae,
        "Wet_Year_Mismatches": wet_year_mismatches
    }

def main():
    if not GT_PATH.exists():
        print(f"Error: Ground truth file not found at {GT_PATH}")
        print("Please ensure the template is generated and populated.")
        return 1
        
    print("Loading Ground Truth dataset...")
    gt_df = pd.read_csv(GT_PATH)
    
    # Validate the ground truth column
    if "GroundTruth_SeasonType" not in gt_df.columns:
        print("Error: 'GroundTruth_SeasonType' column not found in ground truth CSV.")
        return 1
        
    # Check if ground truth was actually modified or if it is exactly the baseline
    is_modified = not gt_df["GroundTruth_SeasonType"].equals(gt_df["Current_SeasonType_Prediction"])
    if not is_modified:
        print("\nNOTE: GroundTruth_SeasonType is currently identical to predictions.")
        print("Evaluation below represents the baseline performance of the 'hybrid' model (100% accuracy).")
        print("To run a real audit, modify GroundTruth_SeasonType values in the CSV first.\n")
        
    methods = ["heuristic", "cumulative_anomaly", "hybrid"]
    results = {}
    
    for method in methods:
        print(f"Evaluating method: {method}...")
        results[method] = evaluate_method(gt_df, method)
        
    # Format and display output
    res_df = pd.DataFrame(results).T
    
    print("\n" + "="*80)
    print("HYDROSEASON EVALUATION SUMMARY AGAINST GROUND TRUTH")
    print("="*80)
    
    # Custom display format
    display_cols = [
        "Accuracy", "Wet_F1", "Wet_Precision", "Wet_Recall", 
        "False_Positives_Total", "Storm_Leaks_FP_lt_20mm", 
        "Onset_MAE_months", "Demise_MAE_months", "Wet_Year_Mismatches"
    ]
    
    for method, metrics in results.items():
        print(f"\nMethod: {method.upper()}")
        print(f"  Month-Level Classification:")
        print(f"    Accuracy:     {metrics['Accuracy']:.2%}")
        print(f"    Wet F1-Score: {metrics['Wet_F1']:.2%} (Prec: {metrics['Wet_Precision']:.2%}, Rec: {metrics['Wet_Recall']:.2%})")
        print(f"    Total FPs:    {metrics['False_Positives_Total']} (Storm Leaks < 20mm: {metrics['Storm_Leaks_FP_lt_20mm']})")
        print(f"  Season-Level Boundaries:")
        print(f"    Onset MAE:    {metrics['Onset_MAE_months']:.2f} months")
        print(f"    Demise MAE:   {metrics['Demise_MAE_months']:.2f} months")
        print(f"    Wet Year Mismatches: {metrics['Wet_Year_Mismatches']} occurrences")
        
    print("\n" + "="*80)
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())

# Blinded Recurrence Identifiability Cycle Cohort Review Rubric

## Review Unit
The unit of human review is a **detected hydrological cycle** within an anonymized catchment. Reviewers inspect time series packets containing only allowable observation columns (date, extent_pct, invalid_pct, quality_state, pixel counts if available, and cycle window boundaries `window_start` and `window_end`). All model outputs, regime classifications, route decisions, timing statuses, station identifiers, and calibration fingerprints are strictly hidden.

## Available Labels

1. **`point_supported`**:
   The cycle contains a distinct, identifiable annual extremum (peak or trough) that can defensibly be pinpointed to a single calendar month. Minor measurement variations elsewhere in the cycle do not obscure the single primary timing point.

2. **`interval_supported`**:
   The cycle contains an identifiable annual extremum spread across two or more adjacent months within a narrow seasonal window (span <= 2 months). The onset and recovery form a coherent seasonal event rather than diffuse plateauing.

3. **`unresolved`**:
   The cycle extremum cannot be defensibly localized to a single point or narrow interval. Typical causes include flat wide plateaus, disjointed equivalent ties across wide time gaps (multi-recurrence without evidence of single-cycle timing), or noisy diffuse signals.

4. **`uncertain`**:
   The reviewer cannot reach a confident determination due to extensive missingness, sensor anomalies, or border conditions.

## Review Protocol & Quality Control

- **Primary Reviewer**: Packets are evaluated independently by a primary reviewer blind to catchment identity and model predictions.
- **Disputed Labels**: Any disputed or borderline packets are adjudicated by an independent second reviewer.
- **Rate Denominators**: Packets labeled `uncertain` are retained in all audit reporting but are explicitly excluded from accuracy and safety rate denominators.
- **Direct Contradiction Rule**: Any instance where human ground truth is `unresolved` but the candidate policy asserts `point` constitutes a direct false-precision contradiction and halts release promotion.

# T4 failure-mode table (§10, §12)

| case | description | failed_step | signal_dimension_level | resulting_verdict |
|---|---|---|---|---|
| baseline_all_valid | All 6 dimensions healthy, no violation | None | HIGH | Normal |
| invalid_signature | Signal statement tampered after signing (sig no longer valid) | signature | LOW | Safe |
| unsupported_schema_version | Signal statement declares schema_version=999 | schema | LOW | Safe |
| source_unauthorised_for_boundary | Signal statement claims boundary TB3 (key is registered only for TB2) | authorization | LOW | Safe |
| window_id_mismatch | Signal statement carries window_id=6, current round is 7 | window_id | LOW | Safe |
| late_arrival | Signal statement arrives at 61ms, deadline Delta(w) is 60ms | arrival | LOW | Safe |

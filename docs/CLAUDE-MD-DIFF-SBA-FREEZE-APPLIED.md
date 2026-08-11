# Applied CLAUDE.md diff — SBA methodology freeze (§20/§28), with the Tail-Floor Rule

**APPLIED.** CLAUDE.md's md5 changed from `bd3990f25199177fd5d5bbfb6cce539b`
(before this pass; unchanged since the first, unapplied draft in
`docs/CLAUDE-MD-DIFF-SBA-FREEZE-PROPOSED.md`) to
`065e8649b7a0fdf71f400823da5a3576` (after). Diffed by hand against the
edit history below: the change is exactly the three edits listed, nothing
else. §3 (threat model), §4 (trust model), §6 (enforcement), §9 (crypto
rules), and every other existing section's text are byte-identical before
and after.

This supersedes `docs/CLAUDE-MD-DIFF-SBA-FREEZE-PROPOSED.md`, which
predated the ROC-estimability diagnostic and the Tail-Floor Rule and
covered only the α/β methodology (event model, apportionment, β
derivation, ppb representation). Everything from that draft is retained
here; §20 is expanded with three new paragraphs (ROC-estimability and the
Tail-Floor Rule; the Tail-Floor Rule's final text; the measured-resolution
note) and a revised closing paragraph (per-claim cohort and disclosure),
and §28 gained one clause extending its scope to Tail-Floor-Rule
conservative floors.

## Edit 1 — new changelog line (top of file)

```
Changelog: 2026-07-21 — SBA (Session Budget Allocation) methodology frozen into new §20 (α/β — event model, apportionment, β derivation, ppb representation, and the Tail-Floor Rule) and new §28 (illustrative-budget scope guard); §17's α/β entry updated to a SETTLED pointer. The Tail-Floor Rule was measured, not assumed, against a dedicated ROC-estimability diagnostic (docs/ROC-ESTIMABILITY-DIAGNOSTIC.md): Model/Device/FSI are sufficient on the held-out {4-9} cohort; Signal and Calibration require the full 9-subject pool and both still fall under the Tail-Floor Rule at all three swept budgets, per measured (not assumed) resolution limits.
```

## Edit 2 — §17's α/β bullet replaced

**Before:**
```
α and β. Provisionally 0.05/0.05. Policy, not measurement. My standing recommendation: α tighter (≈1e-3; at 10 Hz, α=0.05 per claim per window is ~30 spurious halts/minute), β looser (≈0.10, because T5 — not β — is the safety bound). Report the feasible region, not point values. The paper must derive the per-session halt rate from the per-window α explicitly.
```

**After:**
```
α and β — SETTLED (methodology; see §20 and §28). The event model, apportionment formula, β-derivation approach, ppb representation, and Tail-Floor Rule are fixed and pre-registered (docs/OSF-PREREGISTRATION.md, not yet submitted). Illustrative budget VALUES remain a swept feasible region, not point-derived; real per-claim thresholds (including any Tail-Floor-Rule conservative floor) remain Phase 9's output, not this decision's.
```

## Edit 3 — new §20 and §28, inserted after §18, before `## Environment & Workspace Rules`

Full text as it now appears in CLAUDE.md (reproduced here verbatim for
the audit trail — see CLAUDE.md itself for the authoritative, current
copy):

- §20's opening four paragraphs (Event model, α, β, Note, Representation)
  are unchanged from the original proposed draft.
- §20 gains three new paragraphs: "ROC-estimability and the Tail-Floor
  Rule" (summarizing `docs/ROC-ESTIMABILITY-DIAGNOSTIC.md`'s measured
  result), the Tail-Floor Rule's final self-contained text, and the
  "Measured resolution note" (the honest finding that the rule's trigger
  does not currently differentiate by budget for Signal/Calibration, per
  direct 1/N-vs-target-α arithmetic, not assumption).
- §20's closing paragraph ("Per-claim cohort and disclosure") replaces
  what would otherwise have been the section's ending, adding the
  resolution_status stable-label convention and the
  estimation-vs-representation distinction.
- §28 gains one clause extending its scope from "the session-availability
  budget governing α [and] the consequence-exposure budget governing β"
  to also cover "any Tail-Floor-Rule conservative floor."

## Confirmation

- `md5sum CLAUDE.md` before: `bd3990f25199177fd5d5bbfb6cce539b`.
- `md5sum CLAUDE.md` after: `065e8649b7a0fdf71f400823da5a3576`.
- Full-file read after the edit confirmed §1 through §18 unchanged except
  the two intended edits (changelog line, §17 bullet), §18 unchanged, the
  `## Environment & Workspace Rules` block unchanged and still last in the
  file, and §20/§28 inserted exactly once, in order, between them.
- No code, config, or test file was touched by this pass beyond the
  documentation listed here (`docs/ROC-ESTIMABILITY-DIAGNOSTIC.md`,
  `docs/OSF-PREREGISTRATION.md`, this file, and the superseded-marker
  added to `docs/CLAUDE-MD-DIFF-SBA-FREEZE-PROPOSED.md`) and the real-data
  diagnostic driver/tests from Part 1 (`experiments/calibration_full9_sufficiency.py`,
  `roc_estimability/stability.py`'s generalized `claim_sufficiency_verdict`,
  `tests_roc_estimability/test_stability.py`, `harnesses/mutation_check_roc_estimability.py`).

## Correction (same day) — resolution_status hash coverage

§20's original text (above) stated resolution_status was "never a signed
or hashed field," written when the field existed only in prose (CLAUDE.md,
docs) and nowhere in code — trivially true at the time, because there was
nothing to hash. A direct trace (`grep -rn "resolution_status"` across all
`.py`/`.json` files) confirmed this: zero hits outside documentation.

Fixed, not left as a documentation-only convention: `resolution_status`
(`pending | stable | tail_floor`, per claim per swept budget) is now
implemented in `config/eis.v1.json`, validated fail-closed by
`trust_kernel/bands.py`'s `validate_eis_config()`/`_validate_resolution_status()`
for any non-"bp" config format, and therefore is part of the raw JSON
`roc_config_hash()` hashes (that function hashes the entire file's
canonical content — it does not enumerate fields, so any field present in
the config is automatically covered, without needing to touch
`roc_config_hash()` itself). Demonstrated directly, not inferred:
`tests/test_bands.py:RocConfigHashCoversResolutionStatusTests` mutates
only a resolution_status value (in-memory, and separately via a real file
on disk) and shows the hash changes both times.

§20's text was corrected accordingly (see the second changelog line, dated
the same day): resolution_status is confirmed NOT a new wire/signed field
(§8's Statement/Verdict schemas are byte-identical — `trust_kernel/canon.py`,
`trust_kernel/sign.py`, `trust_kernel/schema.py` hashes unchanged, confirmed
by re-running `experiments/eis_v1_precision_validation.py`'s off-crypto-path
check), but it is also not silently editable — it is covered by §8's
existing six-config-hash discipline, the same protection every other
config value already has.

- `md5sum CLAUDE.md` before this correction: `065e8649b7a0fdf71f400823da5a3576`.
- `md5sum CLAUDE.md` after this correction: `3acda0e853af3f446ac7fb33567fed10`.
- `config/eis.v1.json`'s `roc_config_hash()` before adding resolution_status:
  `edc176940acebc0be9ffdda836981557e9597be34d162f6653194d4037b1b197`.
- `config/eis.v1.json`'s `roc_config_hash()` after: `cfeb34557eef7a2eb777d11f845cdcb013c48e3dd4ceadabcd02e3d8f8a8985d`.
- `config/eis.v0.json`'s `roc_config_hash()`: `087f66e28eb3da71ce13c6c6d2cde863fafeff066d1b01d26b292f879bad8aca`
  — unchanged throughout every pass in this project's history, confirmed again here.
- Mutation kill rate: `harnesses/mutation_check.py` 61/61 (100%, v0 codepath
  unaffected); `harnesses/mutation_check_eis_v1.py` 11/11 (100%, extended
  with three new mutants covering the resolution_status validation branch).
- Regression: pure core (`tests/`) 234/234.

Read this file completely before writing any code. It is the source of truth.
The architecture is FROZEN. Do not redesign it. Do not simplify it for elegance. If implementation reveals a genuine flaw — a theorem violation, an impossible assumption, an unverifiable claim — stop and escalate to the PI with a written impact analysis (§12). Elegance is never sufficient justification for change.

Changelog: 2026-07-18 — Phase 7 dataset frozen (BCIC IV 2a via MOABB); phase cross-references corrected for renumbered roadmap.
Changelog: 2026-07-19 — lattice reduced L⁸→L⁶: Context removed (no referent in evaluation substrate), Safety removed (covered by enforcement envelope, not independent evidence per admission-criterion falsification test).
Changelog: 2026-07-21 — SBA (Session Budget Allocation) methodology frozen into new §20 (α/β — event model, apportionment, β derivation, ppb representation, and the Tail-Floor Rule) and new §28 (illustrative-budget scope guard); §17's α/β entry updated to a SETTLED pointer. The Tail-Floor Rule was measured, not assumed, against a dedicated ROC-estimability diagnostic (docs/ROC-ESTIMABILITY-DIAGNOSTIC.md): Model/Device/FSI are sufficient on the held-out {4-9} cohort; Signal and Calibration require the full 9-subject pool and both still fall under the Tail-Floor Rule at all three swept budgets, per measured (not assumed) resolution limits.
Changelog: 2026-07-21 (correction) — resolution_status was implemented as a config/eis.v1.json field the same day §20 was frozen, after tracing found it had been described in §20's original text as "never a signed or hashed field" while not yet existing in any hashed object at all. It now lives in eis.v1.json and is covered by roc_config_hash (§8's existing six-config-hash discipline) -- §20's text corrected to state this precisely: no new wire/signed field was added (§8, §9 unchanged, confirmed by hash), but resolution_status is not silently editable either.

1. What this is
A PhD research prototype: a trust-reasoning security architecture for Brain–Computer Interface cyber-physical systems (EEG → decoder → physical actuator).
The prototype is not the contribution. The prototype is evidence for the architecture. The prototype is software-only: no live human subjects, no BCI hardware, no clinical deployment. Evidence producers instrument a real signal-processing pipeline operating on a public offline EEG dataset, so that every trust classification traces to a concrete runtime measurement rather than a synthetic value. The prototype validates architectural correctness; it is not a deployable product.
Thesis (one sentence): A trust-reasoning kernel, isolated from and independently-evidenced relative to the system it judges, produces a monotone, provenance-grounded actuation-permission verdict from evidence of measured quality — and the enforcement substrate provably bounds the physical consequence of every attack the kernel cannot detect.
The clause after the dash is the contribution. It is true even when every detector fails. That is why detector quality is not the paper's dependency.

Engineering Strategy vs Research Contribution. The architecture employs Defense-in-Depth (DiD) as its engineering strategy, not as the primary scientific contribution. Defense-in-Depth exists to generate diverse, independent, runtime evidence across multiple trust boundaries throughout the BCI software stack — each layer protects a different boundary and continuously emits measurable runtime observations. However, layered detection alone is not the contribution: conventional Defense-in-Depth ends once attacks are detected. The proposed architecture continues further — runtime evidence is interpreted by the Trust Kernel (the Runtime Trust Orchestrator; see §2's terminology note), which continuously reasons over evidence quality, trust relationships, policy constraints, and safety objectives before producing bounded enforcement decisions. Therefore the research contribution is evidence-grounded runtime trust reasoning with bounded safe actuation, not merely layered detection. Throughout the paper: never describe Defense-in-Depth as the research contribution; describe it as the mechanism used to generate trustworthy runtime evidence.

Claimed: decision soundness; graded dependency propagation; consequence-boundedness; auditability (verdicts replayable from the log); honest evidence coverage including uncovered attacks; every trust decision traceable to one or more concrete runtime measurements; no trust value manually assigned; every trust classification reproducible from recorded evidence.
Never claimed: intent verification; end-to-end security; any trust value as a calibrated probability; SIL certification; clinical readiness; statistical independence of trust dimensions; BFT.

2. Architecture (three planes)
BCI Device → Sensors(6) → Evidence Plane → Trust Kernel → Enforcement Plane → Actuator
                                ↑                                    │
                                └──────── Observer ←─────────────────┘
Evidence Plane — append-only, content-addressed log of per-sensor-signed statements. Observations and provenance only, never interpretation. Records may be appended, never altered or deleted. Every record cryptographically attributable.
Trust Kernel — jailed, pure, deterministic. Signed statements → signed, freshness-bound verdict over a per-dimension trust lattice. All interpretation lives here. Purity is what makes exhaustive verification tractable — never put state, clocks, floats, or I/O in π's call path.
Enforcement Plane — dumb, capability-gated actuator writer. Produces no evidence about itself. Its bound is computed independently of the verdict.
Sensors (6 dimensions) — Signal, Model, Calibration, Device, FSI, ActuationFidelity. Characterised evidence sources, not guaranteed-good detectors.
Observer — reads actuator feedback independently into the Evidence Plane. Sole origin of ActuationFidelity evidence. Structurally separate from the enforcer (P2).
Governing principles. P1–P3 force structure; P4–P8 are properties the structure guarantees.

P1 Separation of observation and interpretation. A sensor that emits a trust level or confidence has joined the TCB.
P2 No self-attestation. No component's report about its own integrity has evidential weight against an adversary controlling it.
P3 Centralized trust reasoning. Interpretation in exactly one small, inspectable, verifiable component.
P4 Least privilege. Kernel cannot write the actuator; enforcer cannot reason; sensors append only.
P5 Fail-safe by design. Every failure path resolves toward Safe. No path where failure yields permissiveness.
P6 Immutable evidence.
P7 Deterministic decision making.
P8 Preservative authority is never gated. Braking, controlled deceleration, and holding authority are never verdict-gated, never reduced by any envelope, bounded by the controller's brake profile alone.

Trust boundaries (six, at privilege/failure-domain transitions only — never at data-format transitions): TB1 board↔dongle · TB2 dongle↔host · TB3 host↔kernel · TB4 kernel↔enforcer · TB5 enforcer↔actuator · TB6 host↔governance. TB3 and TB4 carry the security argument.

Terminology note: "Runtime Trust Orchestrator" (used in the sections below and in paper-level prose) and "Trust Kernel" (used throughout §2, §5–§9, §11, and the existing codebase) name the same component. The codebase keeps the trust_kernel/ identifier; do not rename it without a separate, explicit decision (§18).

Evidence Producers — Trust is Derived, Never Assigned. This is a core architectural principle, elaborating P1. No runtime component may emit HIGH / MEDIUM / LOW or any equivalent trust score. The only permitted flow is:
Runtime Measurement → Evidence Statement (raw measurement only) → Evidence Interpretation (EIS) → Trust Classification → Runtime Trust Orchestrator → Policy → Enforcement
Evidence producers are measurement components. They never perform trust reasoning.

Confidence. Evidence Producers must never compute confidence. Confidence is not a runtime measurement — it is a property of detector performance (ROC, calibration, operating characteristics) and therefore belongs entirely to the Evidence Interpretation stage. A producer asserting its own confidence is effectively self-attesting its reliability, which violates architectural independence (P2).

Every Evidence Producer must define: runtime component; runtime measurement; mathematical calculation; measurement units; claim type; trust dimension; timestamp; provenance; expected polarity; window binding; smoothing behaviour (if applicable); attacks influencing the measurement.

Missing Measurements. If a producer cannot obtain a measurement, it emits nothing. It must never emit defaults, placeholder values, synthetic trust, or estimated confidence. Absence of evidence is interpreted downstream according to policy (§10: absence ⇒ LOW ⇒ fail-safe).

Claim Registry. The Claim Registry should emerge from implementation. The implementation determines what is measurable; the registry documents those measurable observations. Do not invent claim types before measurable observations exist.

Software BCI Pipeline. The runtime architecture explicitly documents the complete software processing chain:
EEG Dataset → Streaming Acquisition → Signal Processing → Artifact Detection → Feature Extraction → Classification → Predicted Intent → Security Instrumentation → Evidence Producers → Evidence Interface → Runtime Trust Orchestrator → Policy → Enforcement → Simulated Actuator
The Runtime Trust Orchestrator must remain completely independent of implementation details — it reasons only over evidence statements. The runtime pipeline may change entirely without requiring changes to the reasoning architecture.

Enforcement Exception. Only include security mechanisms that generate measurable runtime evidence. One deliberate exception exists: the Enforcement Plane does not generate evidence about itself. This is intentional — the Enforcement Plane must remain the trusted actuator boundary (P2). Attempting to make enforcement self-attesting introduces circular trust. Do not redesign this behaviour.

3. Threat model (FROZEN)
Two adversaries. The distinction is load-bearing — do not collapse them.
A_data — forges any evidence statement, any signature, any verdict; compromises any sensor and the Trust Kernel; controls all host clocks; reads all host memory. Does not execute code inside the enforcement process.
A_code — arbitrary code execution at host privilege, including inside the enforcer.
TA1 splits:
ClauseHolds againstV1 statusCeil is not a function of νA_data and A_codeDischarged by dependency analysisCeil is not adversary-writableA_data onlyAssumed. Discharged only by hardware
Position A (locked): all evidence including FSI is software-forgeable in V1. CTPR therefore provides no adversarial bound in V1. T5 rests entirely on enforcement-plane termination.
Out of scope: cognitive attacks (genuine EEG from induced states); physical destruction; the analog scalp–electrode boundary.
The honest partition — this table is why the architecture has its shape:
MechanismHonest evidenceAdversarial forgeryDetection (all sensors)Conditional on detector qualityNoCTPR propagationYesNo — FSI forgeableT4 freshnessYesNo — clocks host-ownedVerdict authenticityYesNo — kernel compromisableT5 consequence boundYesYes (vs A_data)

Behaviour-Based Attack Framework. Attack experiments must never manipulate trust directly. The only valid attack model is:
Attack → Runtime Behaviour → Measured Observations → Evidence → Trust → Policy → Enforcement
Directly assigning trust values makes experiments circular and scientifically invalid. Support behaviour-level attacks including: replay; signal injection; adversarial EEG; firmware modification; model replacement; model poisoning; communication tampering; timing attacks; observer disagreement; actuator manipulation.

4. Trust model
Lattice, not scalar. Per-dimension chain LOW ⊑ MED ⊑ HIGH; product over 6 dimensions; |E| = 3⁶ = 729.
Scalar aggregates are rejected on three grounds: they permit compensation (a strong dimension masking a failed one); they destroy provenance; they assert a calibration that does not exist. This also rules out Bayesian / Dempster–Shafer / subjective logic — each needs priors or masses no BCI dataset can supply.
There is no runtime confidence value. It was removed from the statement (sensor self-attestation). ROC-derived quantities are θ₁, θ₂, band_cap in the EIS config, kernel-side.
Interpretation (EIS v1):
score s = pol × raw_measurement          (lower = more attack-like, uniformly)
θ₁ = max{t : FPR(t) ≤ α}                 (LOW boundary; α prices spurious halts)
θ₂ = min{t : TPR(t) ≥ 1−β}               (HIGH boundary; β prices missed detection)
band(s) = LOW if s<θ₁; MED if s<θ₂; else HIGH,  then ⊓ band_cap
α and β are the only hand-set values in the interpretation layer. Stated once, globally. Every per-claim threshold is measured.
Derived, not designed: a detector never attaining TPR ≥ 1−β has no θ₂ ⇒ band_cap = MED ⇒ structurally cannot license HIGH. Propagated through the meet, a weak-detector system is permanently Constrained, mechanically. Strong detector ⇒ θ₂ ≤ θ₁ ⇒ MED collapses to empty; same formula, no special case.
Intra-dimension reduction: meet. Licensed by the admission criterion: a claim type may be admitted only if it is a necessary condition for that dimension's trustworthiness; none is sufficient. This forbids corroborating claims — meet is the wrong operator for them — and is what stops drift back to a weighted aggregate. Detector disagreement is not resolved; meet takes the worst. Missing claim ⇒ LOW (a missing record is evidence of a problem, not absence of evidence).
CTPR: effective_child = meet(child, g(FSI_level)), edges FSI→Signal, FSI→Model, g monotone in the parent's trust level — not confidence (confidence is static per detector; g(confidence) would be a constant cap and propagation inert).
Policy: π(e) = ⊓_d crit_d(effective_d) → {Safe ⊑ Constrained ⊑ Normal}; stale ⇒ Safe.

Strict (LOW alone ⇒ Safe): Signal, Model, FSI, ActuationFidelity, Calibration
Lenient (LOW alone ⇒ Constrained): Device

Why Calibration is strict — do not misstate this. LOW Calibration = detected mapping collapse (electrode shift, session mismatch, enrollment failure); the intent map is known invalid and continued actuation is indefensible. It does not defend against within-prior calibration poisoning, which keeps the sensor at MED/HIGH by construction and remains uncovered-but-consequence-bounded. Two mechanisms, two failure states. Never collapse them.
Why Device is lenient. Failure degrades confidence; bounded actuation is proportionate and halting is itself a hazard for a mobility actuator. Governing principle: strict where failure compromises the command stream, intent chain, or physical fidelity; lenient where it degrades confidence. This explicitly rejects strict-everywhere-as-safest — it is proportionate-response calibration, not safety-maximisation. Documented exception: when attestation lands, tamper/attestation-failure evidence routes to strict.

5. Theorems

T1 Monotonicity. e ⊑ e' ⟹ π(e) ⊑ π(e'). By construction.
T2 Non-compensation. π(e) ⊑ crit_x(ctpr(e)[x]) ∀x. Reportable form is the floor-dominance table.
T3 Fail-safe reachability. π(⊥)=Safe; π(stale)=Safe; Safe ∈ image(π).
T4 Verdict authenticity + freshness. Honest-evidence-conditional under Position A. Not the basis of the central claim.
T5 Consequence-boundedness. realise(ν) = Env(π̂(ν)) ⊓ Ceil ⊑ Ceil for all ν including forged. The content is not the arithmetic (x ⊓ c ⊑ c is an axiom) — it is that Ceil is not a function of ν. The security lives entirely in TA1 and the dependency structure.

T5 must never be proven from π. Under Position A the adversary forges everything, π legitimately returns Normal, and any bound derived from the verdict is circular. T5 is a property of the enforcement function's dependency structure.

6. Enforcement (FROZEN)
Φ = (max_speed, max_acceleration)     mm/s, mm/s²   fixed-point, no floats
Φ is permissive dimensions only (P8). Env(Safe) = (0,0) reads "command no motion at no acceleration" — Safe is a controlled stop by construction.
Reference configuration — these are REFERENCE VALUES, NOT PRESCRIPTIONS. Label them so in every artifact.
max_speedmax_accelerationEnv(Normal) — device capability1600800Env(Constrained)600300Env(Safe)00Ceil — prescription1000500
Ceil is a deployment-time prescription bound — the authority a clinician grants this user on this device, provisioned out-of-band at commissioning, never through the host, never a function of any verdict. Its security property is entirely negative: nothing in the runtime path can raise it.
Binding condition: if Ceil ⊒ Env(Normal) the clamp never fires and T5(a) is true-but-empty. Ceil ⊏ Env(Normal) in both components is required. Under forced Normal: realise = (1000,500) vs intended (1600,800) — that gap is Figure [T5].
In the paper, verbatim: the adversary who forges everything still gets 1 m/s. T5 bounds consequence; it does not confer safety.
Slew: tightening immediate/unlimited; loosening ≤200 mm/s and ≤100 mm/s² per window. Safe→full = 5 windows = 500 ms. Strengthens T5: realised ⊆ Env(π), so the bound holds a fortiori.
Enforcer reads exactly five fields: schema_version, window_id, verdict, expires_at, kernel_sig.
Enforcer NEVER reads: evidence_root, effective_dims, policy_version, crit_table_hash, ctpr_config_hash, roc_config_hash, claim_registry_hash, key_registry_hash, calibration_status, issued_at. Audit fields must be in the signed object and out of the parse-and-act path. Verified by the same dependency analysis that discharges T5(a).
Acceptance (no round knowledge — the enforcer must never learn the round from a host-controlled input):
accept(ν) iff sig valid ∧ schema supported
            ∧ ν.window_id ∉ accept_cache        (2-entry ring, expiry horizon)
            ∧ now < ν.expires_at
Kernel-side statement admission does check window_id == current round — the kernel opens the round, so it legitimately knows it.
Capability: one unforgeable token, held only by the enforcer, sole actuator write authority.
Watchdog — correction of record. A watchdog gives independence from enforcer liveness, not honesty. A live malicious enforcer pets the dog. Any claim that the fail-safe survives enforcer compromise is false. Two distinct hardware roles: (a) watchdog — liveness only, discharges crash/hang/OS-death; (b) in-path hardware ceiling — MCU between enforcer and motor controller, Ceil in firmware, provisioned out-of-band. Only (b) discharges TA1's writability clause against A_code. If hardware is purchased, buy (b), not (a).

7. Timing (FROZEN)
SymbolValueT window period100 ms (10 Hz)Δ(w) = D evidence deadlinet_w + 60 msκ kernel budget≤ 5 msissued_at≈ t_w + 62 msexpires_att_w + 170 ms (= t_w + T + D + M, M = 10 ms)
Verdict w valid [62,170]; w+1 valid [162,270] — 8 ms overlap, no fail-safe gap under honest timing. Suppressed successor ⇒ fail-safe at t_w+170.
Maximum stale actuation = 70 ms = 7 cm at Ceil speed. This number goes in the paper as the quantified cost of arrival-based freshness under Position A.
The invariant that makes latency bounded — name it in the paper: no unbounded wait exists in the decision path; a missing statement is never waited for, it reads LOW. Worst case = D + κ regardless of sensor behaviour. A hung sensor cannot delay the verdict. The deadline is simultaneously a security property and a hard latency bound.
fsync the window batch before the kernel reads — 2 ms of 100 ms, closes the crash-window hole where a verdict references non-durable evidence. Per-record fsync would kill you; per-window is free.
Decision path ≤67 ms of 100 ms. Trust reasoning is ~0.05% of the window — that's the deployability result, and it confirms the O(d) analysis rather than discovering it.

Latency as a primary evaluation metric. Latency is no longer solely an implementation concern — it is one of the primary evaluation metrics of the research. The paper must quantify the security overhead introduced by the Runtime Trust Orchestrator. Measure: acquisition; filtering; artifact detection; feature extraction; classification; evidence generation; evidence signing; evidence interpretation; Runtime Trust Orchestrator; enforcement; end-to-end latency; CPU; memory; throughput.

Architectural timing invariant (restates and generalises the invariant above): the Runtime Trust Orchestrator must never wait indefinitely for evidence. A missing statement must never stall runtime execution. Security failures degrade trust; they must never create unbounded latency. Worst-case latency should therefore remain bounded by Processing Delay + Kernel Processing, independent of sensor behaviour. This invariant is treated as both a security property and a real-time-systems property.

Permitted optimisations may improve runtime performance without changing architectural semantics: pipeline parallelism; streaming computation; incremental feature extraction; asynchronous evidence signing; parallel instrumentation; fast-path/slow-path separation. Never optimise by: skipping verification; waiting for delayed evidence; caching trust decisions; ignoring failed measurements.

8. Wire schema (FROZEN v1)
Statement (sensor-signed, no log state):
{schema_version, key_id, source_id, boundary, claim_type, raw_measurement, window_id, window_hash?, claimed_at, sig}
Entry (log-assigned, unsigned): {seq, prev_hash, entry_hash, statement}
Verdict (kernel-signed):
{schema_version, window_id, evidence_root, effective_dims, verdict, policy_version, crit_table_hash, ctpr_config_hash, roc_config_hash, claim_registry_hash, key_registry_hash, calibration_status, issued_at, expires_at, kernel_sig}
Why statement/entry split (Certificate-Transparency-shaped): prev_hash in signed sensor bytes admits only two outcomes — the signature covers it (every sensor serialized behind the global chain head, log state in the latency path) or it doesn't (unauthenticated chain, tamper-evidence void). Attributability from the signature; tamper-evidence from the chain. Never readmit prev_hash, trust_level, or confidence to a statement. There are tests asserting they cannot be.
Field semantics. window_id = per-round nonce, universal, mandatory. window_hash = epoch hash, required for epoch-derived claim types, forbidden for others, absent never null (a null in a signed field is how replay protection dies quietly). Duty attaches to the claim type, not the source. claimed_at advisory/audit-only. key_id for rotation and historical verification. raw_measurement fixed-point, scale pinned per claim type.
Canonical serialization: deterministic CBOR (RFC 8949 §4.2) restricted to major types 0–5. This makes two rules structural rather than enforced: floats and nulls are inexpressible. Shortest-form heads, definite lengths, bytewise-sorted keys, duplicates rejected — on both paths. Strict decoder; unknown fields rejected, not ignored (acceptance is a downgrade vector). Signatures over encode([domain_tag, object]) — not a concatenated prefix; prefix-plus-variable-body is not injective, CBOR's length-prefixed heads make the tagged pair injective by construction.
Six config hashes in every verdict (crit_table, ctpr_config, roc_config, claim_registry, key_registry, plus policy_version): without them, editing a threshold, a scale, or rotating a key silently reinterprets all history and replay stops being hermetic.
evidence_root: dedupe by statement hash, sort lexicographically, encode as canonical list. A set has no order; two honest verifiers must not disagree.

9. Ed25519 verification rule set (FROZEN — the rule set is the spec, not the library)
Restrict verification to the domain where cofactored and cofactorless verification produce identical results. This sidesteps the ZIP-215/RFC-8032 disagreement rather than picking a side — within the restricted domain there is nothing to disagree about.

Reject non-canonical R encodings (invalid y, failed x recovery).
Reject S ≥ L (malleability).
Provisioning: every public key canonically encoded and in the prime-order subgroup.
Runtime: verify R in the prime-order subgroup ([L]R = O).
k = SHA-512(R ‖ A ‖ M) mod L; verify the standard equation.
C-backed implementation (libsodium). Never implement Ed25519 arithmetic in pure Python.
key_registry_hash in the signed verdict so replay uses the exact registry that existed at production time.
Executable conformance test against published edge-case vectors ("Taming the Many EdDSAs", Chalkias, Garillot & Nikolaenko, 2020).

This is a reproducibility requirement, not only a security one. If two honest verifiers can disagree on a signature, they can disagree on a verdict, and "verdicts replayable from an immutable log" acquires a hole an artifact evaluator finds by running the code on a different machine.

10. Sensor contract
RuleSpecificationCadenceexactly one statement per registered claim type per windowDeadlineappended before Δ(w); late ⇒ that dimension LOWMeasurement definitionpinned per claim type in the registry, including the smoothing window. Sensors may hold state; sensors are not pure.Interpretationnone. No band, no level, no confidence.Failurea sensor that cannot measure emits nothing — never a default, never a sentinel, never a guess. Absence ⇒ LOW ⇒ fail-safe.
That last row is load-bearing: a "safe default" on internal error is how a broken detector silently licenses Normal.
Epoch agreement: all epoch-derived statements in a window must carry the same window_hash. Any disagreement ⇒ all epoch-derived dimensions LOW. No voting, no majority, no BFT. This is exact hash equality, not statistical correlation — it does not reopen the cross-evidence-consistency door (which is cut: it would reintroduce hand-assigned thresholds and add a detector to a consequence-bounding architecture).
Verification order (fixed — any failure ⇒ that dimension LOW, never "record absent"):
sig → schema/version → source authorised for boundary → window_id matches round → arrival before Δ(w) → value enters lattice
How evidence becomes HIGH (all conjunctive): statement admitted and s ≥ θ₂ and band_cap = HIGH (the detector's measured ROC actually reaches TPR ≥ 1−β) and every registered claim for the dimension satisfies these and CTPR isn't dragging it down. Condition 3 is why a weak detector structurally cannot license Normal — nobody hand-tuned it.

11. Coding standards and repository conventions
Language: Python 3.11. Zero runtime dependencies for the pure core — artifact reproduction must be python3 -m unittest discover -s tests with nothing to resolve. libsodium via C binding is the sole exception, and it lives behind one module.
Layout:
trust_kernel/     canon.py schema.py bands.py ctpr.py policy.py sign.py
evidence_plane/   log.py replay.py
enforcement/      clamp.py capability.py slew.py
sensors/          (6 pluggable, sensor-side state permitted)
observer/
bci_pipeline/     loader.py preprocessing.py artifacts.py features.py classifier.py pipeline.py (Phase 7: substrate only, no evidence producers)
tests_bci_pipeline/ separate test dir -- bci_pipeline/ has real numpy/scipy/mne/moabb dependencies (requirements-bci_pipeline.txt, its own venv), so its tests are not under tests/ discovery and do not affect the pure core's zero-dependency `python3 -m unittest discover -s tests`
config/           eis.v*.json  crit_table.json  ctpr.json  key_registry.json  dataset_pins.json
experiments/      e1..e9
harnesses/        mutation_check.py
artifacts/        generated figures/tables — NEVER hand-edited
provenance/       run manifests
docs/             EIS-v1.md  ENFORCEMENT-v1.md  THREAT-MODEL.md
Hard rules:

π's call path: no I/O, no state, no clocks, no floats, no allocation-heavy work. Purity is a theorem dependency.
No floats in any signed or hashed object. Fixed-point ints, scale in the registry.
Fail-closed config loading. No partial loads. roc_config_hash() validates before hashing — an invalid config must never acquire an identity a verdict could point at.
Never hand-assign a confidence or a threshold. Thresholds come from derive_thresholds() on measured ROC.
Every module docstring states which theorem or invariant it serves.


12. Testing strategy
A passing suite is not evidence. A suite that can fail is.

Mutation testing is first-class, not an appendix. For each asserted property, inject a mutant that violates it; the suite must catch it. Metric: kill rate with the specific tests that caught each. Criterion: 100%. A surviving mutant means an asserted property is untested. mutation_check.py runs in CI.
Label conformance honestly. The T1/T2 exhaustive pass is machine-checked implementation conformance, not independent empirical validation — ⊓-of-monotone-maps-is-monotone is a theorem; the check fails only on a dict typo. Report it as a regression guard.
The reportable results are the falsifiable ones: floor-dominance table, CTPR 18/18, T4 failure modes, T5 adversarial forcing, tamper-evidence, replay agreement.
CI runs conformance + floor-dominance + CTPR + tamper-evidence + T5 + mutation on every commit. A regression in a proven property fails the build.


13. Reproducibility
Every experiment run emits a manifest: config + hash, git commit + dirty-state, all parameters including α/β, dataset version + mirror, seeds, hardware, OS, timestamps, and every generated metric/figure/table/log.
Rule: no figure enters the dissertation that cannot be regenerated from its manifest by one command.
Build the manifest → figure pipeline in Phase 2, not Phase 9. Everything through Phase 8 is provisional-watermarked and gets regenerated in Phase 9. Do it manually once and you'll do it manually five times.
Calibration taint travels with the data. Every verdict carries calibration_status ∈ {provisional, measured}. validate_eis_config() refuses status: measured while any derivation is placeholder — the flag cannot be flipped without replacing the numbers. Figures from provisional runs are watermarked by the flag.
Pre-registration: OSF, before Phase 9. A git timestamp is not pre-registration — history is rewritable and reviewers know it.

14. Milestones (revised 2026-07-17 — Architectural Refinement; phases 1–2 unchanged and already delivered, see repository)
PhaseDeliverableResult produced1Sign/verify per §9 + conformance vectors(plumbing — no result)2Kernel core: π + CTPR + EIS wiring; manifest→figure pipelinefloor-dominance table; CTPR 18/18; end-to-end band monotonicity3T4 Statement Admission and Verdict Issuance(not yet specified)4Evidence Logging and Replay(not yet specified)5Enforcement Plane and Safe Actuation(not yet specified)6Observer and Actuation Fidelity(not yet specified)7Real Software BCI Pipeline (EEG → Classifier) — dataset SETTLED: BCI Competition IV 2a via MOABB, §17a(not yet specified)8Runtime Evidence Producers and Derived Claim Registry(not yet specified)9Measured ROC Integration and Runtime Calibration(not yet specified)10Latency Evaluation (Baseline vs NTF)(not yet specified)11Behaviour-Level Attack Framework(not yet specified)12Robustness, Fault Injection, Packaging(not yet specified)13Research Dashboard (Demonstration Artifact)(not yet specified)
"Result produced" for phases 3–13 is an open item (§17) — the 2026-07-17 revision specified deliverables, not results; do not backfill result descriptions before the phase is actually implemented (§11: never hand-assign what should be derived).
Phases 1–9 (of the revised numbering) run under calibration_status: provisional, until Phase 9's measured-ROC integration flips it. That is by design. Expect band_cap = MED results wherever a detector's ROC does not clear TPR ≥ 1−β — that is the weak-detector cap working as designed. Report them.
Each phase ends with a working repository. Never leave a partial system.

15. Never do these

Introduce mutable shared evidence state. Manager().dict() is deleted; it is not coming back.
Let the enforcer produce evidence about itself.
Claim a T5 bound that depends on pi() under forgery.
Hand-assign a confidence or threshold value.
Readmit prev_hash, trust_level, or confidence to a statement.
Put floats or nulls in signed bytes.
Let the enforcer read any field outside the five in §6.
Report the Exp 1 conformance pass as independent empirical validation.
Cherry-pick subjects in Phase 8, hand-tune thresholds, or re-run with adjusted α/β after observing AUC.
Add a component without a theorem, an experiment, and a figure.
Add OPA, a policy engine, cross-evidence consistency, ECDH-in-V1, or BFT. Each was considered and rejected with reasons in the docs.
Emit trust values from sensors or evidence producers.
Emit confidence from evidence producers.
Inject trust directly during experiments.
Frame Defense-in-Depth as the primary contribution.
Force the Enforcement Plane to generate evidence about itself.
Design claim types before measurable runtime observations exist.
Introduce security mechanisms that cannot produce measurable evidence or improve runtime assurance.


16. Future work (specified, not built)
ATECC608B attestation board; AES-CCM/ECDH radio; TEE-sealed kernel; in-path hardware ceiling MCU (the one that discharges TA1 against A_code); clinical population priors; multi-tenancy; Observer out-of-band cutoff line to the MCU disable input.

16a. The dashboard (Phase 13 — Research Dashboard, Demonstration Artifact)
The dashboard is not a research contribution. It is a research demonstration artifact. Its purpose is to visualise the runtime behaviour of the architecture and let observers watch attacks propagate through the complete system.
The dashboard should display: live EEG; signal processing; feature extraction; classification output; predicted intent; evidence producers; evidence statements; evidence timeline; trust state; trust evolution; policy decisions; runtime trust reasoning; CTPR propagation; enforcement decisions; simulated actuator behaviour; residual risk; immutable audit chain; per-stage latency; end-to-end latency; Runtime Trust Orchestrator latency; CPU; memory; throughput; attack timeline; false positives; false negatives.
The dashboard should demonstrate how evidence becomes trust, how trust becomes policy, and how policy becomes safe actuation, rather than merely displaying detector outputs.

17. Still open — the PI decides, not the implementer

α and β — SETTLED (methodology; see §20 and §28). The event model, apportionment formula, β-derivation approach, ppb representation, and Tail-Floor Rule are fixed and pre-registered (docs/OSF-PREREGISTRATION.md, not yet submitted). Illustrative budget VALUES remain a swept feasible region, not point-derived; real per-claim thresholds (including any Tail-Floor-Rule conservative floor) remain Phase 9's output, not this decision's.
Confirmation that Ceil is a prescription bound. If it means something else — hardware limit, regulatory cap, safety-case artifact — the Env table and Figure [T5] must be redone before the enforcement plane is written.
The dependency DAG beyond FSI→{Signal, Model}.
Dataset — SETTLED (BCIC IV 2a, see dataset entry, §17a).
Attack-simulation protocol — gates Phase 11.

17a. Settled decisions (moved out of §17 once resolved)

Primary dataset — BCI Competition IV Dataset 2a. SETTLED.
Access via MOABB (Mother of All BCI Benchmarks), using its standardized preprocessing and evaluation pipeline.
9 subjects, 22 EEG channels, 250 Hz, 4 motor-imagery classes, cross-session (train/eval on separate sessions).
Reproducibility (mandatory, enforced in the manifest): pin the MOABB dataset version, the resolved download mirror URL, and a per-file SHA-256 of every downloaded file, all recorded in the run manifest per §13. A hash mismatch at load time must fail closed, not warn — the same discipline as the six config hashes. "MOABB default" is not a pin; the resolved URL and file hashes are.
Rationale: cross-session structure makes replay detection non-trivial (a replayed epoch from an earlier session is valid EEG and must be caught on freshness/provenance, not signal plausibility); canonical, widely-benchmarked corpus; standardized MOABB evaluation supports independent reproduction.
Scope guard: 2a is nine healthy adults. The classifier is a substrate for runtime measurement, not a performance claim — its decoding accuracy is explicitly not a result, and Phase 9 reports the per-claim ROC distribution with no success criterion on AUC. This dataset supports no clinical-relevance claim; venue target remains CPS/security, not a clinical journal.


18. Conservative evolution protocol
Redesign only when implementation or validation demonstrates necessity. Every change requires a written record: justification, trade-off, impact on threat model / theorems / experiments / dissertation chapters. Escalate to the PI before changing anything in §3 (threat model), §4 (policy), §6 (enforcement), or §9 (crypto rules). Elegance is never sufficient justification.


20. α and β — final SBA (Session Budget Allocation) methodology (supersedes the provisional §17 entry)

Event model. A spurious session restriction is counted as an episode: a maximal run of below-Normal verdicts, with adjacent runs merged under a pre-committed debounce rule D = the 5th percentile of the measured inter-restriction gap distribution (smallest D such that ≥5% of measured gaps are ≤ D), fixed before assessing whether merging changes representability. The naive per-window formulation (windows treated as independent Bernoulli trials) is empirically falsified, not merely disfavoured: real honest-operation continuous EEG across 3 subjects (BCIC IV 2a, session E) measured lag-1 autocorrelation of the restriction indicator at 0.67–0.82 and restricted-run lengths 3–31× the length an independent-draw process would produce, for both Signal and Calibration claims at both tested operating points. See docs/EVENT-MODEL-INVESTIGATION.md for the full falsification protocol and results.

α. Swept over three illustrative session-availability budgets B ∈ {0.1%, 1%, 5% per 8h}, reported as a feasible region rather than a point value. These are illustrative research parameters, not deployment requirements — this project has no target clinical deployment or stakeholder to source a budget from (§28), the same status the reference Env/Ceil values in §14 already carry. Each budget is apportioned to per-claim α via the flat formula (α applied unmodified per claim, undiscounted for CTPR propagation): proven exact, not assumed, for the deployed DAG by exhaustive 729-combination enumeration (docs/PHASE8.5-SBA-VALIDATION.md) — CTPR has zero effect on P(Verdict=Safe) under same-severity propagation, which covers every edge in the current DAG (FSI→Signal, FSI→Model). The propagation-aware correction (ancestor-closure formula, already derived) is shelved, not discarded: it must be re-applied if any future CTPR edge runs from a lenient parent to a strict child — the one topology that breaks the exactness proof. Representation: eis.v1 (ppb, below) is required before any of these budgets' derived per-claim α is representable at all; eis.v0's basis-point scale cannot hold any of them (docs/EVENT-MODEL-INVESTIGATION.md §4).

β. Per-dimension (strict dimensions and the lenient dimension, Device, derived separately), consequence-exposure-derived rather than globally hand-set. A PFD_enforcement (probability of failure on demand of the enforcement path) basis is rejected: deterministic enforcement has no probability of failure on demand under A_data — P(x ⊓ Ceil > Ceil) = 0 exactly, by the meet axiom underlying T5, not by measurement — so a PFD-style β would be circular and would additionally imply an unclaimed SIL rating (§1: "Never claimed: ... SIL certification"). If the underlying consequence-exposure budget is itself unsourced (no clinical/engineering standard to anchor it to, the same gap α's session-availability budget has), it receives the identical illustrative-sweep treatment as α — a feasible region, not a point value.

Note (methodological contribution, not implementation detail): deriving β from a consequence-exposure budget is possible only because T5 severs β from the hazard probability — the enforcement bound holds regardless of β, so β can be set from consequence exposure without β itself having to certify safety. A system without T5's independent consequence bound could not derive β this way; it would need β to BE the safety case, which is exactly the SIL-certification claim this project explicitly disclaims.

Representation. Thresholds, α, and β are carried in the ppb-scaled config format (config/eis.v1.json, eis_schema_version 1), proven sufficient with margin across all 18 (subject × claim × budget) combinations measured by the event-model investigation (minimum margin 130×; none of the 18 are representable at eis.v0's basis-point scale). This is a representation-only change: config/eis.v0.json is untouched, roc_config_hash and the interpretation-layer formula are unchanged in effect, and the wire/signed-statement/crypto path (§8, §9) is byte-identical before and after — confirmed by source hash and AST inspection, not asserted.

ROC-estimability and the Tail-Floor Rule. Before Phase 9 derives any real threshold, a dedicated diagnostic (docs/ROC-ESTIMABILITY-DIAGNOSTIC.md) measured — never assumed — whether each claim's ROC is stably estimable on the intended held-out cohort {subjects 4–9} versus the full 9-subject pool, using class-support / bootstrap-band-width / leave-one-subject-out criteria with the same ephemerality discipline as everywhere else in this section (no threshold or FPR/TPR location is ever computed outside a private, unexported helper — verified by mutation testing, not asserted by convention alone). Result: Model, Device, and FSI are sufficient on the held-out cohort (their two-factor-AND integrity checks separate cleanly; Device and FSI are protocol-level and subject-invariant by construction, disclosed as such rather than presented as independent per-subject variability). Signal and Calibration are not: Signal passes class separation and band-width ratio but fails leave-one-subject-out stability at the tail (a single held-out subject's removal swings the estimate across the full possible range, and the full 9-subject pool is equally unstable there — a sample-size floor, not a cohort-composition fix). Calibration fails class support even at the full 9-subject pool (5 of 9 subjects show genuine drift separation under the cross-subject-mismatch attack, below the 6-of-9 floor the held-out cohort's 4-of-6 bar scales to) — adding subjects 1–3 helped (2 of 3 separate) but did not clear the bar, so Calibration does not get a clean cohort-size resolution and falls under the Tail-Floor Rule alongside Signal, not instead of it.

Tail-Floor Rule (final text, pre-registered alongside the rest of this section). Evaluated independently per (claim, budget) pair across the three swept budgets {0.1%, 1%, 5% per 8h}. A claim's threshold (θ1 or θ2) at a given budget triggers the Tail-Floor Rule when its operating point fails to be stably resolvable by these fixed bars: fewer than 4/6 (equiv. 6/9 at full pool) subjects separating both classes at that point, OR bootstrap band-width ratio > 2× vs. the full-pool reference, OR leave-one-subject-out swing > 0.15. When triggered, the threshold is set to the most extreme empirically resolvable operating point (tightest stably-supported point the ROC reaches under these bars) and no tighter, reported as a conservative floor ("no tighter than X"), not a point estimate, with the sub-resolution region disclosed. No parametric tail model is fitted. Triggering at one budget does NOT imply floor treatment at a looser budget for the same claim — each (claim, budget) pair is evaluated on its own. The rule applies identically to θ1 (low-FPR end) and θ2 (high-TPR/1−β end); for any claim whose θ2 reaches TPR ≥ 1−β only within a tail region failing these bars, θ2 falls under the rule with the same disclosure. Justification: (a) no distributional assumption is introduced; (b) it fails in the conservative direction — it cannot manufacture a permissive threshold by extrapolating into unmeasured tail, consistent with the architecture's fail-closed / missing-claim-reads-LOW discipline (§10).

Measured resolution note, not assumed (this section's own diagnostic discipline applied to itself). The diagnostic's real per-subject trial counts (~280/subject, ~2,500 pooled at full-9) place even the loosest swept budget's implied operating region roughly 30× below the smallest empirically resolvable rate (~1/N_pooled). Concretely: the Tail-Floor Rule's trigger, as actually measured for Signal and Calibration, does not currently differentiate by budget — it fires at all three swept budgets {0.1%, 1%, 5%} for both claims, not only the tightest. A budget-differentiated result would require continuous per-window-granularity attack-class data (tens of thousands of windows/subject, the same order of magnitude docs/EVENT-MODEL-INVESTIGATION.md's honest-operation measurement used), which does not yet exist for either claim's attack condition. Do not assume finer granularity would relax the looser budgets before it is actually measured (docs/ROC-ESTIMABILITY-DIAGNOSTIC.md §5).

Per-claim cohort and disclosure. Model, Device, FSI: held-out {4–9}, sufficient. Signal, Calibration: full 9-subject pool; both fall under the Tail-Floor Rule at all three swept budgets per the measured-resolution note above, not a per-budget split. ActuationFidelity: not assessed by this diagnostic (no offline per-subject measurement exists for it under honest, no-live-enforcement-loop operation). Every θ1/θ2 Phase 9 derives under the Tail-Floor Rule carries a resolution_status label (pending | stable | tail_floor), per claim per swept budget, recorded in config/eis.v1.json and therefore covered by roc_config_hash — one of §8's existing six config hashes, unmodified in shape: no new field was added to the Statement or Verdict wire schema, and resolution_status is consulted by nobody in π's call path. It is not silently editable either: changing it changes roc_config_hash exactly as changing a threshold or a scale would (§8: "editing a threshold, a scale, or rotating a key silently reinterprets all history... replay stops being hermetic" — resolution_status now carries that same protection, not an exemption from it). This is the estimation-vs-representation distinction, kept separate throughout this work: eis.v1's ppb scale (above) resolves whether a value CAN be represented; the Tail-Floor Rule addresses whether it CAN be estimated from available data — two different limits, not one.

Feasibility-region values and any Tail-Floor-Rule-derived threshold value remain outputs of Phase 9, not pre-registered by this section — only the methodology (event model, apportionment, β derivation, ppb representation, and the Tail-Floor Rule) is fixed here.

Pre-registration: docs/OSF-PREREGISTRATION.md (draft, not submitted). §13's rule applies: a git timestamp is not pre-registration.


28. Scope guard — illustrative budgets and the absence of a clinical stakeholder

The session-availability budget governing α, the consequence-exposure budget governing β, and any Tail-Floor-Rule conservative floor (§20) are illustrative research parameters rather than deployment requirements. In the absence of a target clinical deployment or stakeholder, illustrative budget values are evaluated parametrically — swept over a feasible region — in the same manner as the reference Env/Ceil values in §14. The methodology for deriving α and β from a budget, including the Tail-Floor Rule's conservative-floor treatment where a threshold is not stably estimable (§20), is what is pre-registered (docs/OSF-PREREGISTRATION.md), not any particular budget value or floor value; adopting this architecture for a specific deployment requires sourcing real budgets from that deployment's clinical/engineering stakeholders and re-running the same, already-fixed, methodology.


## Environment & Workspace Rules

- Never create, expose, or reference paths, folders, filenames, variables, or artifacts containing the names "Claude", "Anthropic", or any Claude-specific workspace identifiers.
- Never use temporary directories such as `/tmp/claude-*` or include Claude-generated UUIDs in commands, examples, logs, or documentation.
- Use project-relative paths (e.g., `./trust_kernel/`, `./tests/`, `./artifacts/`) or generic paths (e.g., `/tmp/project/`) instead.
- All generated commands, scripts, and documentation must be tool-agnostic and reproducible on any machine.
- Do not expose internal workspace structure or execution environment in outputs.
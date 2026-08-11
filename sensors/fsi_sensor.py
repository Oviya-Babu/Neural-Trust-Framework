"""FSI (Firmware/Software Integrity) evidence producer (CLAUDE.md §2, §3,
§10, Phase 8 Step 3).

Per config/claim_registry.json's fsi.provisional_v0 entry:
measurement_source=EMULATED_PROTOCOL, host_independence=SAME_HOST,
forgeable_under_A_code=TRUE. The TPM operations are real (real swtpm
emulator speaking the real TPM 2.0 command interface, real tpm2-tools
PCR-extend/AIK-creation/quote/checkquote, sensors/fsi_swtpm.py) -- it is
EMULATED_PROTOCOL because swtpm is a software emulation of the TPM chip,
not a discrete hardware root of trust, and because everything here runs
on the same host under test.

CLAUDE.md §3's Position A is explicit and must not be softened by this
module's existence: "Position A (locked): all evidence including FSI is
software-forgeable in V1. CTPR therefore provides no adversarial bound in
V1. T5 rests entirely on enforcement-plane termination." This producer
demonstrates the protocol logic (a real quote is verified, real attacks
against the protocol are caught) under honest operation and against an
A_data that has not compromised this host -- it does not and cannot
discharge TA1's writability clause against A_code (CLAUDE.md §3's TA1
table: only a hardware root of trust does that, §16 future work).

Boot-time-only scope (also load-bearing, not a caveat to skip past): the
PCR extend happens once, at simulated "boot" (SwtpmSession.pcr_extend,
called once per session in provision_fsi_baseline below). Every quote
this producer verifies afterward attests to that one boot-time
measurement, not to anything about the process's behaviour since boot.
An attacker who achieves code execution after boot (A_code, §3) can act
freely without ever touching a PCR, and this producer would keep reporting
FSI_TRUST_CEIL. This is exactly config/claim_registry.json's
fsi.provisional_v0 provenance_note: "boot-time only -- it attests
firmware/software state as measured at boot, not ongoing runtime
execution."

Runtime component: a per-window quote-verification check against a
baseline PCR value pinned at provisioning (boot) time.
Runtime measurement, two independent checks combined:
  1. sig_and_nonce_ok (sensors/fsi_swtpm.py's checkquote): does the quote's
     signature verify under the pinned AIK public key, and does its
     qualifying data match the nonce this specific window expects (the
     TPM2 mechanism that makes a quote non-replayable across windows).
  2. pcr_matches_baseline: does the PCR value reported *inside this
     quote* equal the value pinned at provisioning -- checked by this
     module, not by tpm2_checkquote, which has no notion of "the value we
     expect."
Mathematical calculation: raw_measurement = FSI_TRUST_CEIL if
(sig_and_nonce_ok AND pcr_matches_baseline) else FSI_TRUST_FLOOR -- same
two-factor-AND reasoning as Model's and Device's integrity checks
(sensors/model_sensor.py, sensors/device_sensor.py): a validly-signed
quote reporting the wrong PCR value is exactly as untrustworthy as an
invalid signature, because either means the current boot-time state is
not provably the one that was measured and pinned.
measurement units: dimensionless trust extreme, fixed-point int in
{FSI_TRUST_FLOOR, FSI_TRUST_CEIL}.
claim type: fsi.provisional_v0. trust dimension: FSI.
timestamp/provenance: caller-supplied window_id/claimed_at.
expected polarity: +1 (higher raw = more trustworthy, per config/eis.v0.json).
window binding: the PCR baseline is fixed per boot (session); the nonce
and therefore the quote is fresh per window this producer is asked to
attest to -- see FsiSensor.build_statement.
smoothing: none.
attacks influencing this measurement: replayed quote (§3) -- a stale
quote from an earlier window re-presented against the current window's
nonce: caught by checkquote's nonce validation (sig_and_nonce_ok=False).
PCR mismatch -- the measured boot state diverges from the pinned baseline
(firmware modification, §3, that changed what got measured into the PCR
at boot): caught by this module's baseline comparison
(pcr_matches_baseline=False), NOT by tpm2_checkquote itself. Missing quote
-- if no quote can be produced/obtained for a window, this producer emits
nothing (§10's sensor contract: "a sensor that cannot measure emits
nothing"), which the kernel then reads as LOW via absence, not via this
module returning a synthetic low value.

CTPR (CLAUDE.md §4): FSI is the parent in CTPR's two edges (FSI->Signal,
FSI->Model). This producer's honest-evidence-conditional nature is exactly
why: "effective_child = meet(child, g(FSI_level))" only means something
under honest operation -- Position A already states FSI provides no
adversarial bound, so CTPR propagation through this producer's output is
itself honest-evidence-conditional, consistent with T4/T5's partition, not
an exception to it.

No confidence is computed here (§2): this is a raw measurement only.
"""

from trust_kernel import schema

FSI_CLAIM_TYPE = "fsi.provisional_v0"
FSI_SOURCE_ID = "fsi_sensor_v0"
FSI_BOUNDARY = "TB2"

FSI_TRUST_FLOOR = -100
FSI_TRUST_CEIL = 100


def provision_fsi_baseline(session, boot_measurement: bytes) -> dict:
    """Boot-time-only operation (see module docstring): extends the PCR
    once with the real boot measurement, provisions the AIK, and pins the
    resulting PCR value as the baseline every subsequent quote is checked
    against. `session` is a live sensors.fsi_swtpm.SwtpmSession."""
    session.pcr_extend(boot_measurement)
    ak = session.provision_ak()
    baseline_pcr_hex = session.read_pcr()
    return {**ak, "baseline_pcr_hex": baseline_pcr_hex}


def measure_fsi_integrity(sig_and_nonce_ok: bool, pcr_matches_baseline: bool) -> int:
    ok = sig_and_nonce_ok and pcr_matches_baseline
    return FSI_TRUST_CEIL if ok else FSI_TRUST_FLOOR


def evaluate_quote(session, baseline: dict, quote: dict, expected_nonce_hex: str) -> dict:
    """Runs the two independent checks described in the module docstring
    against one produced quote, and returns their raw_measurement."""
    check = session.checkquote(baseline["ak_pub_pem"], quote, expected_nonce_hex)
    pcr_matches_baseline = quote["reported_pcr_hex"] == baseline["baseline_pcr_hex"]
    raw = measure_fsi_integrity(check["sig_and_nonce_ok"], pcr_matches_baseline)
    return {
        "sig_and_nonce_ok": check["sig_and_nonce_ok"],
        "pcr_matches_baseline": pcr_matches_baseline,
        "raw_measurement": raw,
        "checkquote_output": check["output"],
    }


class FsiSensor:
    def __init__(self, secret_key: bytes, key_id: str = FSI_SOURCE_ID, source_id: str = FSI_SOURCE_ID):
        self._secret_key = secret_key
        self.key_id = key_id
        self.source_id = source_id

    def build_statement(self, *, evaluation: dict, window_id: int, claimed_at: int) -> dict:
        """`evaluation` is evaluate_quote()'s return value -- callers that
        could not obtain a quote at all must not call this method (§10:
        a sensor that cannot measure emits nothing), so there is no
        "missing quote" branch inside build_statement itself."""
        fields = schema.build_statement(
            key_id=self.key_id, source_id=self.source_id, boundary=FSI_BOUNDARY,
            claim_type=FSI_CLAIM_TYPE, raw_measurement=evaluation["raw_measurement"],
            window_id=window_id, claimed_at=claimed_at,
        )
        return schema.sign_statement(self._secret_key, fields)

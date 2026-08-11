"""Software TPM (swtpm) lifecycle + tpm2-tools wrappers for
sensors/fsi_sensor.py (Phase 8 Step 3). Drives the real swtpm emulator and
real tpm2-tools binaries -- genuine PCR-extend/quote/AIK operations
against a real (emulated) TPM 2.0 command interface over its actual wire
protocol, not a hand-rolled stand-in.

Kept separate from fsi_sensor.py so that module's docstring can stay
focused on the measurement contract rather than swtpm process/socket
plumbing.
"""

import os
import re
import socket
import subprocess
import tempfile
import time

PCR_INDEX = 16  # TCG-reserved "debug"/non-production PCR slot, standard choice for a test/demo measurement, distinct from the production boot-measurement PCRs (0-7).
HASH_ALG = "sha256"

SWTPM_STARTUP_WAIT_S = 0.5
TPM2_TIMEOUT_S = 10.0

_PCR_VALUE_RE_TEMPLATE = r"{pcr}:\s*0x([0-9A-Fa-f]+)"


class Tpm2CommandError(RuntimeError):
    """Raised when a tpm2-tools command that is expected to succeed (e.g.
    provisioning) fails. Verification-path commands (checkquote) instead
    return their exit code/output for the caller to interpret -- a quote
    that fails to verify is an expected outcome under attack, not a bug."""


def _port_is_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _free_adjacent_port_pair(max_attempts: int = 20) -> tuple:
    """libtss2-tcti-swtpm derives the control-channel port as
    data-port + 1 by convention (matching the standard 2321/2322 swtpm
    example) and exposes no separate config key for it -- so both ports
    must be free, adjacent, and it is the data port we pass to
    --server/-tcti while port+1 goes to --ctrl."""
    for _ in range(max_attempts):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        candidate = s.getsockname()[1]
        s.close()
        if _port_is_free(candidate + 1):
            return candidate, candidate + 1
    raise Tpm2CommandError("could not find a free adjacent TCP port pair for swtpm")


def extract_pcr_hex(tool_output: str, pcr_index: int = PCR_INDEX) -> str:
    """Pulls the PCR hex digest out of tpm2_pcrread/tpm2_quote's text
    output (both print a 'sha256:\\n  <idx>: 0x<hex>' block)."""
    m = re.search(_PCR_VALUE_RE_TEMPLATE.format(pcr=pcr_index), tool_output)
    if m is None:
        raise Tpm2CommandError(f"could not find PCR {pcr_index} value in tool output:\n{tool_output}")
    return m.group(1).lower()


class SwtpmSession:
    """Context manager: starts a fresh swtpm instance with its own state
    dir and TCP ports, runs tpm2_startup, and terminates the emulator (and
    cleans up its state dir) on exit. One session models one device's TPM
    across its boot lifetime for the duration of a test/demo run."""

    def __init__(self):
        self._tmpdir = None
        self._proc = None
        self.workdir = None
        self.env = None

    def __enter__(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.workdir = self._tmpdir.name
        state_dir = os.path.join(self.workdir, "tpmstate")
        os.makedirs(state_dir, exist_ok=True)
        server_port, ctrl_port = _free_adjacent_port_pair()
        self._proc = subprocess.Popen(
            ["swtpm", "socket", "--tpmstate", f"dir={state_dir}",
             "--ctrl", f"type=tcp,port={ctrl_port}",
             "--server", f"type=tcp,port={server_port}",
             "--tpm2", "--flags", "not-need-init"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        time.sleep(SWTPM_STARTUP_WAIT_S)
        self.env = dict(os.environ)
        self.env["TPM2TOOLS_TCTI"] = f"swtpm:host=localhost,port={server_port}"
        rc, out = self.run(["tpm2_startup", "-c"])
        if rc != 0:
            raise Tpm2CommandError(f"tpm2_startup failed:\n{out}")
        return self

    def __exit__(self, *exc):
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            if self._proc.stdout is not None:
                self._proc.stdout.close()
        if self._tmpdir is not None:
            self._tmpdir.cleanup()

    def run(self, args, timeout=TPM2_TIMEOUT_S):
        result = subprocess.run(
            args, cwd=self.workdir, env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
        )
        return result.returncode, result.stdout.decode(errors="replace")

    def pcr_extend(self, measurement: bytes, pcr_index: int = PCR_INDEX):
        """Boot-time measurement extend: real tpm2_pcrextend over the real
        (emulated) TPM's PCR-extend command, hashing `measurement` first
        since tpm2_pcrextend takes a digest, not raw bytes to hash itself."""
        import hashlib
        digest_hex = hashlib.sha256(measurement).hexdigest()
        rc, out = self.run(["tpm2_pcrextend", f"{pcr_index}:{HASH_ALG}={digest_hex}"])
        if rc != 0:
            raise Tpm2CommandError(f"tpm2_pcrextend failed:\n{out}")

    def read_pcr(self, pcr_index: int = PCR_INDEX) -> str:
        rc, out = self.run(["tpm2_pcrread", f"{HASH_ALG}:{pcr_index}"])
        if rc != 0:
            raise Tpm2CommandError(f"tpm2_pcrread failed:\n{out}")
        return extract_pcr_hex(out, pcr_index)

    def provision_ak(self) -> dict:
        """Creates an Endorsement Key then an Attestation Identity Key
        (AIK) under it -- once per device lifetime, like a real TPM's
        identity provisioning. Returns paths to the AK's public key (PEM,
        for external verifiers) and context (for this session's own later
        quote calls)."""
        ek_ctx = os.path.join(self.workdir, "ek.ctx")
        ak_ctx = os.path.join(self.workdir, "ak.ctx")
        ak_pub_tpm = os.path.join(self.workdir, "ak.pub")
        ak_pub_pem = os.path.join(self.workdir, "ak_pub.pem")

        rc, out = self.run(["tpm2_createek", "-c", ek_ctx, "-G", "rsa", "-u", os.path.join(self.workdir, "ek.pub")])
        if rc != 0:
            raise Tpm2CommandError(f"tpm2_createek failed:\n{out}")
        self.run(["tpm2_flushcontext", "-t"])

        rc, out = self.run([
            "tpm2_createak", "-C", ek_ctx, "-c", ak_ctx, "-u", ak_pub_tpm,
            "-G", "rsa", "-g", HASH_ALG, "-s", "rsassa",
        ])
        if rc != 0:
            raise Tpm2CommandError(f"tpm2_createak failed:\n{out}")
        self.run(["tpm2_flushcontext", "-t"])

        rc, out = self.run(["tpm2_readpublic", "-c", ak_ctx, "-f", "pem", "-o", ak_pub_pem])
        if rc != 0:
            raise Tpm2CommandError(f"tpm2_readpublic failed:\n{out}")

        return {"ak_ctx": ak_ctx, "ak_pub_tpm": ak_pub_tpm, "ak_pub_pem": ak_pub_pem}

    def quote(self, ak_ctx: str, nonce_hex: str, pcr_index: int = PCR_INDEX) -> dict:
        """Produces a real TPM2 quote (signed attestation over the current
        PCR value and the supplied nonce/qualifying-data). Returns file
        paths plus the PCR hex reported *in this quote* (extracted from
        tpm2_quote's own stdout, so it is exactly what the signature
        covers)."""
        msg = os.path.join(self.workdir, f"quote_msg_{nonce_hex[:8]}.bin")
        sig = os.path.join(self.workdir, f"quote_sig_{nonce_hex[:8]}.bin")
        pcrs = os.path.join(self.workdir, f"quote_pcrs_{nonce_hex[:8]}.bin")
        rc, out = self.run([
            "tpm2_quote", "-c", ak_ctx, "-l", f"{HASH_ALG}:{pcr_index}",
            "-q", nonce_hex, "-m", msg, "-s", sig, "-o", pcrs, "-g", HASH_ALG,
        ])
        # swtpm's transient-object slot count is small; tpm2_quote loads
        # ak_ctx into a fresh slot on every call and never frees it itself,
        # so a session that quotes more than a couple of times without this
        # flush eventually fails with "out of memory for object contexts".
        self.run(["tpm2_flushcontext", "-t"])
        if rc != 0:
            raise Tpm2CommandError(f"tpm2_quote failed:\n{out}")
        return {
            "msg_path": msg, "sig_path": sig, "pcrs_path": pcrs,
            "reported_pcr_hex": extract_pcr_hex(out, pcr_index),
            "nonce_hex": nonce_hex,
        }

    def checkquote(self, ak_pub_pem: str, quote: dict, expected_nonce_hex: str) -> dict:
        """Verifies signature + nonce (qualifying data) via real
        tpm2_checkquote. Does NOT itself judge whether the reported PCR
        value matches any expectation -- that is a policy/baseline
        comparison the caller (fsi_sensor.py) makes, since tpm2_checkquote
        has no notion of 'the value we expect', only 'is this quote
        internally consistent and signed by this key'."""
        rc, out = self.run([
            "tpm2_checkquote", "-u", ak_pub_pem, "-m", quote["msg_path"],
            "-s", quote["sig_path"], "-f", quote["pcrs_path"], "-g", HASH_ALG,
            "-q", expected_nonce_hex,
        ])
        return {"sig_and_nonce_ok": rc == 0, "output": out}

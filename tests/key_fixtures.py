"""Demo/test key material for Phase 3 (T4 statement admission + verdict
issuance). Provisional -- CLAUDE.md §6 describes real key provisioning as
out-of-band; there is no real hardware sensor fleet yet (that lands with
the sensors/observer work in later phases), so secret keys here are
deterministically derived from named seeds rather than genuinely
provisioned. config/key_registry.json holds only the resulting PUBLIC
keys, which is what a real registry would hold.

Not imported by trust_kernel/ or config/ -- this is test/experiment
fixture material, not part of the runtime path.
"""

import hashlib

from trust_kernel import sign

SOURCE_IDS = (
    "signal_sensor_v0", "model_sensor_v0", "calibration_sensor_v0",
    "device_sensor_v0", "fsi_sensor_v0", "actuationfidelity_sensor_v0",
)
KERNEL_SOURCE_ID = "kernel_v0"


def _seed_for(name: str) -> bytes:
    return hashlib.sha256(f"CLAUDE.md-phase3-demo-key-seed:{name}".encode()).digest()


def keypair_for(name: str):
    return sign.keypair_from_seed(_seed_for(name))


def sensor_keypairs():
    return {name: keypair_for(name) for name in SOURCE_IDS}


def kernel_keypair():
    return keypair_for(KERNEL_SOURCE_ID)

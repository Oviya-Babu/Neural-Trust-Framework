"""Capability-gated actuator write authority (CLAUDE.md §6, §2 P4). A single
unforgeable token is the sole authority to emit a command; it is held only
by the enforcer. "Rejected/failed verdict ⇒ no token presented ⇒ no
actuator write" -- clamp.accept_and_clamp() produces no envelope at all for
a rejected verdict (§6: EnforcementDecision.envelope is None), so the
top-level driver has nothing to present the capability with, and the
actuator write simply never happens. This module does not itself decide
accept/reject; it only refuses to write in the absence of the correct
capability object, regardless of why.

Models P4 (least privilege): the actuator writer holds no reasoning
capability, and nothing except the process holding ActuatorCapability can
cause SimulatedActuator.history to grow.
"""

import os


class CapabilityError(ValueError):
    pass


class ActuatorCapability:
    """The sole actuator-write authority token (§6). Modelled as object
    identity, not a bearer secret compared by value -- write() checks `is`,
    so even a byte-for-byte copy of another capability's token is refused;
    only the exact object issued to the enforcer authorises a write."""

    def __init__(self):
        self._token = os.urandom(32)


class SimulatedActuator:
    """CLAUDE.md §2: 'Enforcement Plane -- dumb, capability-gated actuator
    writer. Produces no evidence about itself.' Records only the commands it
    was actually authorised to accept; there is no path to append to
    history without presenting the exact capability object this actuator
    was constructed with."""

    def __init__(self, capability: ActuatorCapability):
        self._capability = capability
        self.history: list = []

    def write(self, capability: ActuatorCapability, command: dict):
        if capability is not self._capability:
            raise CapabilityError("actuator write refused: capability not presented")
        self.history.append(dict(command))

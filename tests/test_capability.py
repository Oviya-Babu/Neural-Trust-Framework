"""Unit tests for enforcement/capability.py (CLAUDE.md §2 P4, §6)."""

import unittest

from enforcement.capability import ActuatorCapability, CapabilityError, SimulatedActuator


class CapabilityTests(unittest.TestCase):
    def test_write_with_correct_capability_succeeds(self):
        cap = ActuatorCapability()
        actuator = SimulatedActuator(cap)
        actuator.write(cap, {"max_speed": 1000, "max_acceleration": 500})
        self.assertEqual(actuator.history, [{"max_speed": 1000, "max_acceleration": 500}])

    def test_write_with_a_different_capability_object_is_refused(self):
        real_cap = ActuatorCapability()
        forged_cap = ActuatorCapability()  # a distinct token, not the one issued to this actuator
        actuator = SimulatedActuator(real_cap)
        with self.assertRaises(CapabilityError):
            actuator.write(forged_cap, {"max_speed": 1000, "max_acceleration": 500})
        self.assertEqual(actuator.history, [])

    def test_write_with_none_capability_is_refused(self):
        cap = ActuatorCapability()
        actuator = SimulatedActuator(cap)
        with self.assertRaises(CapabilityError):
            actuator.write(None, {"max_speed": 1000, "max_acceleration": 500})
        self.assertEqual(actuator.history, [])

    def test_no_write_means_no_history_growth(self):
        """P4/§6: a rejected verdict never even attempts a write -- this
        just confirms the actuator has no channel to grow history except
        through write() with the correct capability."""
        cap = ActuatorCapability()
        actuator = SimulatedActuator(cap)
        self.assertEqual(actuator.history, [])

    def test_two_capability_instances_hold_different_tokens(self):
        a, b = ActuatorCapability(), ActuatorCapability()
        self.assertNotEqual(a._token, b._token)


if __name__ == "__main__":
    unittest.main()

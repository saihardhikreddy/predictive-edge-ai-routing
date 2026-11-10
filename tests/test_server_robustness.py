import contextlib
import io
import json
import unittest

from digital_twin_server import DigitalTwinServer


class ServerRobustnessTests(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.server = DigitalTwinServer()

    async def _send(self, payload):
        msg = payload if isinstance(payload, str) else json.dumps(payload)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            await self.server.handle_client_action(msg)

    async def test_malformed_json_does_not_raise(self):
        await self._send("{not json")
        self.assertFalse(self.server.engine.is_paused)

    async def test_unknown_action_is_ignored(self):
        mode = self.server.engine.protocol_mode
        await self._send({"action": "self_destruct"})
        self.assertEqual(self.server.engine.protocol_mode, mode)

    async def test_unknown_protocol_mode_is_rejected(self):
        await self._send({"action": "set_protocol_mode", "mode": "FLOODING"})
        await self._send({"action": "set_protocol_mode", "mode": "TELEPATHY"})
        self.assertEqual(self.server.engine.protocol_mode, "FLOODING")
        await self._send({"action": "set_protocol_mode", "mode": "marl"})
        self.assertEqual(self.server.engine.protocol_mode, "MARL")

    async def test_speed_is_clamped(self):
        await self._send({"action": "set_speed", "speed": 100})
        self.assertEqual(self.server.engine.simulation_speed, 8.0)
        await self._send({"action": "set_speed", "speed": 0})
        self.assertEqual(self.server.engine.simulation_speed, 0.25)

    async def test_bad_speed_value_keeps_previous_speed(self):
        await self._send({"action": "set_speed", "speed": 2})
        await self._send({"action": "set_speed", "speed": "fast"})
        self.assertEqual(self.server.engine.simulation_speed, 2.0)


if __name__ == "__main__":
    unittest.main()


class ServerInputTypeTests(unittest.IsolatedAsyncioTestCase):
    """Values whose JSON type isn't the one the handler expects."""

    setUp = ServerRobustnessTests.setUp
    _send = ServerRobustnessTests._send

    async def test_non_object_json_is_ignored(self):
        for msg in ("[1, 2]", "42", "null"):
            await self._send(msg)
        self.assertFalse(self.server.engine.is_paused)

    async def test_nan_speed_keeps_previous_speed(self):
        await self._send({"action": "set_speed", "speed": 2})
        await self._send({"action": "set_speed", "speed": "nan"})
        self.assertEqual(self.server.engine.simulation_speed, 2.0)

    async def test_scenario_id_given_as_text_still_runs(self):
        await self._send({"action": "run_scenario", "scenario_id": "1"})
        self.assertEqual(self.server.engine.protocol_mode, "FLOODING")
        await self._send({"action": "run_scenario", "scenario_id": "two"})
        self.assertEqual(self.server.engine.protocol_mode, "FLOODING")

    async def test_only_a_real_true_marks_a_chat_as_sos(self):
        seen = []
        self.server.engine.trigger_message = lambda s, d, is_emergency: seen.append(is_emergency)
        for value in ("false", 1, True):
            await self._send({"action": "trigger_chat", "is_emergency": value})
        self.assertEqual(seen, [False, False, True])

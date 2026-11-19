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


class ServerBindingTests(unittest.IsolatedAsyncioTestCase):
    """Both servers listen on this machine only unless --host says otherwise."""

    async def _bound_hosts(self, *args):
        from unittest import mock

        import digital_twin_server as dts

        seen = {}

        class FakeServe:
            def __init__(self, handler, host, port, origins=None):
                seen["ws"] = (host, port)
                seen["origins"] = origins

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        class FakeThread:
            def __init__(self, target, args=(), daemon=None):
                seen["http"] = args

            def start(self):
                pass

        async def no_loop(self):
            return None

        with mock.patch.object(dts.websockets, "serve", FakeServe), \
                mock.patch.object(dts.threading, "Thread", FakeThread), \
                mock.patch.object(dts.DigitalTwinServer, "broadcast_loop", no_loop), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            await dts.main(*args)
        return seen, out.getvalue()

    async def test_default_is_this_machine_only(self):
        import digital_twin_server as dts

        self.assertEqual(dts.parse_args([]).host, "127.0.0.1")
        seen, out = await self._bound_hosts()
        self.assertEqual(seen["ws"], ("127.0.0.1", dts.WS_PORT))
        self.assertEqual(seen["http"], ("127.0.0.1",))
        self.assertIn(f"http://localhost:{dts.HTTP_PORT}", seen["origins"])
        self.assertNotIn("anyone who can reach", out)

    async def test_sharing_on_the_network_is_explicit_and_announced(self):
        import digital_twin_server as dts

        self.assertEqual(dts.parse_args(["--host", "0.0.0.0"]).host, "0.0.0.0")
        seen, out = await self._bound_hosts("0.0.0.0")
        self.assertEqual(seen["ws"][0], "0.0.0.0")
        self.assertEqual(seen["http"], ("0.0.0.0",))
        self.assertIn("anyone who can reach this machine", out)

    async def test_other_websites_cannot_open_the_control_socket(self):
        import websockets

        import digital_twin_server as dts

        async def echo(ws):
            await ws.send("hello")

        async with websockets.serve(echo, "127.0.0.1", 0, origins=dts.allowed_origins("127.0.0.1")) as srv:
            port = srv.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"
            for origin in (f"http://localhost:{dts.HTTP_PORT}", f"http://127.0.0.1:{dts.HTTP_PORT}", None):
                async with websockets.connect(url, origin=origin) as ws:   # the dashboard, or a script
                    self.assertEqual(await ws.recv(), "hello")
            for origin in ("https://evil.example", "null", "http://localhost:9999"):
                with self.assertRaises(websockets.exceptions.InvalidHandshake, msg=origin):  # HTTP 403
                    async with websockets.connect(url, origin=origin) as ws:
                        await ws.recv()
        self.assertIsNone(dts.allowed_origins("0.0.0.0"))                   # shared on purpose
        self.assertIn(f"http://192.168.1.5:{dts.HTTP_PORT}", dts.allowed_origins("192.168.1.5"))

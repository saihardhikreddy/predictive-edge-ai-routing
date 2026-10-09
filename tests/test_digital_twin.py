import unittest
import asyncio
import json
from digital_twin_server import DigitalTwinServer

class TestDigitalTwinServer(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.server = DigitalTwinServer()

    def test_initialization(self):
        self.assertIsNotNone(self.server.engine)
        self.assertEqual(len(self.server.engine.nodes), 16)
        self.assertEqual(len(self.server.connected_clients), 0)

    async def test_handle_actions(self):
        # Test pause action
        await self.server.handle_client_action(json.dumps({"action": "toggle_pause"}))
        self.assertTrue(self.server.engine.is_paused)

        # Test unpause action
        await self.server.handle_client_action(json.dumps({"action": "toggle_pause"}))
        self.assertFalse(self.server.engine.is_paused)

        # Test protocol mode change
        await self.server.handle_client_action(json.dumps({"action": "set_protocol_mode", "mode": "FLOODING"}))
        self.assertEqual(self.server.engine.protocol_mode, "FLOODING")

        await self.server.handle_client_action(json.dumps({"action": "set_protocol_mode", "mode": "MARL"}))
        self.assertEqual(self.server.engine.protocol_mode, "MARL")

    async def test_scenarios(self):
        # Scenario 1: Flooding
        await self.server.handle_client_action(json.dumps({"action": "run_scenario", "scenario_id": 1}))
        self.assertEqual(self.server.engine.protocol_mode, "FLOODING")

        # Scenario 2: MARL
        await self.server.handle_client_action(json.dumps({"action": "run_scenario", "scenario_id": 2}))
        self.assertEqual(self.server.engine.protocol_mode, "MARL")

        # Scenario 4: sinkhole attack queues a burst of traffic
        await self.server.handle_client_action(json.dumps({"action": "run_scenario", "scenario_id": 4}))
        self.assertTrue(any(n.is_sinkhole for n in self.server.engine.nodes.values()))
        self.assertGreater(len(self.server.engine.scheduled), 0)

    async def test_new_controls(self):
        e = self.server.engine
        await self.server.handle_client_action(json.dumps({"action": "toggle_slm"}))
        self.assertFalse(e.slm_toggle_on)
        await self.server.handle_client_action(json.dumps({"action": "set_speed", "speed": 4}))
        self.assertEqual(e.simulation_speed, 4.0)
        await self.server.handle_client_action(json.dumps({"action": "trigger_chat", "is_emergency": True}))
        self.assertEqual(e.summary()["marl"]["generated"], 1)
        await self.server.handle_client_action(json.dumps({"action": "toggle_pause"}))
        t = e.sim_time
        await self.server.handle_client_action(json.dumps({"action": "step"}))
        self.assertGreater(e.sim_time, t)
        self.assertTrue(e.is_paused)

    def test_snapshot_generation(self):
        snapshot = self.server.engine.get_state_snapshot()
        self.assertIn("nodes", snapshot)
        self.assertIn("edges", snapshot)
        self.assertIn("metrics", snapshot)
        self.assertEqual(len(snapshot["nodes"]), 16)

if __name__ == "__main__":
    unittest.main()

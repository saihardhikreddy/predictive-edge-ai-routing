#!/usr/bin/env python3
"""Cognitive Edge Mesh Digital Twin Server.

Single-entry executable server hosting:
1. Static HTML5 Canvas Visualizer on HTTP http://localhost:8080
2. Real-time 30-FPS Simulation State Broadcast on WebSocket ws://localhost:8765
3. Autonomous MARL Routing, Cognitive SLM, and GNN Intrusion Detection Engine.
"""

import asyncio
import http.server
import json
import os
import random
import socketserver
import sys
import threading
import traceback

import websockets

from simulation.mesh_engine import MeshSimulationEngine

HTTP_PORT = 8080
WS_PORT = 8765
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


class CustomHTTPHandler(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, format, *args):
        pass


def start_http_server():
    """Starts background HTTP server for the dashboard."""
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("", HTTP_PORT), CustomHTTPHandler) as httpd:
            print(
                f"[HTTP_SERVER] Serving Digital Twin Dashboard on http://localhost:{HTTP_PORT}"
            )
            httpd.serve_forever()
    except Exception as e:
        print(f"[HTTP_SERVER_NOTE] HTTP server on {HTTP_PORT}: {e}")


class DigitalTwinServer:

    def __init__(self, seed=None):
        self.engine = MeshSimulationEngine(node_count=16, seed=seed)
        self.connected_clients = set()
        self.running = True

    async def register(self, websocket):
        self.connected_clients.add(websocket)
        print(
            f"[WEBSOCKET] Client connected: {websocket.remote_address} (Active: {len(self.connected_clients)})"
        )
        try:
            init_state = self.engine.get_state_snapshot()
            init_state["slm_on"] = self.engine.slm_toggle_on
            init_state["is_paused"] = self.engine.is_paused
            await websocket.send(json.dumps(init_state))
            async for message in websocket:
                await self.handle_client_action(message)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.connected_clients.discard(websocket)
            print(
                f"[WEBSOCKET] Client disconnected (Active: {len(self.connected_clients)})"
            )

    async def handle_client_action(self, message: str):
        try:
            data = json.loads(message)
            action = data.get("action")

            if action == "toggle_pause":
                self.engine.is_paused = not self.engine.is_paused
                status = "PAUSED" if self.engine.is_paused else "RESUMED"
                self.engine.set_narrative(f"Simulation is now {status}.")
                self.engine.log_event("CONTROL", f"Simulation {status}")

            elif action == "step":
                was_paused = self.engine.is_paused
                self.engine.is_paused = False
                self.engine.tick(0.1)
                self.engine.is_paused = was_paused
                self.engine.log_event("CONTROL", "Manual Step Frame")

            elif action == "set_protocol_mode":
                mode = data.get("mode", "MARL")
                self.engine.protocol_mode = mode
                if mode == "FLOODING":
                    self.engine.set_narrative(
                        "🌊 PROTOCOL SWITCHED: Flooding & Flushing Mode active. Messages will explode across all neighbor links (Broadcast Storm)."
                    )
                elif mode == "MARL":
                    self.engine.set_narrative(
                        "🧠 PROTOCOL SWITCHED: Cognitive MARL Mode active. Packets routed predictively via Q-learning."
                    )
                elif mode == "COMPARISON":
                    self.engine.set_narrative(
                        "⚔️ COMPARISON MODE: Dispatches will benchmark MARL vs Flooding side-by-side."
                    )
                self.engine.log_event("MODE", f"Protocol mode set to {mode}")

            elif action == "run_scenario":
                sc_id = data.get("scenario_id", 1)
                self.engine.run_scenario(sc_id)

            elif action == "trigger_chat":
                node_keys = list(self.engine.nodes.keys())
                if len(node_keys) >= 2:
                    s, d = random.sample(node_keys, 2)
                    is_sos = data.get("is_emergency", False)
                    self.engine.trigger_message(s, d, is_emergency=is_sos)

            elif action == "reset_topology":
                self.engine.reset_topology()

            elif action == "inject_sinkhole":
                nid = data.get("node_id")
                self.engine.inject_sinkhole(nid)

            elif action == "clear_quarantine":
                self.engine.clear_quarantines()

            elif action == "toggle_slm":
                self.engine.slm_toggle_on = not self.engine.slm_toggle_on
                state = "ON" if self.engine.slm_toggle_on else "OFF"
                self.engine.set_narrative(f"Cognitive triage (SLM layer) {state}.")
                self.engine.log_event("CONTROL", f"Triage {state}")

            elif action == "set_speed":
                self.engine.simulation_speed = max(0.25, min(8.0, float(data.get("speed", 1.0))))
                self.engine.log_event("CONTROL", f"Speed x{self.engine.simulation_speed:g}")

            else:
                print(f"[ACTION_WARN] Unknown action: {action}")

        except Exception:
            print("[ACTION_ERROR] Error handling action:")
            traceback.print_exc()

    async def broadcast_loop(self):
        while self.running:
            try:
                self.engine.tick(0.033)  # no-op while paused
                if self.connected_clients:
                    snap = self.engine.get_state_snapshot()
                    snap["slm_on"] = self.engine.slm_toggle_on
                    snap["is_paused"] = self.engine.is_paused
                    snapshot = json.dumps(snap)
                    tasks = [
                        client.send(snapshot)
                        for client in list(self.connected_clients)
                    ]
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
            except Exception:
                traceback.print_exc()
            await asyncio.sleep(0.033)


async def main():
    server = DigitalTwinServer()

    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    async with websockets.serve(server.register, "0.0.0.0", WS_PORT):
        print(f"[WEBSOCKET] Serving Digital Twin state on ws://localhost:{WS_PORT}")
        print(f"[STATUS] Cognitive Edge Mesh Server running. Access UI at http://localhost:{HTTP_PORT}")
        await server.broadcast_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[SERVER] Shutting down Digital Twin Server.")

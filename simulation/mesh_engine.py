"""Cognitive Edge Mesh — simulation engine.

Everything the dashboard and the benchmark report is computed here; there are
no hard-coded result numbers. Four mechanisms, each local to a node:

1. Predictive routing (MARL, independent learners)
   Every node owns a linear Q-function  Q_x(d, a) = w_x . phi(x, a, d)  over the
   actions a in {forward to neighbour y, CARRY (store-carry-forward)}. The
   features only use what x can observe locally: neighbour beacons (battery,
   buffer, advertised delivery predictability to d), link RSSI, and x's own state.
   After a hop x -> y, y piggybacks V_y(d) = max_a Q_y(d, a) on the link-layer ACK
   and x does a TD(0) update (Q-routing, Boyan & Littman 1994, with function
   approximation). No node ever sees the global topology.

2. Mobility learning (PRoPHET-style delivery predictability)
   P_x(d) rises on every encounter, ages over time and spreads transitively.
   It is the "predictive" feature: who is likely to meet d soon.

3. Gossip federated learning
   When two nodes meet (and have not gossiped for a while) they average their
   weight vectors, weighted by local sample counts (decentralised FedAvg). Only
   7 floats move; no location, contact log or message ever leaves the device.

4. Ego-graph trust IDS (GNN-style message passing)
   Senders keep per-neighbour counters of hand-offs and end-to-end delivery
   ACKs. A node's reputation is a Beta(credited+1, handed-credited+1) mean; its
   anomaly score compares that reputation with the mean of its 1-hop ego graph.
   Nodes whose anomaly >= 0.85 with enough evidence are quarantined.

Baseline: BitChat-style TTL flooding with duplicate suppression, where one
broadcast = one transmission, every neighbour pays receive energy, and
same-slot transmissions collide at a receiver (slotted random back-off).
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import triage

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

N_FEAT = 7  # [bias, P(dest), link quality, battery, buffer, is_dest, is_carry]
FEATURE_NAMES = ["bias", "p_dest", "link_q", "battery", "buffer", "is_dest", "carry"]
# Warm-start prior == PRoPHET's GRTR rule (forward if the neighbour is more likely
# to meet d than I am). Learning then refines it.
PRIOR_W = [0.0, 7.0, 0.5, 1.0, -1.5, 10.0, -0.3]


@dataclass
class PacketAnimation:
    """One MARL copy of a message (kept under this name for UI compatibility)."""

    packet_id: str
    msg_id: str
    source_id: str
    dest_id: str
    path: List[str]
    holder: str
    created_at: float
    ttl_s: float
    payload_size_bytes: int
    intent_class: str = triage.INTENT_ROUTINE
    urgency: float = 1.0
    is_emergency: bool = False
    is_flooding: bool = False
    next_hop: Optional[str] = None
    progress: float = 0.0
    next_decision_at: float = 0.0
    hops: int = 0
    last_phi: Optional[List[float]] = None
    carry_phi: Optional[List[float]] = None
    watch: Optional[Tuple[str, str, float]] = None  # 2ACK: (prev, holder, deadline)
    completed: bool = False
    failed: bool = False
    fail_reason: str = ""

    @property
    def current_hop_idx(self) -> int:
        return len(self.path) - 2 if self.next_hop else len(self.path) - 1


@dataclass
class FloodBranch:
    branch_id: str
    from_node: str
    to_node: str
    hop_level: int
    progress: float = 0.0
    collided: bool = False
    completed: bool = False


@dataclass
class Node:
    id: str
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    target_x: float = 0.0
    target_y: float = 0.0
    battery: float = 100.0
    base_buffer: int = 10
    held_packets: int = 0
    encounter_score: int = 0
    q_table: Dict[str, Dict[str, float]] = field(default_factory=dict)
    is_sinkhole: bool = False
    is_quarantined: bool = False
    anomaly_score: float = 0.0
    packets_routed: int = 0
    acks_received: int = 0
    advertised_q: float = 0.0
    status: str = "IDLE"
    # learning state
    w: List[float] = field(default_factory=lambda: list(PRIOR_W))
    n_samples: int = 0
    P: Dict[str, float] = field(default_factory=dict)
    trust: Dict[str, List[float]] = field(default_factory=dict)  # y -> [handed, credited] (decayed)
    last_contact: Dict[str, float] = field(default_factory=dict)
    link_q: Dict[str, float] = field(default_factory=dict)  # learned per-link delivery rate (EWMA)
    last_gossip: Dict[str, float] = field(default_factory=dict)

    @property
    def buffer_occupancy(self) -> int:
        return min(100, self.base_buffer + 8 * self.held_packets)

    @property
    def alive(self) -> bool:
        return self.battery > 0.5

    def prune_peer(self, peer_id: str):
        for dest in self.q_table:
            self.q_table[dest].pop(peer_id, None)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class MeshSimulationEngine:
    # learning
    ALPHA = 0.02
    GAMMA = 0.9
    EPSILON = 0.05
    W_CLIP = 50.0
    # radio / world
    BLE_RANGE_PX = 190.0
    BOUNDS_WIDTH = 900.0
    BOUNDS_HEIGHT = 550.0
    HOP_TIME_S = 0.4
    DECISION_INTERVAL_S = 0.5
    # rewards
    REWARD_DELIVER = 10.0
    PENALTY_LINK_BREAK = -3.0
    CARRY_COST = 0.2
    # PRoPHET
    P_INIT = 0.75
    P_BETA = 0.25
    P_AGING_PER_S = 0.985
    # gossip FL
    GOSSIP_COOLDOWN_S = 30.0
    # radio: log-distance path loss calibrated so the range edge is ~-90 dBm,
    # and a logistic packet-success curve (BLE 1M PHY sensitivity ~-90..-95 dBm)
    PATHLOSS_EXP_DB = 39.0
    PSR_MID_DBM = -85.0
    PSR_SCALE_DB = 2.5
    USE_LINK_EWMA = False
    # protocol
    MARL_TTL_S = 60.0
    MAX_HOPS = 16
    SOS_COPIES = 2
    FLOOD_TTL = 7
    FLOOD_SLOTS = 8
    BEACON_INTERVAL_S = 1.0
    # IDS
    SINKHOLE_QUARANTINE_THRESHOLD = 1.0  # anomaly_score = CUSUM / CUSUM_H
    CUSUM_H = 12.0
    CUSUM_P1 = 0.2  # forwarding probability assumed for a sinkhole
    TRUST_DECAY_PER_S = 0.97  # forgetting factor of the Beta reputation
    ENCOUNTER_GAP_S = 5.0     # contact must have been broken this long to count as a new encounter
    IDS_INTERVAL_S = 1.0
    ACK2_TIMEOUT_S = 20.0
    PVEC_REFRESH_S = 10.0
    # energy (battery % per byte)
    E_TX_PER_BYTE = 0.0004
    E_RX_PER_BYTE = 0.00025

    def __init__(
        self,
        node_count: int = 16,
        seed: Optional[int] = None,
        learning_enabled: bool = True,
        federated_enabled: bool = True,
        ids_enabled: bool = True,
        auto_traffic: bool = True,
        traffic_interval_s: float = 3.5,
        warmup_s: float = 20.0,
        mobility_scale: float = 1.0,
        cold_start: bool = False,
    ):
        self.mobility_scale = mobility_scale
        self.cold_start = cold_start
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.mob_rng = random.Random(self.seed)
        self.rng = random.Random(self.seed + 1)
        self.traffic_rng = random.Random(self.seed + 2)

        self.learning_enabled = learning_enabled
        self.federated_enabled = federated_enabled
        self.ids_enabled = ids_enabled
        self.auto_traffic = auto_traffic
        self.traffic_interval_s = traffic_interval_s
        self.warmup_s = warmup_s

        self.protocol_mode: str = "MARL"
        self.slm_toggle_on: bool = True
        self.is_paused: bool = False
        self.simulation_speed: float = 1.0

        self._init_nodes(node_count)

    # ------------------------------------------------------------------ setup

    def _reset_state(self):
        self.sim_time = 0.0
        self._warming = True
        self.nodes: Dict[str, Node] = {}
        self.adj: Dict[str, Dict[str, int]] = {}
        self.edges: List[Tuple[str, str, float, int]] = []
        self.active_packets: List[PacketAnimation] = []
        self.active_flood_branches: List[FloodBranch] = []
        self.pending_acks: List[Tuple[float, Tuple[str, str]]] = []
        self.delivered_msgs: Dict[str, float] = {}
        self.msg_records: Dict[str, Dict] = {}
        self.scheduled: List[Tuple[float, Dict]] = []
        self.event_logs: List[Dict[str, str]] = []
        self.current_narrative = ""
        self._pkt_counter = 0
        self._last_beacon = 0.0
        self._last_pvec = 0.0
        self._last_ids = 0.0
        self._last_traffic = 0.0
        self.sinkhole_injection_time: Optional[float] = None
        self.ids_detection_s: List[float] = []
        self.trust_events: List[Tuple[str, bool]] = []
        self.cusum: Dict[str, float] = {}
        self.fl_rounds = 0
        self.m = {
            proto: {
                "generated": 0, "delivered": 0, "failed": 0,
                "data_tx": 0, "control_tx": 0, "data_bytes": 0, "control_bytes": 0,
                "energy": 0.0, "latencies": [], "hops": [], "collisions": 0,
                "link_breaks": 0, "sinkhole_drops": 0,
                "sos_generated": 0, "sos_delivered": 0, "sos_latencies": [],
            }
            for proto in ("marl", "flood")
        }
        self.triage_stats = {"raw_bytes": 0, "air_bytes": 0, "n": 0, "sos_raw": 0, "sos_air": 0, "sos_n": 0}

    def _init_nodes(self, count: int):
        self._reset_state()
        cols = int(math.ceil(math.sqrt(count)))
        rows = int(math.ceil(count / cols))
        cell_w = (self.BOUNDS_WIDTH - 200) / cols
        cell_h = (self.BOUNDS_HEIGHT - 160) / rows
        r = self.mob_rng
        for i in range(count):
            nid = f"Node_{i + 1:02d}"
            row, col = divmod(i, cols)
            self.nodes[nid] = Node(
                id=nid,
                x=80 + col * cell_w + r.uniform(-20, 20),
                y=70 + row * cell_h + r.uniform(-15, 15),
                vx=r.uniform(-1.5, 1.5),
                vy=r.uniform(-1.5, 1.5),
                target_x=r.uniform(60, self.BOUNDS_WIDTH - 60),
                target_y=r.uniform(60, self.BOUNDS_HEIGHT - 60),
                battery=r.uniform(88.0, 100.0),
                base_buffer=r.randint(5, 20),
                w=[0.0] * N_FEAT if self.cold_start else list(PRIOR_W),
            )
        self.update_topology()
        # Silent warm-up: nodes roam and build encounter history (no traffic).
        steps = int(self.warmup_s / 0.1)
        for _ in range(steps):
            self.sim_time += 0.1
            self.update_mobility(0.1)
            self.update_topology()
            self._age_predictability(0.1)
        self.sim_time = 0.0
        self._warming = False
        self.set_narrative(f"Initialized {count} mobile pedestrian nodes roaming across the campus mesh map.")
        self.log_event("SYSTEM", f"Initialized {count} nodes (seed {self.seed}); {self.warmup_s:.0f}s encounter warm-up done.")

    def reset_topology(self):
        self._init_nodes(len(self.nodes))
        self.set_narrative("Mesh topology reset. Fresh nodes with empty models.")

    # ---------------------------------------------------------------- logging

    def set_narrative(self, text: str):
        self.current_narrative = text

    def log_event(self, category: str, message: str):
        self.event_logs.append({"time": f"t={self.sim_time:6.1f}s", "category": category, "message": message})
        if len(self.event_logs) > 80:
            self.event_logs.pop(0)

    # ------------------------------------------------------- mobility / radio

    def update_mobility(self, dt: float):
        r = self.mob_rng
        alpha_momentum = 0.90
        speed_factor = 1.4
        for node in self.nodes.values():
            dx, dy = node.target_x - node.x, node.target_y - node.y
            dist = math.hypot(dx, dy)
            if dist < 40.0:
                node.target_x = r.uniform(70, self.BOUNDS_WIDTH - 70)
                node.target_y = r.uniform(60, self.BOUNDS_HEIGHT - 60)
            dvx = (dx / max(dist, 1.0)) * 2.2 * r.uniform(0.8, 1.2)
            dvy = (dy / max(dist, 1.0)) * 2.2 * r.uniform(0.8, 1.2)
            # Gauss-Markov steering
            node.vx = alpha_momentum * node.vx + (1 - alpha_momentum) * dvx + r.gauss(0, 0.12)
            node.vy = alpha_momentum * node.vy + (1 - alpha_momentum) * dvy + r.gauss(0, 0.12)
            spd = math.hypot(node.vx, node.vy)
            if spd > 2.8:
                node.vx, node.vy = node.vx / spd * 2.8, node.vy / spd * 2.8
            # dt is in seconds; the original UI moved ~1.4 px per 33ms frame unit
            node.x += node.vx * dt * speed_factor * self.mobility_scale
            node.y += node.vy * dt * speed_factor * self.mobility_scale
            mx, my = 50.0, 45.0
            if node.x < mx:
                node.x, node.vx = mx, abs(node.vx)
            elif node.x > self.BOUNDS_WIDTH - mx:
                node.x, node.vx = self.BOUNDS_WIDTH - mx, -abs(node.vx)
            if node.y < my:
                node.y, node.vy = my, abs(node.vy)
            elif node.y > self.BOUNDS_HEIGHT - my:
                node.y, node.vy = self.BOUNDS_HEIGHT - my, -abs(node.vy)

    def update_topology(self):
        old_adj = getattr(self, "adj", {})
        self.edges = []
        self.adj = {nid: {} for nid in self.nodes}
        ids = list(self.nodes.keys())
        for i in range(len(ids)):
            n1 = self.nodes[ids[i]]
            if not n1.alive:
                continue
            for j in range(i + 1, len(ids)):
                n2 = self.nodes[ids[j]]
                if not n2.alive:
                    continue
                dist = math.hypot(n1.x - n2.x, n1.y - n2.y)
                if dist <= self.BLE_RANGE_PX:
                    norm = max(dist / 10.0, 1.0)
                    rssi = int(-40.0 - self.PATHLOSS_EXP_DB * math.log10(norm) + self.mob_rng.gauss(0, 2.0))
                    rssi = max(min(rssi, -30), -95)
                    self.edges.append((n1.id, n2.id, dist, rssi))
                    self.adj[n1.id][n2.id] = rssi
                    self.adj[n2.id][n1.id] = rssi
                    if n2.id not in old_adj.get(n1.id, {}):
                        if self.sim_time - n1.last_contact.get(n2.id, -1e9) > self.ENCOUNTER_GAP_S:
                            self._on_encounter(n1, n2)
                    n1.last_contact[n2.id] = n2.last_contact[n1.id] = self.sim_time

    def packet_success_prob(self, rssi: int) -> float:
        return 1.0 / (1.0 + math.exp(-(rssi - self.PSR_MID_DBM) / self.PSR_SCALE_DB))

    def get_neighbors(self, node_id: str) -> List[Tuple[str, int]]:
        return list(self.adj.get(node_id, {}).items())

    # ------------------------------------------- PRoPHET + gossip FL on contact

    def _advertised_P(self, node: Node, dest: str) -> float:
        if node.is_sinkhole:
            return 1.0  # the attack: claim to be next to everyone
        if node.id == dest:
            return 1.0
        return node.P.get(dest, 0.0)

    def _on_encounter(self, a: Node, b: Node):
        a.encounter_score += 1
        b.encounter_score += 1
        for x, y in ((a, b), (b, a)):
            p = x.P.get(y.id, 0.0)
            x.P[y.id] = p + (1 - p) * self.P_INIT
        # transitivity, using the *advertised* vectors (a liar pollutes this too)
        for x, y in ((a, b), (b, a)):
            pxy = x.P[y.id]
            src = {k: self._advertised_P(y, k) for k in (self.nodes if y.is_sinkhole else y.P)}
            for c, pyc in src.items():
                if c == x.id:
                    continue
                pxc = x.P.get(c, 0.0)
                x.P[c] = pxc + (1 - pxc) * pxy * pyc * self.P_BETA
        if self._warming:
            return
        if self.protocol_mode in ("MARL", "COMPARISON"):
            nbytes = 3 * min(8, len(a.P)) + 3 * min(8, len(b.P)) + 4
            self._charge_control(a, b, nbytes, n_tx=2)
        if self.federated_enabled:
            self._gossip_fedavg(a, b)

    def _age_predictability(self, dt: float):
        k = self.P_AGING_PER_S ** dt
        for n in self.nodes.values():
            for d in list(n.P):
                n.P[d] *= k
                if n.P[d] < 1e-3:
                    del n.P[d]

    def _gossip_fedavg(self, a: Node, b: Node):
        if a.is_quarantined or b.is_quarantined:
            return
        # each node takes part in at most one FL round per cooldown window
        last = max(a.last_gossip.get("*", -1e9), b.last_gossip.get("*", -1e9))
        if self.sim_time - last < self.GOSSIP_COOLDOWN_S:
            return
        na, nb = a.n_samples + 1, b.n_samples + 1
        merged = [(na * wa + nb * wb) / (na + nb) for wa, wb in zip(a.w, b.w)]
        a.w, b.w = list(merged), list(merged)
        a.n_samples = b.n_samples = (na + nb) // 2
        a.last_gossip["*"] = b.last_gossip["*"] = self.sim_time
        self.fl_rounds += 1
        nbytes = 2 * (8 + 4 * N_FEAT)
        self._charge_control(a, b, nbytes, n_tx=2)

    # ------------------------------------------------------------ Q-function

    def _phi(self, x: Node, y_id: Optional[str], dest: str) -> List[float]:
        if y_id is None:  # CARRY action
            return [1.0, self._advertised_P(x, dest), 0.0, x.battery / 100, x.buffer_occupancy / 100, 0.0, 1.0]
        y = self.nodes[y_id]
        return [
            1.0,
            self._advertised_P(y, dest),
            self.link_quality(x, y_id),
            y.battery / 100,
            y.buffer_occupancy / 100,
            1.0 if y_id == dest else 0.0,
            0.0,
        ]

    def link_quality(self, x: Node, y_id: str) -> float:
        """Estimated probability that a frame x->y gets through: the RSSI-based
        prior blended with x's own learned EWMA of past attempts on that link."""
        rssi = self.adj.get(x.id, {}).get(y_id)
        prior = self.packet_success_prob(rssi) if rssi is not None else 0.0
        if self.USE_LINK_EWMA and self.learning_enabled and y_id in x.link_q:
            return 0.5 * prior + 0.5 * x.link_q[y_id]
        return prior

    def action_value(self, x: Node, y_id: Optional[str], phi: List[float]) -> float:
        """Q_x(d, a). Forwarding is a gamble on the link:
        l * (value if it gets through) + (1 - l) * link-failure penalty."""
        v = self._dot(x.w, phi)
        if y_id is None:
            return v
        lq = phi[2]
        return lq * v + (1.0 - lq) * self.PENALTY_LINK_BREAK

    @staticmethod
    def _dot(w: List[float], phi: List[float]) -> float:
        return sum(a * b for a, b in zip(w, phi))

    def _eligible(self, x: Node, exclude: set) -> List[str]:
        return [
            y for y in self.adj.get(x.id, {})
            if y not in exclude and not self.nodes[y].is_quarantined and self.nodes[y].battery > 5.0
        ]

    def best_value(self, y: Node, dest: str, exclude: set) -> float:
        """V_y(d): what y reports back in the link-layer ACK."""
        if y.is_sinkhole:
            return 9.9
        vals = [self.action_value(y, None, self._phi(y, None, dest))]
        vals += [self.action_value(y, z, self._phi(y, z, dest)) for z in self._eligible(y, exclude)]
        return max(vals)

    def _td_update(self, x: Node, phi: List[float], target: float):
        if not self.learning_enabled:
            return
        err = target - self._dot(x.w, phi)
        x.w = [max(-self.W_CLIP, min(self.W_CLIP, w + self.ALPHA * err * f)) for w, f in zip(x.w, phi)]
        x.n_samples += 1

    def get_q(self, node_id: str, dest_id: str, next_hop_id: str) -> float:
        x = self.nodes[node_id]
        return self._dot(x.w, self._phi(x, next_hop_id, dest_id))

    # --------------------------------------------------------- energy helpers

    def _charge(self, node: Node, nbytes: int, tx: bool):
        e = nbytes * (self.E_TX_PER_BYTE if tx else self.E_RX_PER_BYTE)
        node.battery = max(0.0, node.battery - e)
        return e

    def _charge_control(self, a: Node, b: Node, nbytes: int, n_tx: int = 1):
        e = self._charge(a, nbytes // 2, True) + self._charge(b, nbytes // 2, True)
        e += self._charge(a, nbytes // 2, False) + self._charge(b, nbytes // 2, False)
        self.m["marl"]["control_tx"] += n_tx
        self.m["marl"]["control_bytes"] += nbytes
        self.m["marl"]["energy"] += e

    def _beacons(self, full_vector: bool):
        """BitChat already broadcasts a periodic announce for peer discovery, so
        MARL adds no extra transmissions here -- only extension bytes, which are
        charged to MARL: 2 B (battery, buffer) every second and the top-8
        delivery-predictability entries every PVEC_REFRESH_S."""
        for n in self.nodes.values():
            if not n.alive:
                continue
            nbytes = 2 + (3 * min(8, len(n.P)) if full_vector else 0)
            e = self._charge(n, nbytes, True)
            for y in self.adj.get(n.id, {}):
                e += self._charge(self.nodes[y], nbytes, False)
            self.m["marl"]["control_bytes"] += nbytes
            self.m["marl"]["energy"] += e

    # ------------------------------------------------------------- messaging

    def trigger_message(self, source_id: str, dest_id: str, is_emergency: bool = False, raw_text: Optional[str] = None):
        if source_id not in self.nodes or dest_id not in self.nodes or source_id == dest_id:
            return None
        if raw_text is None or raw_text == "Status Update":
            corpus = triage.EMERGENCY_CORPUS if is_emergency else triage.ROUTINE_CORPUS
            raw_text = self.traffic_rng.choice(corpus)
        tri = triage.encode(raw_text, slm_enabled=self.slm_toggle_on)
        self.triage_stats["n"] += 1
        self.triage_stats["raw_bytes"] += tri.raw_payload_bytes
        self.triage_stats["air_bytes"] += tri.payload_bytes
        if tri.intent == triage.INTENT_SOS:
            self.triage_stats["sos_n"] += 1
            self.triage_stats["sos_raw"] += tri.raw_payload_bytes
            self.triage_stats["sos_air"] += tri.payload_bytes

        self._pkt_counter += 1
        msg_id = f"m{self._pkt_counter:05d}"
        self.msg_records[msg_id] = {"src": source_id, "dst": dest_id, "t0": self.sim_time, "intent": tri.intent, "text": raw_text}

        if self.protocol_mode in ("MARL", "COMPARISON"):
            self.execute_marl_dispatch(source_id, dest_id, tri, msg_id)
        if self.protocol_mode in ("FLOODING", "COMPARISON"):
            self.execute_flooding_dispatch(source_id, dest_id, tri, msg_id, is_comparison=self.protocol_mode == "COMPARISON")
        return msg_id

    # ---------------------------------------------------------------- MARL

    def execute_marl_dispatch(self, source_id: str, dest_id: str, tri: "triage.TriageResult", msg_id: str):
        mm = self.m["marl"]
        mm["generated"] += 1
        sos = tri.intent == triage.INTENT_SOS
        if sos:
            mm["sos_generated"] += 1
        copies = self.SOS_COPIES if sos else 1
        for c in range(copies):
            pkt = PacketAnimation(
                packet_id=f"{msg_id}.{c}",
                msg_id=msg_id,
                source_id=source_id,
                dest_id=dest_id,
                path=[source_id],
                holder=source_id,
                created_at=self.sim_time,
                ttl_s=self.MARL_TTL_S * (2 if sos else 1),
                payload_size_bytes=tri.payload_bytes,
                intent_class=tri.intent,
                urgency=tri.urgency,
                is_emergency=sos,
                next_decision_at=self.sim_time,
            )
            self.active_packets.append(pkt)
            self.nodes[source_id].held_packets += 1
        label = "SOS fast-track" if sos else "MARL"
        self.log_event("MARL_ROUTER", f"{label}: {msg_id} {source_id}->{dest_id} [{tri.intent}, {tri.payload_bytes}B on air, x{copies}]")
        if sos:
            self.set_narrative(
                f"SOS: triage compressed {tri.raw_payload_bytes}B -> {tri.payload_bytes}B "
                f"('{triage.decode(tri.encoded)}'), 2 copies, no exploration."
            )
        else:
            self.set_narrative(f"MARL: {source_id} -> {dest_id} routed hop-by-hop with local Q-values only.")

    def _decide(self, pkt: PacketAnimation):
        x = self.nodes[pkt.holder]
        if not x.alive:
            return
        visited = set(pkt.path)
        # don't hand a second SOS copy to the node already holding/receiving the first
        for other in self.active_packets:
            if other is not pkt and other.msg_id == pkt.msg_id:
                visited.add(other.holder)
                if other.next_hop:
                    visited.add(other.next_hop)
        cands = self._eligible(x, visited)
        if pkt.dest_id in self.adj.get(x.id, {}) and self.nodes[pkt.dest_id].alive and pkt.dest_id not in cands:
            cands.append(pkt.dest_id)
        actions: List[Tuple[Optional[str], List[float]]] = [(None, self._phi(x, None, pkt.dest_id))]
        actions += [(y, self._phi(x, y, pkt.dest_id)) for y in cands]
        if pkt.is_emergency and len(actions) > 1:
            # urgency-aware policy: SOS never waits while a better-than-me relay exists
            carry_q = self.action_value(x, None, actions[0][1])
            if any(self.action_value(x, a, phi) > carry_q - 2.0 for a, phi in actions[1:]):
                actions = actions[1:]
        qs = [self.action_value(x, a, phi) for a, phi in actions]
        # cache for the inspector
        x.q_table[pkt.dest_id] = {(a or "CARRY"): round(q, 2) for (a, _), q in zip(actions, qs)}
        eps = 0.0 if pkt.is_emergency else self.EPSILON
        if self.rng.random() < eps and len(actions) > 1:
            idx = self.rng.randrange(len(actions))
        else:
            idx = max(range(len(actions)), key=lambda i: qs[i])
        choice = actions[idx][0]
        best_now = max(qs)
        # close the previous CARRY decision: r = -c, s' = now
        if pkt.carry_phi is not None:
            self._td_update(x, pkt.carry_phi, -self.CARRY_COST + self.GAMMA * best_now)
            pkt.carry_phi = None
        if choice is None:
            pkt.carry_phi = actions[0][1]
            pkt.next_decision_at = self.sim_time + self.DECISION_INTERVAL_S
            return
        pkt.carry_phi = None
        pkt.last_phi = self._phi(x, choice, pkt.dest_id)
        pkt.next_hop = choice
        pkt.progress = 0.0
        pkt.path.append(choice)
        mm = self.m["marl"]
        mm["data_tx"] += 1
        mm["data_bytes"] += pkt.payload_size_bytes
        mm["energy"] += self._charge(x, pkt.payload_size_bytes, True)
        x.packets_routed += 1
        x.status = "RELAYING"

    def _complete_hop(self, pkt: PacketAnimation):
        x = self.nodes[pkt.holder]
        y_id = pkt.next_hop
        y = self.nodes[y_id]
        mm = self.m["marl"]
        hop_cost = 0.4 + 0.6 * pkt.payload_size_bytes / 150.0
        rssi = self.adj.get(x.id, {}).get(y_id)
        ok = rssi is not None and y.alive and self.rng.random() <= self.packet_success_prob(rssi)
        if self.learning_enabled:
            lq = x.link_q.get(y_id, self.packet_success_prob(rssi) if rssi is not None else 0.5)
            x.link_q[y_id] = 0.7 * lq + 0.3 * (1.0 if ok else 0.0)
        if not ok:
            # link broke mid-transfer (mobility) or frame lost (weak RSSI):
            # the packet stays with x, x's link estimate drops, x re-decides
            mm["link_breaks"] += 1
            pkt.path.pop()
            pkt.next_hop = None
            pkt.next_decision_at = self.sim_time + self.DECISION_INTERVAL_S
            return
        mm["energy"] += self._charge(y, pkt.payload_size_bytes, False)
        x.held_packets = max(0, x.held_packets - 1)
        pkt.hops += 1
        # 2ACK (Liu et al., 2007): x just relayed, so x's predecessor learns that
        # x forwarded the packet it was handed -> credit (prev, x).
        if pkt.watch is not None and pkt.watch[1] == x.id:
            self._credit(pkt.watch[0], x.id, True)
            mm["control_tx"] += 1
            mm["control_bytes"] += 12
        pkt.watch = None

        if y_id == pkt.dest_id:
            self._td_update(x, pkt.last_phi, self.REWARD_DELIVER - hop_cost)
            self._credit(x.id, y_id, True)
            pkt.completed = True
            self._on_delivered(pkt)
            return

        if y.is_sinkhole:
            # the liar ACKs the hop with a fake V=9.9 and silently drops the packet
            self._td_update(x, pkt.last_phi, -hop_cost + self.GAMMA * 9.9)
            pkt.failed = True
            pkt.fail_reason = "sinkhole"
            mm["sinkhole_drops"] += 1
            self.pending_acks.append((self.sim_time + self.ACK2_TIMEOUT_S, (x.id, y_id)))
            self.log_event("PACKET_DROPPED", f"{pkt.packet_id} silently dropped by {y_id}")
            self.set_narrative(f"{y_id} advertised V=9.9, attracted {pkt.packet_id} and dropped it. {x.id} will notice when no 2-hop ACK comes back.")
            return

        v_y = self.best_value(y, pkt.dest_id, exclude=set(pkt.path))
        self._td_update(x, pkt.last_phi, -hop_cost + self.GAMMA * v_y)
        pkt.watch = (x.id, y_id, self.sim_time + self.ACK2_TIMEOUT_S)
        pkt.holder = y_id
        pkt.next_hop = None
        y.held_packets += 1
        pkt.next_decision_at = self.sim_time
        if pkt.hops >= self.MAX_HOPS:
            self._fail(pkt, "max_hops")

    def _on_delivered(self, pkt: PacketAnimation):
        mm = self.m["marl"]
        # end-to-end delivery ACK walks back along the route (control traffic)
        mm["control_tx"] += pkt.hops
        mm["control_bytes"] += 12 * max(1, pkt.hops)
        if pkt.msg_id in self.delivered_msgs:
            return  # duplicate SOS copy
        lat = self.sim_time - pkt.created_at
        self.delivered_msgs[pkt.msg_id] = lat
        mm["delivered"] += 1
        mm["latencies"].append(lat)
        mm["hops"].append(pkt.hops)
        if pkt.is_emergency:
            mm["sos_delivered"] += 1
            mm["sos_latencies"].append(lat)
        self.nodes[pkt.source_id].acks_received += 1
        self.log_event("DELIVERY_ACK", f"{pkt.msg_id} reached {pkt.dest_id} in {pkt.hops} hops, {lat:.1f}s")

    def _credit(self, a: str, b: str, credited: bool):
        self.trust_events.append((b, credited))
        rec = self.nodes[a].trust.setdefault(b, [0.0, 0.0])
        rec[0] += 1
        if credited:
            rec[1] += 1

    def _fail(self, pkt: PacketAnimation, reason: str):
        pkt.failed = True
        pkt.fail_reason = reason
        self.nodes[pkt.holder].held_packets = max(0, self.nodes[pkt.holder].held_packets - 1)
        if pkt.watch is not None:
            self._credit(pkt.watch[0], pkt.watch[1], False)
            pkt.watch = None

    def _resolve_ack_timeouts(self):
        keep = []
        for deadline, (a, b) in self.pending_acks:
            if self.sim_time >= deadline:
                self._credit(a, b, False)
            else:
                keep.append((deadline, (a, b)))
        self.pending_acks = keep
        for pkt in self.active_packets:
            if pkt.watch is not None and self.sim_time >= pkt.watch[2]:
                self._credit(pkt.watch[0], pkt.watch[1], False)
                pkt.watch = None

    def _update_marl_packets(self, dt: float):
        # emergencies first (priority queue)
        self.active_packets.sort(key=lambda p: -p.urgency)
        for pkt in self.active_packets:
            if pkt.completed or pkt.failed:
                continue
            if pkt.msg_id in self.delivered_msgs and pkt.next_hop is None:
                pkt.completed = True  # sibling copy already arrived
                self.nodes[pkt.holder].held_packets = max(0, self.nodes[pkt.holder].held_packets - 1)
                continue
            if self.sim_time - pkt.created_at > pkt.ttl_s:
                self._fail(pkt, "ttl")
                continue
            if pkt.next_hop is None:
                if self.sim_time >= pkt.next_decision_at:
                    self._decide(pkt)
            else:
                pkt.progress += dt / self.HOP_TIME_S
                if pkt.progress >= 1.0:
                    self._complete_hop(pkt)
        done = [p for p in self.active_packets if p.completed or p.failed]
        for p in done:
            if p.failed and p.fail_reason != "sinkhole" and p.msg_id not in self.delivered_msgs:
                siblings_alive = any(q.msg_id == p.msg_id and not (q.completed or q.failed) for q in self.active_packets)
                if not siblings_alive:
                    self.m["marl"]["failed"] += 1
        self.active_packets = [p for p in self.active_packets if not (p.completed or p.failed)]
        for n in self.nodes.values():
            if n.status == "RELAYING" and n.held_packets == 0:
                n.status = "IDLE" if not n.is_quarantined else "QUARANTINED"

    # ------------------------------------------------------------- flooding

    def execute_flooding_dispatch(self, source_id: str, dest_id: str, tri: "triage.TriageResult", msg_id: str, is_comparison: bool = False):
        mf = self.m["flood"]
        mf["generated"] += 1
        sos = tri.intent == triage.INTENT_SOS
        if sos:
            mf["sos_generated"] += 1
        nbytes = tri.payload_bytes
        received = {source_id: 0}
        frontier = [source_id]
        tx = rx = coll = 0
        energy = 0.0
        delivered_wave = None
        for wave in range(self.FLOOD_TTL):
            broadcasters = [
                b for b in frontier
                if self.nodes[b].alive and b != dest_id and not self.nodes[b].is_sinkhole
            ]
            if not broadcasters:
                break
            slot = {b: self.rng.randrange(self.FLOOD_SLOTS) for b in broadcasters}
            tx += len(broadcasters)
            for b in broadcasters:
                energy += self._charge(self.nodes[b], nbytes, True)
            heard: Dict[str, List[str]] = {}
            for b in broadcasters:
                for r in self.adj.get(b, {}):
                    heard.setdefault(r, []).append(b)
            nxt = []
            for r, senders in heard.items():
                rn = self.nodes[r]
                if not rn.alive:
                    continue
                for s in senders:
                    energy += self._charge(rn, nbytes, False)
                rx += len(senders)
                ok = [s for s in senders if sum(1 for t in senders if slot[t] == slot[s]) == 1]
                coll += len(senders) - len(ok)
                ok = [s for s in ok if self.rng.random() <= self.packet_success_prob(self.adj[s][r])]
                for s in senders:
                    if r not in received or s in ok:
                        self.active_flood_branches.append(
                            FloodBranch(f"fb{self._pkt_counter}_{wave}_{s}_{r}", s, r, wave,
                                        progress=-1.2 * wave, collided=s not in ok)
                        )
                if ok and r not in received:
                    received[r] = wave + 1
                    nxt.append(r)
                    if r == dest_id:
                        delivered_wave = wave + 1
            frontier = nxt
        mf["data_tx"] += tx
        mf["data_bytes"] += tx * nbytes
        mf["energy"] += energy
        mf["collisions"] += coll
        if delivered_wave is not None:
            lat = delivered_wave * self.HOP_TIME_S
            mf["delivered"] += 1
            mf["latencies"].append(lat)
            mf["hops"].append(delivered_wave)
            if sos:
                mf["sos_delivered"] += 1
                mf["sos_latencies"].append(lat)
        else:
            mf["failed"] += 1
        if len(self.active_flood_branches) > 600:
            self.active_flood_branches = self.active_flood_branches[-600:]
        res = "delivered" if delivered_wave else "NOT delivered (partition/TTL/collisions)"
        self.log_event("FLOODING_STORM", f"{msg_id}: {tx} broadcasts, {rx} receptions, {coll} collisions, {res}")
        if not is_comparison:
            self.set_narrative(
                f"BROADCAST STORM: {msg_id} from {source_id} -> {tx} rebroadcasts, {rx} receptions "
                f"({coll} collided) to reach {len(received) - 1} phones; {res}."
            )

    def _update_flood_branches(self, dt: float):
        keep = []
        for fb in self.active_flood_branches:
            fb.progress += dt / self.HOP_TIME_S
            if fb.progress < 1.0:
                keep.append(fb)
        self.active_flood_branches = keep

    # ------------------------------------------------------------------ IDS

    def inject_sinkhole(self, node_id: Optional[str] = None):
        cands = [n for n in self.nodes if not self.nodes[n].is_sinkhole]
        if not cands:
            return
        if node_id not in self.nodes:
            # most central node = most dangerous
            node_id = max(cands, key=lambda n: len(self.adj.get(n, {})))
        t = self.nodes[node_id]
        t.is_sinkhole = True
        t.advertised_q = 9.9
        t.status = "SINKHOLE"
        self.sinkhole_injection_time = self.sim_time
        self.set_narrative(f"ATTACK: {node_id} now advertises P(d)=1.0 and V=9.9 for every destination and drops all data.")
        self.log_event("ATTACK_INJECTED", f"Sinkhole {node_id} spawned (lies in beacons + ACKs, drops data).")
        return node_id

    def run_gnn_ids(self):
        """Ego-graph trust IDS.

        Step 1 (message passing): every node's forwarding reputation is the
        decayed Beta mean of 2ACK outcomes reported by everyone who handed it a
        packet; the *expected* behaviour p0 of node y is the mean reputation of
        y's 1-hop ego graph (its current neighbours).
        Step 2 (change detection): a one-sided CUSUM over y's new outcomes,
        log-likelihood ratio of "drops like a sinkhole (p1)" vs "forwards like
        its neighbours (p0)". Alarm when S_y >= CUSUM_H.
        anomaly_score = S_y / CUSUM_H (1.0 = quarantine).
        """
        if not self.ids_enabled:
            self.trust_events.clear()
            return
        decay = self.TRUST_DECAY_PER_S ** self.IDS_INTERVAL_S
        H: Dict[str, float] = {n: 0.0 for n in self.nodes}
        C: Dict[str, float] = {n: 0.0 for n in self.nodes}
        for rep in self.nodes.values():
            for y, rec in rep.trust.items():
                rec[0] *= decay
                rec[1] *= decay
                H[y] += rec[0]
                C[y] += rec[1]
        rep_score = {n: (C[n] + 1) / (H[n] + 2) for n in self.nodes}
        glob = (sum(C.values()) + 1) / (sum(H.values()) + 2)
        p1 = self.CUSUM_P1
        for y, ok in self.trust_events:
            neigh = [z for z in self.adj.get(y, {}) if H[z] > 0.5 and not self.nodes[z].is_quarantined]
            p0 = sum(rep_score[z] for z in neigh) / len(neigh) if neigh else glob
            p0 = max(0.6, min(0.98, p0))
            llr = math.log(p1 / p0) if ok else math.log((1 - p1) / (1 - p0))
            self.cusum[y] = max(0.0, self.cusum.get(y, 0.0) + llr)
        self.trust_events.clear()

        for nid, node in self.nodes.items():
            node.anomaly_score = round(min(1.0, self.cusum.get(nid, 0.0) / self.CUSUM_H), 3)
            if node.anomaly_score >= self.SINKHOLE_QUARANTINE_THRESHOLD and not node.is_quarantined:
                node.is_quarantined = True
                node.status = "QUARANTINED"
                for peer in self.nodes.values():
                    peer.prune_peer(nid)
                det = None
                if node.is_sinkhole and self.sinkhole_injection_time is not None:
                    det = self.sim_time - self.sinkhole_injection_time
                    self.ids_detection_s.append(det)
                kind = "true positive" if node.is_sinkhole else "FALSE POSITIVE"
                msg = (f"{nid} quarantined: CUSUM={self.cusum[nid]:.2f} (reputation {rep_score[nid]:.2f}, "
                       f"evidence {H[nid]:.1f}) [{kind}]")
                if det is not None:
                    msg += f", {det:.1f}s after the attack started"
                self.log_event("GNN_QUARANTINE", msg)
                self.set_narrative("TRUST IDS: " + msg)

    def clear_quarantines(self):
        for n in self.nodes.values():
            n.is_sinkhole = False
            n.is_quarantined = False
            n.anomaly_score = 0.0
            n.status = "IDLE"
            n.trust.clear()
        self.cusum.clear()
        self.trust_events.clear()
        self.sinkhole_injection_time = None
        self.set_narrative("Quarantines cleared and trust counters reset.")
        self.log_event("SYSTEM", "Cleared quarantines and trust state.")

    # ------------------------------------------------------------ scenarios

    def run_scenario(self, scenario_id: int):
        keys = list(self.nodes.keys())
        if len(keys) < 4:
            return
        src, dst = keys[0], keys[-1]
        if scenario_id == 1:
            self.protocol_mode = "FLOODING"
            self.trigger_message(src, dst, is_emergency=False)
        elif scenario_id == 2:
            self.protocol_mode = "MARL"
            self.trigger_message(src, dst, is_emergency=False)
        elif scenario_id == 3:
            self.protocol_mode = "MARL"
            self.slm_toggle_on = True
            self.trigger_message(src, dst, is_emergency=True)
        elif scenario_id == 4:
            self.protocol_mode = "MARL"
            sink = self.inject_sinkhole()
            # burst of traffic so the trust IDS gathers evidence
            for i in range(40):
                s, d = self.traffic_rng.sample([k for k in keys if k != sink], 2)
                self.scheduled.append((self.sim_time + 1.0 * i, {"src": s, "dst": d}))
            self.set_narrative(f"SCENARIO 4: {sink} turned sinkhole; 40 messages queued over 40s (try 4x speed). Watch the trust IDS collect missing 2-hop ACKs and quarantine it.")

    # ------------------------------------------------------------------ tick

    def tick(self, dt: float = 0.033):
        if self.is_paused:
            return
        dt = dt * self.simulation_speed
        self.sim_time += dt
        self.update_mobility(dt)
        self.update_topology()
        self._age_predictability(dt)
        if self.sim_time - self._last_beacon >= self.BEACON_INTERVAL_S:
            self._last_beacon = self.sim_time
            if self.protocol_mode in ("MARL", "COMPARISON"):
                full = self.sim_time - self._last_pvec >= self.PVEC_REFRESH_S
                if full:
                    self._last_pvec = self.sim_time
                self._beacons(full)
        for when, job in list(self.scheduled):
            if self.sim_time >= when:
                self.scheduled.remove((when, job))
                self.trigger_message(job["src"], job["dst"], is_emergency=job.get("sos", False))
        self._update_marl_packets(dt)
        self._update_flood_branches(dt)
        self._resolve_ack_timeouts()
        if self.sim_time - self._last_ids >= self.IDS_INTERVAL_S:
            self._last_ids = self.sim_time
            self.run_gnn_ids()
        if self.auto_traffic and self.sim_time - self._last_traffic > self.traffic_interval_s:
            self._last_traffic = self.sim_time
            alive = [k for k, n in self.nodes.items() if n.alive and not n.is_sinkhole]
            if len(alive) >= 2:
                s, d = self.traffic_rng.sample(alive, 2)
                self.trigger_message(s, d, is_emergency=self.traffic_rng.random() < 0.2)

    # ------------------------------------------------------------- metrics

    @staticmethod
    def _mean(xs: List[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    def summary(self) -> Dict[str, Dict[str, float]]:
        out = {}
        for proto, mm in self.m.items():
            gen = mm["generated"]
            tot_tx = mm["data_tx"] + mm["control_tx"]
            out[proto] = {
                "generated": gen,
                "delivered": mm["delivered"],
                "pdr": mm["delivered"] / gen if gen else 0.0,
                "latency_s": self._mean(mm["latencies"]),
                "hops": self._mean(mm["hops"]),
                "data_tx": mm["data_tx"],
                "control_tx": mm["control_tx"],
                "tx_total": tot_tx,
                "tx_per_delivery": tot_tx / mm["delivered"] if mm["delivered"] else float("nan"),
                "bytes_total": mm["data_bytes"] + mm["control_bytes"],
                "energy": mm["energy"],
                "energy_per_delivery": mm["energy"] / mm["delivered"] if mm["delivered"] else float("nan"),
                "collisions": mm["collisions"],
                "sos_pdr": mm["sos_delivered"] / mm["sos_generated"] if mm["sos_generated"] else float("nan"),
                "sos_latency_s": self._mean(mm["sos_latencies"]),
                "sinkhole_drops": mm["sinkhole_drops"],
            }
        ts = self.triage_stats
        out["triage"] = {
            "avg_raw_bytes": ts["raw_bytes"] / ts["n"] if ts["n"] else 0.0,
            "avg_air_bytes": ts["air_bytes"] / ts["n"] if ts["n"] else 0.0,
            "sos_raw_bytes": ts["sos_raw"] / ts["sos_n"] if ts["sos_n"] else 0.0,
            "sos_air_bytes": ts["sos_air"] / ts["sos_n"] if ts["sos_n"] else 0.0,
        }
        out["ids"] = {
            "detection_s": self.ids_detection_s[-1] if self.ids_detection_s else float("nan"),
            "false_positives": sum(1 for n in self.nodes.values() if n.is_quarantined and not n.is_sinkhole),
        }
        out["fl_rounds"] = self.fl_rounds
        return out

    def get_state_snapshot(self) -> Dict:
        s = self.summary()
        mk, fl = s["marl"], s["flood"]
        return {
            "nodes": [
                {
                    "id": n.id,
                    "x": round(n.x, 1),
                    "y": round(n.y, 1),
                    "battery": round(n.battery, 1),
                    "buffer": n.buffer_occupancy,
                    "encounter_score": n.encounter_score,
                    "is_sinkhole": n.is_sinkhole,
                    "is_quarantined": n.is_quarantined,
                    "anomaly_score": n.anomaly_score,
                    "q_table": {d: v for d, v in list(n.q_table.items())[-4:]},
                    "status": n.status,
                    "samples": n.n_samples,
                    "top_P": sorted(((d, round(p, 2)) for d, p in n.P.items()), key=lambda t: -t[1])[:4],
                }
                for n in self.nodes.values()
            ],
            "edges": [{"source": u, "target": v, "distance": round(d, 1), "rssi": r} for u, v, d, r in self.edges],
            "packets": [
                {
                    "packet_id": p.packet_id,
                    "source_id": p.source_id,
                    "dest_id": p.dest_id,
                    "path": p.path,
                    "hop_idx": p.current_hop_idx,
                    "progress": round(min(p.progress, 1.0), 2) if p.next_hop else 0.0,
                    "carrying": p.next_hop is None,
                    "is_flooding": False,
                    "is_emergency": p.is_emergency,
                    "urgency": p.urgency,
                    "payload_size": p.payload_size_bytes,
                    "intent": p.intent_class,
                }
                for p in self.active_packets
            ],
            "flood_branches": [
                {"branch_id": fb.branch_id, "from": fb.from_node, "to": fb.to_node, "progress": round(fb.progress, 2), "collided": fb.collided}
                for fb in self.active_flood_branches
                if 0.0 <= fb.progress < 1.0
            ],
            "world_bounds": {"width": self.BOUNDS_WIDTH, "height": self.BOUNDS_HEIGHT},
            "narrative": self.current_narrative,
            "protocol_mode": self.protocol_mode,
            "sim_time": round(self.sim_time, 1),
            "metrics": {
                "marl_transmissions": mk["tx_total"],
                "marl_data_tx": mk["data_tx"],
                "marl_control_tx": mk["control_tx"],
                "flooding_transmissions": fl["tx_total"],
                "collision_count": fl["collisions"],
                "marl_battery_burn": round(mk["energy"], 1),
                "flooding_battery_burn": round(fl["energy"], 1),
                "marl_delivered": mk["delivered"],
                "marl_generated": mk["generated"],
                "marl_pdr": round(mk["pdr"], 3),
                "flood_delivered": fl["delivered"],
                "flood_generated": fl["generated"],
                "flood_pdr": round(fl["pdr"], 3),
                "marl_latency_s": round(mk["latency_s"], 2),
                "flood_latency_s": round(fl["latency_s"], 2),
                "sinkhole_drops": mk["sinkhole_drops"],
                "ids_detection_s": None if math.isnan(s["ids"]["detection_s"]) else round(s["ids"]["detection_s"], 1),
                "fl_rounds": s["fl_rounds"],
                "triage_raw_bytes": round(s["triage"]["avg_raw_bytes"], 1),
                "triage_air_bytes": round(s["triage"]["avg_air_bytes"], 1),
            },
            "logs": list(self.event_logs),
        }

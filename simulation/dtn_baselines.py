"""Standard delay-tolerant routing baselines, run on the same mobility, radio, traffic and energy
model as MARL and flooding (simulation/mesh_engine.py):

  EPIDEMIC  copy every message to every neighbour that lacks it (Vahdat & Becker, 2000)
  SPRAY     binary Spray-and-Wait with L copies: hand half your copies to a neighbour; with one
            copy left, wait to meet the destination (Spyropoulos et al., 2005)
  PROPHET   copy to a neighbour whose delivery predictability for the destination is higher than
            yours (GRTR rule; Lindgren et al., 2003), using the engine's PRoPHET vectors
  DIRECT    hold the message until you meet the destination yourself (lower bound on cost)

Same rules for all: one frame per link at a time, taking HOP_TIME_S (x2 on Long Range links);
success with the same RSSI-based probability; the sender pays transmit energy and the receiver
receive energy per frame; each offer costs an 8-byte control exchange (summary vector entry);
copies expire after the same TTL as MARL (x2 for SOS); SOS goes first. A delivery receipt
walks back along the path (12 B per hop), as in MARL; PRoPHET pays for its predictability vectors
the same way MARL does. By default, copies keep spreading and live until their TTL even after
delivery (no anti-packets, as in the ONE simulator's defaults). With vaccine=True every copy
vanishes the moment the message is delivered: an optimistic upper bound for the baselines.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

KINDS = ("EPIDEMIC", "SPRAY", "PROPHET", "DIRECT")
CONTROL_BYTES = 8


@dataclass
class _Msg:
    src: str
    dst: str
    t0: float
    nbytes: int
    sos: bool
    ttl: float
    delivered: bool = False


@dataclass
class _Copy:
    tokens: int
    hops: int


class DTNRouter:
    def __init__(self, eng, kind: str, spray_copies: int = 8, vaccine: bool = False):
        assert kind in KINDS, kind
        self.e = eng
        self.kind = kind
        self.L = spray_copies
        self.vaccine = vaccine
        self.msgs: Dict[str, _Msg] = {}
        self.buf: Dict[str, Dict[str, _Copy]] = {}
        self.busy_until: Dict[frozenset, float] = {}
        self.m = eng.m["dtn"]

    def originate(self, src: str, dst: str, tri, msg_id: str):
        from . import triage
        sos = tri.intent == triage.INTENT_SOS
        self.m["generated"] += 1
        if sos:
            self.m["sos_generated"] += 1
        self.msgs[msg_id] = _Msg(src, dst, self.e.sim_time, tri.payload_bytes, sos,
                                 self.e.MARL_TTL_S * (2 if sos else 1))
        self.buf.setdefault(src, {})[msg_id] = _Copy(self.L if self.kind == "SPRAY" else 1, 0)

    # ---------------------------------------------------------------- policy

    def _wants(self, a: str, b: str, mid: str, c: _Copy) -> bool:
        m = self.msgs[mid]
        if b == m.dst:
            return not m.delivered  # the destination already has it once delivered
        if mid in self.buf.get(b, {}):
            return False
        if self.kind == "EPIDEMIC":
            return True
        if self.kind == "SPRAY":
            return c.tokens > 1
        if self.kind == "PROPHET":
            na, nb = self.e.nodes[a], self.e.nodes[b]
            return self.e._advertised_P(nb, m.dst) > self.e._advertised_P(na, m.dst)
        return False  # DIRECT

    def step(self):
        e = self.e
        t = e.sim_time
        # expire and purge
        for nid, b in self.buf.items():
            for mid in [k for k, c in b.items() if (self.vaccine and self.msgs[k].delivered) or t - self.msgs[k].t0 > self.msgs[k].ttl]:
                del b[mid]
        for a, nbrs in e.adj.items():
            na = e.nodes[a]
            if not na.alive or not self.buf.get(a):
                continue
            if na.is_sinkhole:
                self.buf[a].clear()  # a sinkhole never passes anything on
                continue
            for b, rssi in nbrs.items():
                link = frozenset((a, b))
                if t < self.busy_until.get(link, 0.0) or not e.nodes[b].alive:
                    continue
                cands = [(mid, c) for mid, c in self.buf[a].items() if self._wants(a, b, mid, c)]
                if not cands:
                    continue
                mid, c = min(cands, key=lambda mc: (not self.msgs[mc[0]].sos, self.msgs[mc[0]].t0))
                self._transfer(a, b, rssi, mid, c, link)

    def _transfer(self, a: str, b: str, rssi: int, mid: str, c: _Copy, link: frozenset):
        e = self.e
        m = self.msgs[mid]
        coded = link in e.coded
        cx = e.CODED_ENERGY_X if coded else 1.0
        self.busy_until[link] = e.sim_time + e.HOP_TIME_S * (e.CODED_HOP_TIME_X if coded else 1.0)
        na, nb = e.nodes[a], e.nodes[b]
        # offer/accept (summary vector entry) both ways, then the frame
        self.m["control_tx"] += 1
        self.m["control_bytes"] += CONTROL_BYTES
        self.m["energy"] += e._charge(na, CONTROL_BYTES, True) + e._charge(nb, CONTROL_BYTES, False)
        self.m["data_tx"] += 1
        self.m["data_bytes"] += m.nbytes
        self.m["energy"] += e._charge(na, int(m.nbytes * cx), True)
        if e.rng.random() > e.packet_success_prob(rssi):
            self.m["link_breaks"] += 1
            return
        self.m["energy"] += e._charge(nb, int(m.nbytes * cx), False)
        if nb.is_sinkhole and b != m.dst:
            self.m["sinkhole_drops"] += 1
            if self.kind == "SPRAY":
                c.tokens -= c.tokens // 2  # the copies handed over are lost
            return
        if b == m.dst:
            if not m.delivered:
                m.delivered = True
                lat = e.sim_time - m.t0
                self.m["delivered"] += 1
                self.m["latencies"].append(lat)
                self.m["hops"].append(c.hops + 1)
                # delivery receipt back to the source, one 12-byte frame per hop (as MARL)
                h = c.hops + 1
                self.m["control_tx"] += h
                self.m["control_bytes"] += 12 * h
                self.m["energy"] += h * 12 * (e.E_TX_PER_BYTE + e.E_RX_PER_BYTE)
                if m.sos:
                    self.m["sos_delivered"] += 1
                    self.m["sos_latencies"].append(lat)
            self.buf[a].pop(mid, None)
            return
        if self.kind == "SPRAY":
            give = c.tokens // 2
            c.tokens -= give
            self.buf.setdefault(b, {})[mid] = _Copy(give, c.hops + 1)
        else:
            self.buf.setdefault(b, {})[mid] = _Copy(1, c.hops + 1)

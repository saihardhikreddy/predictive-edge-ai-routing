# Project idea (revised, October 2026)

**Working title:** *Predictive Edge Routing for Offline BLE Meshes: Learning Store-Carry-Forward with Gossip-Federated Training and Trust-Based Sinkhole Defence*

Team 8 · Introduction to Computer Networks (23AID206)

---

## 1. The idea in one paragraph

Offline messengers such as BitChat, Bridgefy and Briar move messages by **flooding**: every phone that hears a message rebroadcasts it. That is robust in small groups but scales badly. Every neighbour pays receive energy for every copy, and same-slot rebroadcasts collide. We replace flooding with a **per-phone learned router**. Each phone decides locally whether to hand a message to one neighbour or to **carry it** until a better relay appears. It decides using:

1. how likely each neighbour is to *meet the destination soon*, learned from encounter history;
2. how likely the BLE link is to *actually deliver the frame*, from RSSI;
3. a small Q-function trained with temporal-difference learning.

Phones that meet **average their model weights** (gossip federated learning), so the network learns faster without anyone sharing locations or contact logs. Every hop is confirmed by a **two-hop ACK**, and a **CUSUM change detector** over those confirmations quarantines nodes that start swallowing traffic (sinkholes). An on-device **triage** step turns emergency texts into a few semantic tokens and gives them priority.

## 2. What changed from the first review, and why

| First-review claim | Problem | Now |
|---|---|---|
| "MARL routing" | Paths were computed with a global view of the network, and Q-values were never really learned (the next-state value was fixed at 7.5) | Truly distributed: each phone uses only neighbour beacons and its own model; TD(0) updates use the neighbour's advertised value |
| "Gossip federated learning" | Not implemented | Sample-weighted FedAvg on encounters, at most once per node every 30 s, with only 7 floats on air |
| "GNN detects a sinkhole in 41.8 ms" | Hard-coded: `anomaly = 0.985` for the attacker, and 41.8 was a constant | Two-hop ACK evidence, ego-graph baseline, CUSUM. Measured: **12/12 attacks detected, 44 ± 11 s, 0 false positives in 30 runs** |
| "SLM compresses 140 B → 18 B, 5× urgency" | Fixed numbers | Lexicon classifier plus semantic token encoding. Measured: **SOS 113 B → 30 B on air** (header included); routine chat 95 B → 56 B, lossless |
| "−85% power vs flooding" | Flooding was charged 2.4× more per hop and counted one transmission per *edge* | One broadcast = one transmission, every listener pays receive energy, slotted collisions, same packet-loss model for both |

**Naming.** In slides and the report, call the security layer an *ego-graph trust aggregation with CUSUM change detection*. It is a one-layer, fixed-weight message-passing step, so "GNN-style" is fair but "GNN" alone is not. Call the triage layer *on-device triage (rule-based, SLM-swappable)* until a real model is plugged in.

## 3. Measured results (from `python benchmark.py`, 6 seeds per cell, 300 s each)

| Nodes in the same area | Energy per delivered message (Flooding → MARL) | Collisions per message (Flooding → MARL) | Delivery ratio (Flooding / MARL) | Latency (Flooding / MARL) |
|---|---|---|---|---|
| 16 (sparse) | 1.77 → 0.81 (**2.2× less**) | 18 → 0 | 0.78 / **0.89** | 0.9 s / 7.3 s |
| 32 | 6.54 → 1.35 (**4.8× less**) | 180 → 0 | **0.96** / 0.92 | 0.9 s / 4.7 s |
| 48 (dense) | 13.5 → 1.88 (**7.2× less**) | 528 → 0 | **0.99** / 0.90 | 0.9 s / 3.9 s |

- **Learning from zero** (32 nodes, cold start): delivery stays at 0.2–0.3 without learning. TD learning reaches ≈0.80 in about 6–10 minutes; with gossip FL it gets there faster (0.72 vs 0.56 at 2 minutes). The hand-designed prior sits at about 0.92.
- **Sinkhole at t = 30 s:** delivery after the attack is Flooding 0.77, MARL without IDS 0.64, **MARL with IDS 0.85**. The IDS cuts swallowed packets from 76 to 17.
- **SOS:** delivery ratio 0.92–0.97 across densities, with two copies, priority, and no exploration.

## 4. What the results honestly say (put this on a slide; examiners respect it)

1. **The energy and collision win is real and grows with density.** Flooding's cost grows with neighbourhood size; unicast routing's doesn't.
2. **The price is latency.** Store-carry-forward waits for good relays, so MARL takes 4–7 s versus about 0.9 s. That is fine for chat and SOS; it would be wrong for voice.
3. **In dense meshes flooding still delivers slightly more** (0.99 vs 0.90). In sparse, partitioned meshes MARL delivers more, because carrying beats shouting into an empty room.
4. **Learning on top of a good prior gives only about +1–3 delivery points**, which is within seed noise. The value of RL here is that it **learns PRoPHET-quality routing from scratch**, and that federated averaging **speeds that up**. That is the claim we can defend.
5. **Flooding is naturally robust to a sinkhole**, because one silent node can't stop a flood. Learned routing is *attracted* to a liar, which is exactly why the trust layer is necessary rather than decorative.

## 5. Contributions we can claim

- **C1.** An expected-transmission-aware, fully local Q-routing formulation for BLE store-carry-forward. CARRY is an explicit action, and the delivery predictability is part of the state.
- **C2.** Gossip FedAvg for routing models in an infrastructure-less mesh, with measured convergence speed-up from a cold start.
- **C3.** A sinkhole defence that needs no global view: two-hop ACKs plus an ego-graph-normalised CUSUM, with the detection-time and false-positive trade-off measured.
- **C4.** An urgency-aware policy (priority, two copies, no exploration) driven by on-device triage, with measured payload reduction.
- **C5.** An open, reproducible simulator and dashboard: same mobility and message traces across variants, plus ablations.

## 6. Next steps to make it conference-worthy

1. **Show where learning beats the prior.** Run non-stationary scenarios: crowds that change mobility regime (lecture to lunch rush), nodes whose battery or buffer collapses, region-dependent radio loss. The fixed prior can't adapt there; TD+FL should.
2. **Compare against the real DTN baselines:** epidemic, Spray-and-Wait, and plain PRoPHET. Use real contact traces (the CRAWDAD Haggle/Infocom datasets) as well as the synthetic mobility.
3. **Make the IDS stronger.** Add a grayhole attacker (drops 30–70%), colluding liars, and on-off attacks. Then train a small GNN on simulated traces and compare it against the CUSUM baseline.
4. **Replace the rule-based triage** with a tiny on-device classifier. Report precision/recall on a labelled message set, plus phone latency.
5. **Field test:** 4–6 Android phones running the `MarlRouter` module inside BitChat, logging RSSI, hop success and battery drain.

## 7. How to reproduce

```bash
pip install websockets matplotlib
python -m unittest discover tests      # 18 tests
python benchmark.py                    # ~3 min → results/summary.md + charts
python digital_twin_server.py          # dashboard at http://localhost:8080
```

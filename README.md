# Predictive Edge AI Routing for Offline Bluetooth Mesh Networks
**A learning, privacy-preserving and self-defending routing layer for BitChat-style BLE meshes**

* **Course:** Introduction to Computer Networks (23AID206)
* **Instructor:** Dr. Sundharesan S
* **Team 8:** C Sai Hardhik Reddy, Kavali Charan Saatvikh Reddy, R Gagan Chowdary

See **[IDEA.md](IDEA.md)** for the revised idea, measured results and limitations.

---

## What's in here

| Path | What it is |
|---|---|
| `simulation/mesh_engine.py` | The simulator: mobility, BLE radio (path loss + packet loss), distributed Q-routing with CARRY, PRoPHET predictability, gossip FedAvg, two-hop-ACK trust + CUSUM IDS, BitChat-style TTL flooding baseline |
| `simulation/triage.py` | On-device message triage: emergency classifier + semantic SOS encoding + lossless codebook compression |
| `digital_twin_server.py` + `web/index.html` | Live dashboard (HTTP 8080, WebSocket 8765) |
| `benchmark.py` | Headless experiments with seeds and ablations → `results/` |
| `results/` | Latest benchmark output: `summary.md`, `runs.csv`, charts |
| `app/` | Android module: `MarlRouter.kt` (pure-Kotlin port of the router) + a self-check `MainActivity` + JUnit tests |
| `tests/` | Python unit tests |

## How each layer works (all computed, nothing hard-coded)

1. **Predictive MARL routing.** Each phone keeps a 7-weight linear Q-function over *forward to neighbour y* or *CARRY*. Features come only from local observation: the neighbour's advertised delivery predictability to the destination, link success probability from RSSI, battery, buffer. Forwarding is scored as `linkQ · Q + (1 − linkQ) · penalty`. After each hop the receiver piggybacks its value `V_y(d)` on the ACK and the sender runs a TD(0) update.
2. **Mobility learning.** PRoPHET-style `P(d)`: it rises on encounters, ages over time, and spreads transitively.
3. **Gossip federated learning.** Phones that meet average weights, weighted by sample count (at most once per node every 30 s).
4. **Trust IDS.** Two-hop ACKs confirm that each relay really forwarded. A one-sided CUSUM compares a node's outcomes with its 1-hop neighbourhood and quarantines it at `CUSUM ≥ 12`.
5. **Triage.** SOS texts become about 6 bytes of tokens plus a 24-byte header. They get priority, two copies, and no exploration.

## Run it

```bash
pip install websockets matplotlib

python -m unittest discover tests     # 18 tests
python benchmark.py --quick           # ~20 s smoke run
python benchmark.py                   # full run (~3 min) -> results/
python digital_twin_server.py         # open http://localhost:8080
```

Dashboard tips: **Compare Side-by-Side** runs both protocols on every message. Scenario **4** turns the most central phone into a sinkhole and queues 40 messages; the IDS typically quarantines it 30–45 simulated seconds later (about 10 s of wall time at 4× speed). Click a phone to see its Q-values, delivery predictabilities and number of local updates.

## Phone testbed (APK)

Every push to `main` builds **Mesh Testbed** on GitHub Actions and publishes it under **Releases → latest** as `MeshTestbed.apk`. Install it on 3–5 phones and follow **[FIELD_TEST.md](FIELD_TEST.md)**. It runs the same router as the simulator over real BLE, logs everything to CSV, and `tools/analyze_field_logs.py` turns the merged logs into report tables.

## Android module

`app/` is the testbed app: a 3D three.js interface (`assets/web/`, five chapters: Mesh, Send, Route, Defend, Lab) in a WebView, driven by the Kotlin engine through a small JSON bridge (`MainActivity.kt`, `mesh/StateJson.kt`). Open `assets/web/index.html` in a desktop browser to try the UI with a built-in demo engine. Engine: `mesh/BleTransport.kt` (advertise, scan, GATT inbox), `mesh/MeshEngine.kt` (flooding and MARL forwarding, encounters, FedAvg, 2-hop ACK trust, delivery ACKs), `mesh/EventLog.kt` (CSV). To build locally, open the root in Android Studio. `MarlRouter` is pure Kotlin, so it can be unit-tested on the JVM (`app/src/test`). The integration point in BitChat is the relay step of `BluetoothMeshService`: call `decide()` there instead of rebroadcasting. `bitchat_repo/` is currently empty; clone upstream BitChat Android there when you start that integration.

## Presentation files

`Predictive_Edge_AI_Routing*.pptx`, `presentation.tex` and `presentation_guide.md` are from the first review. Several of their numbers (41.8 ms, 140 → 18 B, −85% power) came from the old hard-coded demo. Replace them with `results/summary.md` before the next review; IDEA.md §2 lists each one.

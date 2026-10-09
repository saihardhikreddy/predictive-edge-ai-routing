# Field test with 3–5 phones

## 1. Install

1. On each phone, open the repo's **Releases → latest** page and download `MeshTestbed.apk`.
2. Allow "install unknown apps" for your browser when Android asks, then install.
3. New builds install over old ones; they all use the same signing key.

Requirements: Android 8.0 or newer, with Bluetooth LE advertising support. Almost every phone from 2018 onwards has it. On Android 11 and older, Location must also be **on**, because Android requires it for BLE scanning.

## 2. First run

The app opens on a 3D map of the mesh: your phone is the amber lantern, and every phone it hears stands where its signal strength puts it. Real messages fly along the links as light. Drag to orbit, pinch to zoom, and tap a phone to fly to it. The tabs at the bottom (Mesh, Send, Route, Defend, Lab) each move the camera to their own shot. Drag the panel's handle up for more room.

1. Open **Mesh Testbed**, give the phone a name (e.g. *Hardhik*), and tap **Start**. Allow the Bluetooth permissions.
2. Do the same on the other phones. Within a few seconds each phone shows the others in the 3D map and under **Phones nearby** in the **Mesh** chapter.
3. Keep the app open with the screen on (the app keeps it awake). Android throttles BLE scanning in the background.

## 3. Make a multi-hop chain in one room

BLE reaches across a whole room, so every phone hears every other phone. Force a chain A – B – C – D:

- **Block (easiest):** tap a phone on the map or in the list, then **Block this phone**. On A, block C and D. On B, block D. On C, block A. On D, block A and B.
- **Or the range slider:** spread the phones 3–8 m apart and raise "Ignore phones weaker than …" until each phone only lists its chain neighbours.

Check by sending A → D in the **Send** chapter. The delivered message should say **3 hops**.

## 4. Experiments for the report

Run each one twice, once in **MARL** and once in **Flooding**. Set the mode on *every* phone; the sender's mode decides how a message travels.

| # | Setup | What it shows |
|---|---|---|
| E1 | 4–5 phones, chain topology, *Lab → Run experiment*, 30 messages, 3 s interval, 20% SOS, run from two phones at once | Delivery ratio, RTT, frames per delivered message |
| E2 | Same, but walk one middle phone out of range and back during the run | Store-carry-forward vs flooding under partitions |
| E3 | Mesh topology (no blocks), MARL. In one middle phone, open **Defend** and switch on **Act as the attacker**, then run 30 messages from the others | Packets swallowed, time until the others quarantine it |
| E4 | Leave all phones running for 10 minutes with background messages, MARL | Federated rounds and weights converging (Route chapter: *What this phone has learned*), battery drop |

Tip: tap **Reset results** (Lab) on every phone before each run, and note the clock time when each run starts.

## 5. Collect and analyse

1. On each phone: **Lab → Save CSV**. The file goes to *Downloads/mesh_<id>_<time>.csv*. You can also use **Share CSV** to send it to yourself.
2. Copy all CSVs into one folder on the laptop, e.g. `field_logs/`.
3. Run:

```bash
python tools/analyze_field_logs.py field_logs/ --since 2026-10-10T14:00 --until 2026-10-10T14:20
```

The script prints a Markdown table per mode (PDR, SOS PDR, RTT, hops, frames and bytes per delivered message), battery drop per phone, and every sinkhole quarantine with its detection time, ready for the slides.

## Notes and known limits

- **RTT** is measured on the source phone (send → delivery ACK back), so phone clocks don't need to be in sync.
- **Sending a frame** takes a GATT connection (~0.3–1.5 s per hop). Real latency is therefore higher than in the simulator. That is a genuine finding to report.
- **The 2-hop ACK is not cryptographically signed,** so a smarter attacker could forge it. BitChat's Ed25519 keys would fix this (future work).
- **The trust threshold is lower on phones** (`cusumH = 6`) than in the simulator (12), so detection is visible within one 30-message run. Mention this in the report.

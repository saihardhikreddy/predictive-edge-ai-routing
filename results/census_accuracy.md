# Survivor census: accuracy of the 256-bit sketch

Each phone sets one bit per phone id (hashed) in a 256-bit sketch and merges neighbours' sketches with a bitwise OR.
The count is estimated as n ≈ −256 · ln(zero bits / 256). 200 random meshes per size (`tools/CensusAccuracy.kt`):

| Phones in mesh | Mean estimate | 10th–90th percentile | Worst error |
|---|---|---|---|
| 3 | 3.0 | 3–3 | 1 |
| 5 | 5.0 | 5–5 | 1 |
| 10 | 9.8 | 9–10 | 2 |
| 20 | 20.2 | 19–21 | 3 |
| 30 | 30.3 | 29–32 | 5 |
| 48 | 47.8 | 45–51 | 7 |
| 75 | 75.6 | 71–80 | 11 |
| 100 | 100.6 | 94–106 | 11 |
| 150 | 150.3 | 140–160 | 36 |
| 200 | 199.5 | 188–212 | 32 |

- Unbiased, and within about ±6 % (10th–90th percentile) up to 100 phones, with a fixed 32 bytes per count.
- Gossip in a chain of 30 phones, each merging only with its neighbours, then 50 more rounds of repeated
  contacts: every phone reports exactly 30. Meeting the same phone again never inflates the count.
- Windows: a phone that stops re-announcing itself drops out within two 10-minute windows.
- The same sketch counts SOS calls raised and SOS calls that reached someone; the difference is the
  number still waiting for help.

Limitation: an attacker can set every bit and make the count saturate. A per-sender check (a phone may
add at most a few bits per window) would bound this; not implemented yet.

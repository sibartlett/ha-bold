# Changelog

## 1.0.0 (unreleased)

The first release: a new integration for Bold Smart Locks, written from
scratch.

### Locks

- Unlock through a Bold Connect, or directly over Bluetooth when Home
  Assistant can hear the lock (through its own adapter, or an ESPHome
  Bluetooth proxy). Bluetooth is faster, works without internet, and works for
  locks without a Bold Connect.
- Choose per lock: prefer the Bold Connect (the default), prefer Bluetooth, or
  use only one. With a preference, the other way is tried when the first fails.
- Locks with the Classic Upgrade and locked status turned on show whether
  they're locked, updated within seconds when turned by hand. Other locks show
  when they're activated.
- **Lock** ends an activation early.

### Activity

- An activity entity for each lock fires for activations (with who, and how:
  PIN, button, app, key fob…), failed activations such as a wrong PIN,
  deactivations, tamper alerts, and the bolt being locked or unlocked.
- Pushed by Bold within seconds when Home Assistant is reachable from the
  internet (an external URL, or Home Assistant Cloud); polled otherwise.

### Batteries, signal and firmware

- Battery level, a low-battery sensor, and battery voltages at rest and under
  load from each lock's daily status report.
- How well each lock reaches its Bold Connect, and how well Home Assistant
  hears it over Bluetooth.
- Whether each lock and Bold Connect is on the firmware Bold requires.
- For each Bold Connect: whether it's online, and when Bold last heard from it.

### Setup and upkeep

- Sign in through Home Assistant Cloud, or your own Bold OAuth client.
- Discovered from a Bold lock's Bluetooth advertisements, or a Bold Connect
  joining the network.
- Locks and Bold Connects added to or removed from the Bold account follow
  automatically.
- Repairs for a Bold Connect that's offline, a Bluetooth-only lock that's out
  of range, and a lock Home Assistant can't reach at all.
- Diagnostics, with personal details and keys removed.
- Requires Home Assistant 2026.8 or later.

### Switching from the older Bold integration

This integration uses the same `bold` domain as the older one
([lwestenberg/homeassistant_bold](https://github.com/lwestenberg/homeassistant_bold)),
so the two can't be installed together:

1. Delete the old integration under **Settings → Devices & services → Bold**.
2. Remove it in HACS, and restart Home Assistant.
3. Install this one as described in the [README](README.md#installation), and
   add it again. Entity IDs may differ, so check automations and dashboards
   that used the old entities.

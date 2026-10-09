# Changelog

## Unreleased

- A lock with locked status on can be linked to its door's contact sensor,
  from the integration's page. It then shows as unlocked once the door has
  opened since it last reported locked, catching unlocks the lock missed.
- An activation's activity says whether the Bold app activated the lock
  automatically, as a phone came near, in its `automatic` attribute.
- An activation's or deactivation's activity names the app that sent it, such
  as the Bold app or Home Assistant, in its `client` attribute.

## 1.1.0 (2026-10-07)

### Bold Connect with Controller on

- A Bold Connect with its **Controller** setting on opens whatever its relay is
  wired to: a door strike, a gate or a garage door. Bold doesn't say which, so
  it gets both a lock and an **Activate** button, disabled by default: enable
  the one that fits, as the README describes. The lock suits a door strike,
  and Google Assistant only unlocks it with a PIN; the button suits a gate or
  garage door, or a relay set to pulse.
- An activity entity for the Connect, enabled, shows who opened it and how,
  whether from Home Assistant, the Bold app or the Connect's own button.
- The lock and button are unavailable while Controller is off, or while Bold
  doesn't allow remote access.

### Changes

- Entities for features turned on in the Bold app, such as a Connect's
  Controller setting or a lock's event log, appear within 10 minutes, without
  reloading the integration.
- A Bold Connect's last seen sensor is disabled by default for new installs,
  as it changes at almost every update; its connectivity sensor says whether
  it's online. Existing ones stay enabled, and can be disabled.

### Fixes

- A lock whose clock runs ahead of Home Assistant's no longer shows as
  unlocked for longer than an activation lasts, or stays unlocking after an
  activation is ended early.
- An activity's time is never in the future, even from a device whose clock
  runs ahead.
- Errors Bold reports with HTTP 400, such as a Bold Connect needing a firmware
  update to end an activation early, show Bold's reason instead of "HTTP 400".

## 1.0.2 (2026-09-28)

- No changes to the integration. HACS now installs it from a zip attached to
  each release, so it can show how many times it's been downloaded.

## 1.0.1 (2026-09-28)

- A lock that reports its bolt, activated while unlocked, shows as locking
  until it's turned, instead of unlocked, or unlocking once turned to locked.
- Once a lock is turned during an activation, it shows the bolt's new position
  straight away, rather than unlocking or locking until the activation ends.

## 1.0.0 (2026-09-26)

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

- An activity entity for each lock fires for activations (with how: PIN,
  button or Bluetooth, which covers the app, Home Assistant and a Bold Connect;
  and who, when Bold knows), failed activations such as a wrong PIN,
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

This integration uses the same `bold` domain as the older one, so the two
can't be installed together: remove the old one first, as described in the
[README](README.md#switching-from-the-older-bold-integration).

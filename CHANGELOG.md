# Changelog

## 1.2.0 (2026-10-09)

### Link a lock to its door sensor

Bold locks occasionally miss being turned, and keep showing their last
position, such as locked while the door is actually open. If the door has a
contact sensor, you can now link the two: once the door has opened, the lock
shows as unlocked until it next reports locked.

- Choose **Link a door sensor** on the Bold integration's page. Any lock with
  locked status turned on can be linked.
- Links keep working when you rename the lock or sensor, or change the
  sensor's entity ID, and their titles follow the new names.
- A repair tells you if a link stops working: its sensor was deleted or
  disabled, or the lock's locked status was turned off.

See [Linking a lock to its door sensor](docs/door-sensors.md).

### Activity

- **`automatic`** says whether the Bold app activated the lock as a phone
  came near.
- **`client`** names the app behind an activation or deactivation, such as
  the Bold app or Home Assistant.

### Documentation

- The README is shorter, with one-click install buttons. The details moved
  to pages under [docs](docs/), with new automation examples.

## 1.1.0 (2026-10-07)

### Use a Bold Connect as a door, gate or garage opener

With its **Controller** setting on in the Bold app, a Bold Connect switches
its relay when activated, to open whatever it's wired to. Bold doesn't say
what that is, so the Connect now gets both a lock and an **Activate** button.
Both are disabled by default: enable the one that fits.

- **The lock** suits a door strike. Google Assistant only unlocks it with a
  PIN.
- **The button** suits a gate or garage door, or a relay set to pulse.
- **An activity entity**, enabled, shows who opened it and how: from Home
  Assistant, the Bold app or the Connect's own button.
- The lock and button are unavailable while Controller is off, or while Bold
  doesn't allow remote access.

See [Using a Bold Connect as a door, gate or garage opener](docs/controller.md).

### Changes

- **New features appear by themselves.** Turn on a feature in the Bold app,
  such as a Connect's Controller setting or a lock's event log, and its
  entities appear within 10 minutes, without reloading the integration.
- **Last seen is disabled by default** on new installs, as a Bold Connect's
  last seen sensor changes at almost every update. Its connectivity sensor
  says whether it's online. If you already have it, it stays enabled.

### Fixes

- **Locks whose clock runs ahead** of Home Assistant's no longer show as
  unlocked for longer than an activation lasts, or stay unlocking after an
  activation is ended early.
- **Activity times** are never in the future, even from a device whose clock
  runs ahead.
- **Errors from Bold** now show Bold's reason instead of "HTTP 400", such as a
  Bold Connect needing a firmware update to end an activation early.

## 1.0.2 (2026-09-28)

No changes to the integration. HACS now installs it from a zip attached to
each release, so it can show how many times it's been downloaded.

## 1.0.1 (2026-09-28)

### Fixes

- **Activating an unlocked lock** with locked status now shows it as locking
  until it's turned, rather than unlocked, or unlocking once it's locked.
- **Turning a lock during an activation** shows the bolt's new position
  straight away, rather than unlocking or locking until the activation ends.

## 1.0.0 (2026-09-26)

The first release: a new integration for Bold Smart Locks, written from
scratch.

### Locks

- **Unlock through a Bold Connect, or directly over Bluetooth** when Home
  Assistant can hear the lock, through its own adapter or an ESPHome
  Bluetooth proxy. Bluetooth is faster, works without internet, and works for
  locks without a Bold Connect.
- **Choose how each lock is unlocked:** prefer the Bold Connect (the
  default), prefer Bluetooth, or use only one. With a preference, the other
  way is tried if the first fails.
- **See whether a door is locked.** Locks with the Classic Upgrade and locked
  status turned on show their bolt's position, updated within seconds when
  turned by hand. Other locks show when they're activated.
- **Lock** ends an activation early.

### Activity

- **An activity entity for each lock** fires when it's activated, fails to
  activate (such as a wrong PIN), is deactivated, is tampered with, or is
  locked or unlocked. It says how, such as by PIN, button or Bluetooth, and
  who, when Bold knows.
- **Updates arrive within seconds** when Home Assistant is reachable from the
  internet, through an external URL or Home Assistant Cloud. Otherwise, the
  integration checks regularly.

### Batteries, signal and firmware

- **Batteries:** each lock's battery level, a low-battery sensor, and battery
  voltages at rest and under load, from its daily status report.
- **Signal:** how well each lock reaches its Bold Connect, and how well Home
  Assistant hears it over Bluetooth.
- **Firmware:** whether each lock and Bold Connect is on the version Bold
  requires.
- **Bold Connects:** whether each one is online, and when Bold last heard
  from it.

### Setup and upkeep

- **Sign in** through Home Assistant Cloud, or your own Bold OAuth client.
- **Discovered automatically** from a Bold lock's Bluetooth advertisements, or
  a Bold Connect joining your network.
- **Devices stay in sync:** locks and Bold Connects added to or removed from
  your Bold account appear and disappear by themselves.
- **Repairs** tell you when a Bold Connect is offline, a Bluetooth-only lock
  is out of range, or Home Assistant can't reach a lock at all.
- **Diagnostics**, with personal details and keys removed.
- Requires Home Assistant 2026.8 or later.

### Coming from the older Bold integration?

This integration uses the same `bold` domain as the older one, so the two
can't be installed together. Remove the old one first, as described in the
[README](README.md#coming-from-the-older-bold-integration).

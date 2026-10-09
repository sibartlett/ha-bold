# Bold Smart Lock for Home Assistant

A Home Assistant integration for [Bold Smart Locks](https://boldsmartlock.com):
smart cylinders that replace a door's regular cylinder, and are opened with the
Bold app, a PIN, a key fob or remotely through a Bold Connect.

The integration connects to your Bold account through the
[Bold API](https://apidoc.boldsmartlock.com/). It lets you unlock your locks
remotely, see who opened them and how, and keep an eye on batteries, signal and
firmware.

## Supported devices

| Device | Support |
|---|---|
| Bold Smart Cylinder | ✅ Tested with the Bold Classic, with and without the Classic Upgrade (which lets it report whether it's locked). The Bold Elite should be supported, but has not been tested. |
| Bold Connect | ✅ Unlocks locks from anywhere, through Bold's cloud. A Connect with its **Controller** setting on can also open what its relay is wired to, such as a building's entrance, a gate or a garage door. |
| Bold Clicker (key fob) | ➖ Ignored. Its activity shows up on the lock it opens. |

Home Assistant can unlock a lock in two ways:

- **Through a Bold Connect** near the lock, via Bold's cloud.
- **Over Bluetooth**, directly, when Home Assistant can hear the lock: through
  its own Bluetooth adapter, or an
  [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html)
  near the door. This is faster, works when the internet is down, and works for
  locks without a Bold Connect.

## Installation

Requires Home Assistant 2026.8 or later.

1. In HACS, add `https://github.com/sibartlett/ha-bold` as a custom repository
   (type: Integration), then download **Bold Smart Lock**.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration**, choose
   **Bold Smart Lock** and sign in with your Bold account.

Signing in needs one of:

- **Home Assistant Cloud:** if you're logged in to Home Assistant Cloud, pick it
  when asked how to sign in. There's nothing else to configure.
- **Your own Bold OAuth client:** Bold issues custom clients free of charge
  ([request one](https://sesamsolutions.gitlab.io/public-documentation/integration/oauth-authentication.html)),
  with `https://my.home-assistant.io/redirect/oauth` as the redirect URI. Add its
  client ID and secret under
  **Settings → Devices & services → ⋮ → Application credentials** before adding
  the integration.

There are no other settings. Each Bold account can be added once.

For activity to appear within seconds, Bold needs to reach Home Assistant from
the internet: set an external URL (**Settings → System → Network**), or use
Home Assistant Cloud. Without that, activity is polled instead (see
[How data is updated](https://github.com/sibartlett/ha-bold/blob/main/docs/how-it-works.md)).

If Home Assistant can hear a Bold lock over Bluetooth, or sees a Bold Connect
join your network, it offers to set up Bold under
**Settings → Devices & services → Discovered**.

### Switching from the older Bold integration

This integration replaces the older one
([lwestenberg/homeassistant_bold](https://github.com/lwestenberg/homeassistant_bold)),
and uses the same `bold` domain, so the two can't be installed together:

1. Delete the old integration under **Settings → Devices & services → Bold**.
2. Remove it in HACS, and restart Home Assistant.
3. Install this one as above, and add it again.

Entity IDs may differ, so check automations and dashboards that used the old
ones.

## Entities

Each lock gets a `lock` to unlock it, an `event` for its activity (who opened
it, and how), sensors for its battery and signal, and a firmware `update`.
With Bluetooth, a `select` chooses whether it's unlocked through its Bold
Connect or over Bluetooth. Each Bold Connect gets a connectivity sensor and a
firmware `update`. See [Entities](https://github.com/sibartlett/ha-bold/blob/main/docs/entities.md) for the details.

- [Link a lock to its door sensor](https://github.com/sibartlett/ha-bold/blob/main/docs/door-sensors.md), for a
  more reliable lock status.
- [A Bold Connect with its Controller setting on](https://github.com/sibartlett/ha-bold/blob/main/docs/controller.md)
  can open a door, gate or garage door.

## Known limitations

- **Bolt position needs the Classic Upgrade** (or a lock that reports it),
  with locked status on. Other locks' state shows whether they're
  _activated_, not whether the bolt is thrown, as an assumed state.
  Bolt changes appear within seconds with pushes, or about 30 seconds without.
- **Lock can't throw the bolt.** Bold locks are turned by hand; **Lock** only
  ends an activation early.
- **Delays.** Activity from outside Home Assistant (app, PIN, button, key fob)
  appears within seconds when Bold can push it, and within about 30 seconds
  otherwise. A Bold Connect going offline is noticed
  after 30–40 minutes.
- **Locks without a Bold Connect** only report activity to Bold (and so to
  Home Assistant) when a phone with the Bold app passes by.
- **Battery levels** are the five levels Bold reports, not percentages.

## Documentation

- [Entities](https://github.com/sibartlett/ha-bold/blob/main/docs/entities.md)
- [Linking a lock to its door sensor](https://github.com/sibartlett/ha-bold/blob/main/docs/door-sensors.md)
- [A Bold Connect with its Controller setting on](https://github.com/sibartlett/ha-bold/blob/main/docs/controller.md)
- [How data is updated](https://github.com/sibartlett/ha-bold/blob/main/docs/how-it-works.md)
- [Automations](https://github.com/sibartlett/ha-bold/blob/main/docs/automations.md)
- [Troubleshooting and removal](https://github.com/sibartlett/ha-bold/blob/main/docs/troubleshooting.md)
- [Contributing](https://github.com/sibartlett/ha-bold/blob/main/CONTRIBUTING.md)

## Security

The integration stores Bluetooth keys that can unlock your locks: see
[where the keys are kept](https://github.com/sibartlett/ha-bold/blob/main/docs/how-it-works.md#where-the-keys-are-kept).
To report a security problem, see [SECURITY.md](https://github.com/sibartlett/ha-bold/blob/main/SECURITY.md).

## License

The code is licensed under the [Apache License 2.0](https://github.com/sibartlett/ha-bold/blob/main/LICENSE). The Bluetooth
protocol is ported from
[homebridge-bold-ble](https://github.com/robbertkl/homebridge-bold-ble) (MIT). The Bold name and
logos are trademarks of Bold Smart Lock.

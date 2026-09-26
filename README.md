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
| Bold Connect | ✅ Unlocks locks from anywhere, through Bold's cloud. |
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
[How data is updated](#how-data-is-updated)).

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

A Bold lock is not motorised: unlocking it _activates_ the cylinder, so it can
be turned by hand for a few seconds (the activation time set in the Bold app).
Each lock gets:

| Entity | What it does |
|---|---|
| `lock.<lock>` | **Unlock** activates the lock. Locks that report their bolt position show it: locked or unlocked, and unlocking while activated and waiting to be turned. Other locks show as unlocked while activated and locked otherwise, as an assumed state. **Lock** ends an activation early. `changed_by` shows who last activated or deactivated it. |
| `event.<lock>_activity` | Fires for activations (with how: PIN, button or Bluetooth, which covers the app, Home Assistant and a Bold Connect; and who, when Bold knows), failed activations such as a wrong PIN, deactivations, tamper alerts (including repeated wrong PINs), and, for locks that report their bolt position, the bolt being locked or unlocked. |
| `sensor.<lock>_battery_level` | Battery level as Bold reports it: Excellent, High, Medium, Low or Critical. |
| `binary_sensor.<lock>_battery` | Low battery: on when the level is Low or Critical. |
| `sensor.<lock>_battery_voltage` | Battery voltage at rest, from the lock's daily status report (and occasional extra readings). |
| `sensor.<lock>_battery_voltage_under_load` | Battery voltage under load, from the daily status report. Weak batteries sag under load before they drop at rest, so this is the earlier warning. Unknown for a lock that doesn't measure it, e.g. on days its motor didn't run. |
| `sensor.<lock>_bold_connect_signal` | How well the lock reaches its Bold Connect: Excellent, High, Medium, Low or Critical. |
| `sensor.<lock>_bold_connect_signal_strength` | The same signal in dBm. Disabled by default. |
| `sensor.<lock>_bluetooth_signal` | How well Home Assistant hears the lock over Bluetooth, in dBm; unavailable when it can't. Handy for placing an ESPHome Bluetooth proxy. Only when Home Assistant has Bluetooth. |
| `update.<lock>_firmware` | Whether the lock is on the firmware version Bold requires. |
| `select.<lock>_unlock_method` | For locks with a Bold Connect, when Home Assistant has Bluetooth: **Prefer Bold Connect** (the default), **Prefer Bluetooth**, **Bluetooth only** or **Bold Connect only**. With a preference, the other way is used when the first fails. With **Prefer Bluetooth**, Bluetooth is only tried first when Home Assistant hears the lock well (−85 dBm or better). |

Each Bold Connect is a device too, and the locks it serves are linked to it:

| Entity | What it does |
|---|---|
| `binary_sensor.<connect>_connectivity` | Online while Bold has heard from the Connect in the last 30 minutes. |
| `sensor.<connect>_last_seen` | When Bold last heard from the Connect. |
| `update.<connect>_firmware` | Whether the Connect is on the firmware version Bold requires. |

Locks and Bold Connects added to your Bold account appear automatically, and
ones removed from it are removed from Home Assistant.

To see whether a lock is locked, a Bold Elite or an upgraded Bold Classic is required, with **locked status** turned on in the Bold app. Then set
or turn the lock once: until then Bold doesn't know its position. Home
Assistant switches over within seconds.

The activity entity's `event_type` is one of `activated`, `activation_failed`,
`deactivated`, `tamper`, `locked` or `unlocked`. Its attributes say when it
happened (`time`) and who did it (`user`, when Bold knows); activations and
deactivations add the `method` (e.g. `Pin`, `Button`, `Ble`) and whether it
was `remote`, activations their `result`, and tamper alerts the `tamper_type`
(`vibration`, `rotations` or `faulty_pin`).

## How data is updated

**Pushed within seconds**, when Home Assistant is reachable from the internet
(through its external URL, or Home Assistant Cloud): the integration registers a
webhook with Bold, which sends activations, bolt changes, tamper alerts and
daily status reports as they happen. Deliveries are checked against a secret
only Bold and Home Assistant know. The webhook is kept up to date across
restarts, and removed with the integration.

**Polled** otherwise, and as a safety net:

- **Activity** (the event log) every 30 seconds, or every 5 minutes while
  pushes are working. If a poll finds an event the webhook should have pushed,
  polling goes back to every 30 seconds until the webhook delivers again.
  Locks upload their events when a Bold Connect or phone next syncs with them,
  which can be later, so every 10 minutes a poll looks back an hour to pick up
  events that arrived late.
- **Devices** (battery, signal, firmware, Bold Connect status) every 10 minutes.
- **Battery voltages** come from a status report each lock sends once a day, at
  a fixed time. They keep their last reading across restarts, and start from
  the past week's readings when the integration is set up.

Unlocking from Home Assistant updates the lock straight away.

For Bluetooth, Bold's cloud issues each lock a handshake (valid for about a
week) and signed commands. The integration fetches them every 12 hours and
stores them, so locks in Bluetooth range can be unlocked for several days
without internet. Home Assistant tracks which locks it can hear as they
advertise.

## Use cases

- Unlock the door from a dashboard, a voice assistant or an automation, e.g.
  for a delivery or a guest.
- Get notified about failed PIN attempts or tamper alerts.
- Know who came home, and whether they used the app, a PIN or a key fob.
- Get warned when a lock's batteries run low or the Bold Connect goes offline,
  before remote unlocking stops working.

## Examples

Notify on a wrong PIN or a tamper alert:

```yaml
alias: Front door security alert
triggers:
  - trigger: state
    entity_id: event.front_door_activity
    not_from: [unavailable, unknown]
conditions:
  - condition: state
    entity_id: event.front_door_activity
    attribute: event_type
    state: [activation_failed, tamper]
actions:
  - action: notify.notify
    data:
      message: >
        Front door: {{ trigger.to_state.attributes.event_type | replace("_", " ") }}
        ({{ trigger.to_state.attributes.method or trigger.to_state.attributes.tamper_type }})
```

Log who opened the door, and how:

```yaml
alias: Front door opened
triggers:
  - trigger: state
    entity_id: event.front_door_activity
    not_from: [unavailable, unknown]
conditions:
  - condition: state
    entity_id: event.front_door_activity
    attribute: event_type
    state: activated
actions:
  - action: logbook.log
    data:
      name: Front door
      message: >
        opened by {{ trigger.to_state.attributes.user or "someone" }}
        using {{ trigger.to_state.attributes.method }}
```

Warn when the Bold Connect is offline:

```yaml
alias: Bold Connect offline
triggers:
  - trigger: state
    entity_id: binary_sensor.bold_connect_connectivity
    to: "off"
actions:
  - action: notify.notify
    data:
      message: The Bold Connect is offline, so the locks can't be unlocked remotely.
```

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

## Troubleshooting

Home Assistant raises a repair (**Settings → System → Repairs**) when a Bold
Connect has been offline for an hour, when a lock that can only be unlocked
over Bluetooth has been out of range for an hour, or when a lock has no way to
be unlocked from Home Assistant at all. Repairs clear themselves once the
problem is gone. You can ignore one, e.g. for a lock that's only in range some
of the time; it's raised again if the problem comes back after being fixed.

- **A lock is unavailable.** Home Assistant has no way to reach it: no Bold
  Connect it can use (none assigned in the Bold app, or Bold can't be
  reached), and it isn't in Bluetooth range. Check the lock's Bold Connect
  signal and that the Connect is online, or its Bluetooth signal.
- **Unlocking fails with "No Bold Connect is available".** The Connect is
  offline or out of range of the lock. Check its power and Wi-Fi, and its
  `connectivity` sensor.
- **A lock isn't unlocked over Bluetooth.** Home Assistant needs to hear the
  lock well: add an ESPHome Bluetooth proxy near the door. The integration's
  diagnostics show whether each lock is reachable, and when its Bluetooth keys
  expire. When unlocking over Bluetooth fails, the log says why before falling
  back to the Bold Connect.
- **Unlocking fails with "Too many requests".** Bold limits how often locks can
  be activated. Wait a moment and try again.
- **A lock has no activity entity.** The lock doesn't support Bold's event log.
  If the log says the account "is not allowed to read the event log", your Bold
  account doesn't have access to it.
- **Activity takes up to 30 seconds to appear.** Bold isn't pushing it. Home
  Assistant needs an external URL Bold can reach, or Home Assistant Cloud. The
  integration's diagnostics show whether pushes are active, and when the last
  one arrived; debug logging shows why the webhook couldn't be set up. After changing the external URL, reload the
  integration so the webhook points at the new address.
- **The lock shows locked, but someone just opened it.** Locks that don't
  report their bolt position only show as unlocked while activated (usually a
  few seconds), which can be over before the activity arrives.
- **Home Assistant asks to re-authenticate.** Your Bold sign-in expired or was
  revoked. Follow the prompt and sign in with the same Bold account.

When reporting a problem, include the integration's diagnostics
(**Settings → Devices & services → Bold Smart Lock → ⋮ → Download diagnostics**)
and debug logs (**⋮ → Enable debug logging**, reproduce the problem, then
disable it to download the log). Personal details are removed from diagnostics.

## Removal

1. Go to **Settings → Devices & services → Bold Smart Lock**, open the **⋮**
   menu and choose **Delete**. This also removes the webhook the integration
   registered with Bold, and deletes the Bluetooth keys stored for your locks.
2. To remove the integration's files too, remove **Bold Smart Lock** in HACS and
   restart Home Assistant.
3. If you added your own Bold OAuth client, you can remove it under
   **Settings → Devices & services → ⋮ → Application credentials**.

## Development

The Bold API client and Bluetooth protocol live in
`custom_components/bold/boldsmartlock/`, which doesn't depend on Home Assistant,
so in the future it can become a standalone library (as Home Assistant core
requires). A test keeps it that way.

```sh
pip install -r requirements_test.txt pre-commit
pre-commit install  # runs ruff and mypy before each commit
pytest --cov=custom_components.bold
python script/translations.py  # after changing strings.json
pytest --snapshot-update  # after changing entities or diagnostics; review the diff
HYPOTHESIS_PROFILE=thorough pytest tests/test_fuzz.py  # after changing parsing
```

CI requires 100% test coverage, and also runs the tests against the oldest
Home Assistant version in `hacs.json`.

## Security

The Bluetooth keys are stored in Home Assistant's `.storage` folder, like your
Bold sign-in and the webhook's secret. Anyone who can read that folder (or a
backup of it) could unlock your locks over Bluetooth, from within Bluetooth
range, until the keys expire (about a week). Diagnostics never include any of
them.

To report a security problem, see [SECURITY.md](SECURITY.md).

## License

The code is licensed under the [Apache License 2.0](LICENSE). The Bluetooth
protocol is ported from
[homebridge-bold-ble](https://github.com/robbertkl/homebridge-bold-ble) (MIT). The Bold name and
logos are trademarks of Bold Smart Lock.

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
| Bold Smart Cylinder | ✅ Tested with the Bold Classic (SX33); other cylinder models should work the same way. |
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

If Home Assistant can hear a Bold lock over Bluetooth, or sees a Bold Connect
join your network, it offers to set up Bold under
**Settings → Devices & services → Discovered**.

## Entities

A Bold lock is not motorised: unlocking it _activates_ the cylinder, so it can
be turned by hand for a few seconds (the activation time set in the Bold app).
Each lock gets:

| Entity | What it does |
|---|---|
| `lock.<lock>` | **Unlock** activates the lock through your Bold Connect. The lock shows as unlocked while it is activated, and locked otherwise. **Lock** ends an activation early. `changed_by` shows who last activated or deactivated it. |
| `event.<lock>_activity` | Fires for activations (with the user and method: PIN, button, app…), failed activations such as a wrong PIN, deactivations, and tamper alerts. |
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

## How data is updated

Bold only offers push updates (webhooks) to business organizations, so the
integration polls Bold's cloud:

- **Activity** (the event log) every 30 seconds. Activations, changes to
  `changed_by` and activity events show up within about 30 seconds of reaching
  Bold. Locks upload their events when a Bold Connect or phone next syncs with
  them, which can be later, so every 10 minutes a poll looks back an hour to
  pick up events that arrived late, such as battery voltage readings.
- **Battery voltages** come from a status report each lock
  sends once a day, at a fixed time. They keep their last reading across
  restarts, and start from the past week's readings when the integration is set
  up.
- **Devices** (battery, signal, firmware, Bold Connect status) every 10 minutes.

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
  - condition: template
    value_template: >
      {{ trigger.to_state.attributes.event_type in ["activation_failed", "tamper"] }}
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

- **No bolt position.** The lock's state shows whether it is _activated_, not
  whether the door is actually open: it's marked as an assumed state. Locks
  that report their bolt position aren't supported yet.
- **Lock can't throw the bolt.** Bold locks are turned by hand; **Lock** only
  ends an activation early.
- **Delays.** Activity from outside Home Assistant (app, PIN, button, key fob)
  appears within about 30 seconds. A Bold Connect going offline is noticed
  after 30–40 minutes.
- **Bluetooth uses an undocumented part of Bold's API**, the one the Bold app
  uses. Bold could change it without notice; the Bold Connect keeps working
  either way.
- **Locks without a Bold Connect** only report activity to Bold (and so to
  Home Assistant) when a phone with the Bold app passes by.
- **Keep-active mode isn't supported.** It's a Bold Pro feature. Keep-active
  periods started from the Bold app are shown on the lock.
- **Firmware.** Bold only reports the firmware version it _requires_, which may
  not be the newest release. Firmware is updated from the Bold app.
- **Battery levels** are the five levels Bold reports, not percentages.

## Troubleshooting

- **A lock is unavailable.** It has no Bold Connect assigned in the Bold app, or
  the integration can't reach Bold. Check the lock's Bold Connect signal, and
  that the Connect is online.
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
- **The lock shows locked, but someone just opened it.** Activity from outside
  Home Assistant takes up to 30 seconds to appear, and the lock only shows as
  unlocked while it is activated (usually a few seconds).
- **Home Assistant asks to re-authenticate.** Your Bold sign-in expired or was
  revoked. Follow the prompt and sign in with the same Bold account.

When reporting a problem, include the integration's diagnostics
(**Settings → Devices & services → Bold Smart Lock → ⋮ → Download diagnostics**)
and debug logs (**⋮ → Enable debug logging**, reproduce the problem, then
disable it to download the log). Personal details are removed from diagnostics.

## Removal

1. Go to **Settings → Devices & services → Bold Smart Lock**, open the **⋮**
   menu and choose **Delete**.
2. To remove the integration's files too, remove **Bold Smart Lock** in HACS and
   restart Home Assistant.
   This also deletes the Bluetooth keys stored for your locks.
3. If you added your own Bold OAuth client, you can remove it under
   **Settings → Devices & services → ⋮ → Application credentials**.

## Development

```sh
pip install -r requirements_test.txt ruff mypy
pytest --cov=custom_components.bold
ruff check . && ruff format --check .
mypy
python script/translations.py  # after changing strings.json
```

## Security

The Bluetooth keys are stored in Home Assistant's `.storage` folder, like your
Bold sign-in. Anyone who can read that folder (or a backup of it) could unlock
your locks over Bluetooth, from within Bluetooth range, until the keys expire
(about a week). Diagnostics never include them.

## License

The code is licensed under the [Apache License 2.0](LICENSE). The Bluetooth
protocol is ported from
[homebridge-bold-ble](https://github.com/robbertkl/homebridge-bold-ble) (MIT). The Bold name and
logos are trademarks of Bold Smart Lock.

# Entities

A Bold lock is not motorised: unlocking it _activates_ the cylinder, so it can
be turned by hand for a few seconds (the activation time set in the Bold app).
Each lock gets:

| Entity | What it does |
|---|---|
| `lock.<lock>` | **Unlock** activates the lock. Locks that report their bolt position show it: locked or unlocked, and, while activated and waiting to be turned, unlocking (if it was locked) or locking (if it was unlocked). Other locks show as unlocked while activated and locked otherwise, as an assumed state. **Lock** ends an activation early. `changed_by` shows who last activated or deactivated it. |
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

Locks with locked status can be linked to their door's contact sensor, for a more reliable lock status: see [Linking a lock to its door sensor](door-sensors.md).

Each Bold Connect is a device too, and the locks it serves are linked to it:

| Entity | What it does |
|---|---|
| `binary_sensor.<connect>_connectivity` | Online while Bold has heard from the Connect in the last 30 minutes. |
| `sensor.<connect>_last_seen` | When Bold last heard from the Connect. Disabled by default, as it changes at almost every update. |
| `update.<connect>_firmware` | Whether the Connect is on the firmware version Bold requires. |

A Bold Connect with its **Controller** setting on also gets a lock and a button: see [A Bold Connect with its Controller setting on](controller.md).

Locks and Bold Connects added to your Bold account appear automatically, and
ones removed from it are removed from Home Assistant. Entities for features
turned on later, such as a lock's event log, appear within 10 minutes too.

To see whether a lock is locked, a Bold Elite or an upgraded Bold Classic is required, with **locked status** turned on in the Bold app. Then set
or turn the lock once: until then Bold doesn't know its position. Home
Assistant switches over within seconds.

## Activity

The activity entity's `event_type` is one of `activated`, `activation_failed`,
`deactivated`, `tamper`, `locked` or `unlocked`. Its attributes say when it
happened (`time`, by the device's clock, but never later than it reached Home
Assistant) and who did it (`user`, when Bold knows); activations and
deactivations add the `method` (e.g. `Pin`, `Button`, `Ble`), whether it
was `remote` and the `client` that sent it (e.g. `BoldApp` or
`HomeAssistant`; none for the lock's button or keypad), activations their
`result` and `automatic` (whether the Bold app activated the lock as a phone
came near), and tamper alerts the `tamper_type` (`vibration`, `rotations` or
`faulty_pin`).

For examples of automations using the activity, see [Automations](automations.md).

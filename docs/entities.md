# Entities

Bold locks aren't motorised: unlocking one _activates_ it, so someone can turn
it by hand for a few seconds (the activation time you set in the Bold app).

## Each lock

| Entity | What it does |
|---|---|
| `lock.<lock>` | **Unlock** activates the lock, and **Lock** ends an activation early. With locked status on, it shows whether the bolt is locked or unlocked, and, while activated and waiting to be turned, unlocking or locking. Otherwise it shows unlocked while activated and locked the rest of the time, as an assumed state. `changed_by` shows who last activated or deactivated it. |
| `event.<lock>_activity` | Fires for activations, failed activations (such as a wrong PIN), deactivations, tamper alerts, and, with locked status on, the bolt being locked or unlocked. See [Activity](#activity) for what it tells you. |
| `sensor.<lock>_battery_level` | Bold's battery level: Excellent, High, Medium, Low or Critical. |
| `binary_sensor.<lock>_battery` | On when the battery is Low or Critical. |
| `sensor.<lock>_battery_voltage` | Battery voltage at rest, from the lock's daily status report and occasional extra readings. |
| `sensor.<lock>_battery_voltage_under_load` | Battery voltage under load, from the daily status report. Weak batteries sag under load before they drop at rest, so this warns you earlier. Unknown on days the lock doesn't measure it, such as when its motor didn't run. |
| `sensor.<lock>_bold_connect_signal` | How well the lock reaches its Bold Connect: Excellent, High, Medium, Low or Critical. |
| `sensor.<lock>_bold_connect_signal_strength` | The same signal, in dBm. Disabled by default. |
| `sensor.<lock>_bluetooth_signal` | How well Home Assistant hears the lock over Bluetooth, in dBm, or unavailable when it can't. Handy for placing an ESPHome Bluetooth proxy. Only when Home Assistant has Bluetooth. |
| `update.<lock>_firmware` | Whether the lock is on the firmware version Bold requires. |
| `select.<lock>_unlock_method` | How the lock is unlocked, when it has a Bold Connect and Home Assistant has Bluetooth: **Prefer Bold Connect** (the default), **Prefer Bluetooth**, **Bluetooth only** or **Bold Connect only**. With a preference, the other way is tried if the first fails. **Prefer Bluetooth** only tries Bluetooth first when Home Assistant hears the lock well (−85 dBm or better). |

For a more reliable lock status, you can
[link a lock to its door sensor](door-sensors.md).

## Each Bold Connect

The locks a Bold Connect serves are linked to it as devices.

| Entity | What it does |
|---|---|
| `binary_sensor.<connect>_connectivity` | On while Bold has heard from the Connect in the last 30 minutes. |
| `sensor.<connect>_last_seen` | When Bold last heard from the Connect. Disabled by default, as it changes at almost every update. |
| `update.<connect>_firmware` | Whether the Connect is on the firmware version Bold requires. |

With its **Controller** setting on, a Bold Connect also gets a lock and a
button: see [Using a Bold Connect as a door, gate or garage opener](controller.md).

## New and removed devices

Locks and Bold Connects you add to your Bold account appear automatically, and
ones you remove disappear from Home Assistant. Entities for features you turn
on later, such as a lock's event log, appear within 10 minutes too.

## Whether a door is locked

You'll need a Bold Elite or an upgraded Bold Classic, with **locked status**
turned on in the Bold app. Then lock or unlock it once, as Bold doesn't know
its position until then. Home Assistant picks it up within seconds.

## Activity

Each activity has an `event_type`: `activated`, `activation_failed`,
`deactivated`, `tamper`, `locked` or `unlocked`. Its attributes tell you more:

| Attribute | On | What it tells you |
|---|---|---|
| `time` | Everything | When it happened, by the device's clock, but never later than it reached Home Assistant. |
| `user` | Everything | Who did it, when Bold knows. |
| `method` | Activations and deactivations | How, such as `Pin`, `Button` or `Ble` (Bluetooth, from the app, Home Assistant or a Bold Connect). |
| `remote` | Activations and deactivations | Whether it went through a Bold Connect, rather than being done nearby. |
| `client` | Activations and deactivations | The app that sent it, such as `BoldApp` or `HomeAssistant`, or none for the lock's button or keypad. |
| `result` | Activations | Whether it succeeded, such as `Success` or `PinInvalid`. |
| `automatic` | Activations | Whether the Bold app activated the lock as a phone came near. |
| `tamper_type` | Tamper alerts | `vibration`, `rotations` or `faulty_pin` (repeated wrong PINs). |

For ideas on using these, see [Automations](automations.md).

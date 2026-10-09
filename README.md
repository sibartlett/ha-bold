# Bold Smart Lock for Home Assistant

Bring your [Bold Smart Locks](https://boldsmartlock.com) into Home Assistant.
Unlock your doors from a dashboard, an automation or your voice assistant, see
who came and went, and get a heads-up before a battery runs out.

## What you can do

- **Unlock from anywhere**, through a Bold Connect, or **directly over
  Bluetooth** when Home Assistant is in range, through its own adapter or an
  [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html)
  near the door. Bluetooth is faster and keeps working when the internet is
  down.
- **See who opened the door, and how**: the app, a PIN, the button or a key
  fob, usually within seconds.
- **Know whether a door is locked**, with a Bold Elite or an upgraded Bold
  Classic.
- **Get alerts** for wrong PINs, tamper warnings, low batteries, or a Bold
  Connect going offline.
- **Open a gate or garage door** wired to a Bold Connect.

## Supported devices

| Device | Support |
|---|---|
| Bold Smart Cylinder | ✅ Tested with the Bold Classic, with and without the Classic Upgrade. The Bold Elite should work too, but hasn't been tested. |
| Bold Connect | ✅ Unlocks your locks remotely. With its **Controller** setting on, it can also open a door, gate or garage door wired to it. |
| Bold Clicker (key fob) | ➖ Not added as a device, but whenever it opens a lock, that shows in the lock's activity. |

## Getting started

You'll need Home Assistant 2026.8 or later.

1. In HACS, add `https://github.com/sibartlett/ha-bold` as a custom repository
   (type: Integration), then download **Bold Smart Lock**.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration**, choose
   **Bold Smart Lock**, and sign in with your Bold account.

To sign in, you'll use either:

- **Home Assistant Cloud**, if you're subscribed: just pick it when asked.
- **Your own Bold OAuth client**, which Bold issues for free
  ([request one](https://sesamsolutions.gitlab.io/public-documentation/integration/oauth-authentication.html)).
  Use `https://my.home-assistant.io/redirect/oauth` as the redirect URI, and
  add the client ID and secret under
  **Settings → Devices & services → ⋮ → Application credentials** first.

That's it: your locks and Bold Connects appear automatically. Home Assistant
may also offer to set Bold up for you, under
**Settings → Devices & services → Discovered**, when it hears a Bold lock or
sees a Bold Connect.

**Tip:** for activity to show up within seconds, Bold needs to reach your Home
Assistant: use Home Assistant Cloud, or set an external URL under
**Settings → System → Network**. Otherwise it's checked every 30 seconds.

### Coming from the older Bold integration?

This one replaces
[lwestenberg/homeassistant_bold](https://github.com/lwestenberg/homeassistant_bold),
and the two can't be installed together. Delete the old one under
**Settings → Devices & services**, remove it in HACS and restart, then set this
one up as above. Your entity IDs may change, so check your automations and
dashboards afterwards.

## What you get

Each lock gets a **lock** to unlock it, an **activity** event showing who
opened it and how, **battery** and **signal** sensors, and a **firmware**
update entity. With Bluetooth, you can also choose how each lock is unlocked:
through its Bold Connect or over Bluetooth, with the other as a fallback. Each
Bold Connect gets a **connectivity** sensor and a **firmware** update entity.

Two optional extras:

- [**Link a lock to its door sensor**](https://github.com/sibartlett/ha-bold/blob/main/docs/door-sensors.md)
  for a more reliable lock status.
- [**Use a Bold Connect as a door, gate or garage opener**](https://github.com/sibartlett/ha-bold/blob/main/docs/controller.md)
  with its Controller setting on.

## Good to know

- **Bold locks aren't motorised.** Unlocking lets someone turn the lock by
  hand for a few seconds, and **Lock** just ends that early. Nothing can turn
  the bolt for you.
- **Whether a door is locked** needs a Bold Elite or an upgraded Bold
  Classic, with locked status turned on in the Bold app. Other locks show as
  unlocked only while they're activated.
- **Locks without a Bold Connect** only report activity when a phone with the
  Bold app passes by.

See all the [known limitations](https://github.com/sibartlett/ha-bold/blob/main/docs/troubleshooting.md#known-limitations).

## Learn more

- [Entities and their attributes](https://github.com/sibartlett/ha-bold/blob/main/docs/entities.md)
- [Linking a lock to its door sensor](https://github.com/sibartlett/ha-bold/blob/main/docs/door-sensors.md)
- [Using a Bold Connect as a door, gate or garage opener](https://github.com/sibartlett/ha-bold/blob/main/docs/controller.md)
- [Automation ideas and examples](https://github.com/sibartlett/ha-bold/blob/main/docs/automations.md)
- [How updates reach Home Assistant](https://github.com/sibartlett/ha-bold/blob/main/docs/how-it-works.md)
- [Troubleshooting, known limitations and removal](https://github.com/sibartlett/ha-bold/blob/main/docs/troubleshooting.md)
- [Contributing](https://github.com/sibartlett/ha-bold/blob/main/CONTRIBUTING.md)

## Security

To unlock over Bluetooth, the integration stores keys for your locks in Home
Assistant, so keep your backups safe. See
[where the keys are kept](https://github.com/sibartlett/ha-bold/blob/main/docs/how-it-works.md#where-the-keys-are-kept).
To report a security issue, see
[SECURITY.md](https://github.com/sibartlett/ha-bold/blob/main/SECURITY.md).

## License

Apache License 2.0: see
[LICENSE](https://github.com/sibartlett/ha-bold/blob/main/LICENSE). The
Bluetooth protocol is ported from
[homebridge-bold-ble](https://github.com/robbertkl/homebridge-bold-ble) (MIT).
Bold and its logos are trademarks of Bold Smart Lock.

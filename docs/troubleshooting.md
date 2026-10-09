# Troubleshooting

## Repairs

Home Assistant tells you under **Settings → System → Repairs** when:

- a Bold Connect has been offline for an hour;
- a lock that can only be unlocked over Bluetooth has been out of range for an
  hour;
- a lock can't be unlocked from Home Assistant at all.

Repairs clear themselves once the problem is gone. You can ignore one, such as
for a lock that's only in range some of the time, and it comes back if the
problem returns after being fixed.

## Common problems

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
- **Activity takes up to 30 seconds to appear.** Bold isn't pushing it: Home
  Assistant needs an external URL Bold can reach, or Home Assistant Cloud. The
  integration's diagnostics show whether pushes are working and when the last
  one arrived, and debug logging shows why the webhook couldn't be set up. If
  you change the external URL, reload the integration so the webhook follows.
- **The lock shows locked, but someone just opened it.** Locks that don't
  report their bolt position only show as unlocked while activated (usually a
  few seconds), which can be over before the activity arrives.
- **The lock shows locked, but the door is unlocked.** The lock missed being
  unlocked: two locked reports in a row in its activity show it. Linking the
  lock to its [door sensor](door-sensors.md) shows it as unlocked as soon as
  the door opens.
- **The lock shows unlocked, but it was just locked.** The lock is holding the
  report until it next checks in with its Bold Connect, up to about 15
  minutes, or it missed being turned. It shows locked once it reports it, or
  the next time it's turned.
- **An automation runs after a restart.** Activity entities come back with
  their last event: ignore changes from `unavailable` or `unknown`, as the
  [examples](automations.md#examples) do.
- **Home Assistant asks to re-authenticate.** Your Bold sign-in expired or was
  revoked. Follow the prompt and sign in with the same Bold account.

## Known limitations

- **Bold locks aren't motorised.** Unlocking lets someone turn the lock by
  hand for a few seconds, and **Lock** just ends that early. Nothing can turn
  the bolt for you.
- **Whether a door is locked** needs a Bold Elite or an upgraded Bold
  Classic, with locked status turned on in the Bold app. Other locks show as
  unlocked only while they're activated.
- **Locks occasionally miss being turned**, and keep showing their last
  position. [Linking a door sensor](door-sensors.md) catches a missed unlock
  as soon as the door opens.
- **Some updates arrive late.** A lock sometimes holds back a lock or unlock
  until it next checks in with its Bold Connect, up to about 15 minutes.
  Activity from outside Home Assistant usually arrives within seconds, or
  within about 30 seconds when Bold can't reach Home Assistant. A Bold
  Connect going offline is noticed after 30–40 minutes.
- **Locks without a Bold Connect** only report activity when a phone with the
  Bold app passes by.
- **Battery levels** are Bold's five levels, from Excellent to Critical, not
  percentages.

## Reporting a problem

Please include:

- **Diagnostics:** **Settings → Devices & services → Bold Smart Lock → ⋮ →
  Download diagnostics**. Personal details are removed.
- **Debug logs:** **⋮ → Enable debug logging**, reproduce the problem, then
  disable it to download the log.

## Removal

1. Go to **Settings → Devices & services → Bold Smart Lock**, open the **⋮**
   menu and choose **Delete**. This also removes the webhook the integration
   registered with Bold, and deletes the Bluetooth keys stored for your locks.
2. To remove the integration's files too, remove **Bold Smart Lock** in HACS and
   restart Home Assistant.
3. If you added your own Bold OAuth client, you can remove it under
   **Settings → Devices & services → ⋮ → Application credentials**.

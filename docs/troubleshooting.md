# Troubleshooting

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

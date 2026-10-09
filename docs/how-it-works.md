# How updates reach Home Assistant

## Pushed, within seconds

When Bold can reach your Home Assistant, through its external URL or Home
Assistant Cloud, the integration sets up a webhook with Bold. Bold then sends
activations, bolt changes, tamper alerts and daily status reports as they
happen.

- Each delivery is checked against a secret only Bold and Home Assistant know.
- The webhook is kept up to date across restarts, and removed with the
  integration.

## Polled, as a fallback

Without pushes, and as a safety net alongside them:

- **Activity** is checked every 30 seconds, or every 5 minutes while pushes are
  working. If a check finds something the webhook should have pushed, it goes
  back to every 30 seconds until pushes resume. Locks upload their events when
  a Bold Connect or phone next syncs with them, which can be later, so every
  10 minutes a check looks back an hour for anything that arrived late.
- **Devices** (battery, signal, firmware and Bold Connect status) are checked
  every 10 minutes.
- **Battery voltages** come from a status report each lock sends once a day,
  at a fixed time. They keep their last reading across restarts, and start
  from the past week's readings when you set up the integration.

Unlocking from Home Assistant updates the lock straight away.

## Bluetooth

To unlock over Bluetooth, Bold's cloud issues each lock a handshake, valid for
about a week, and signed commands. The integration fetches them every 12
hours and stores them, so locks in range can be unlocked for several days
without internet. Home Assistant keeps track of which locks it can hear as
they advertise.

## Where the keys are kept

The Bluetooth keys are stored in Home Assistant's `.storage` folder, along
with your Bold sign-in and the webhook's secret. Anyone who can read that
folder, or a backup of it, could unlock your locks over Bluetooth from within
range, until the keys expire after about a week. Diagnostics never include any
of them.

To report a security problem, see [SECURITY.md](../SECURITY.md).

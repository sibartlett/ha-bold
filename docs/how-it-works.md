# How data is updated

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

## Where the keys are kept

The Bluetooth keys are stored in Home Assistant's `.storage` folder, like your
Bold sign-in and the webhook's secret. Anyone who can read that folder (or a
backup of it) could unlock your locks over Bluetooth, from within Bluetooth
range, until the keys expire (about a week). Diagnostics never include any of
them.

To report a security problem, see [SECURITY.md](../SECURITY.md).

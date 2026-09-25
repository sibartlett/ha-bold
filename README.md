# Bold Smart Lock for Home Assistant

A custom integration for [Bold Smart Locks](https://boldsmartlock.com), using the
[Bold API](https://apidoc.boldsmartlock.com/).

## How Bold locks are represented

A Bold lock is not motorised. Unlocking it _activates_ the cylinder, so it can be
turned by hand for a few seconds. Each lock gets:

| Entity | What it does |
|---|---|
| `lock.<name>` | **Unlock** activates the lock through your Bold Connect. The lock shows as unlocked while it is activated, and locked otherwise. This is an assumed state: without bolt position reporting, Home Assistant can't know whether the door was actually turned. **Lock** ends an activation early; it can't throw the bolt. `changed_by` shows who last activated or deactivated it. |
| `event.<name>_activity` | Fires for activations (with the user and method: PIN, button, app…), failed activations such as a wrong PIN, deactivations, and tamper alerts. Only created for locks with the event log feature. |
| `sensor.<name>_battery_level` | Battery level as Bold reports it: Excellent, High, Medium, Low or Critical. |
| `binary_sensor.<name>_battery` | Low battery: on when the level is Low or Critical. |

Locks without a Bold Connect show as unavailable, because they can't be
activated remotely.

## Polling

Bold's webhooks are only available to business organizations, so this
integration polls:

- devices every 10 minutes
- the event log every 30 seconds, so activity shows up with up to ~30 seconds' delay

## Installation

1. Add this repository to HACS as a custom repository (type: Integration) and install it.
2. Restart Home Assistant.
3. Add the **Bold Smart Lock** integration and sign in with your Bold account.

Signing in needs one of:

- **Home Assistant Cloud:** if you're logged in to Nabu Casa, Home Assistant
  offers its own Bold client, so there's nothing to configure.
- **Your own Bold OAuth client:** Bold issues custom clients free of charge
  ([request one](https://sesamsolutions.gitlab.io/public-documentation/integration/oauth-authentication.html)),
  with `https://my.home-assistant.io/redirect/oauth` as the redirect URI. Add its
  client ID and secret under
  **Settings → Devices & services → ⋮ → Application credentials** first.

## Development

```sh
pip install -r requirements_test.txt
pytest
ruff check . && ruff format --check .
python script/translations.py  # after changing strings.json
```

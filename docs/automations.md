# Automations

## Use cases

- Unlock the door from a dashboard, a voice assistant or an automation, e.g.
  for a delivery or a guest.
- Get notified about failed PIN attempts or tamper alerts.
- Know who came home, and whether they used the app, a PIN or a key fob.
- Get warned when a lock's batteries run low or the Bold Connect goes offline,
  before remote unlocking stops working.

## Examples

After a restart, each activity entity comes back with its last event. To
react only to new activity, the examples below ignore changes from
`unavailable` or `unknown`, with `not_from`.

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

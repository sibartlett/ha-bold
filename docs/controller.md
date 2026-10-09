# Using a Bold Connect as a door, gate or garage opener

With **Controller** turned on in the Bold app, a Bold Connect switches its
relay when activated, to open whatever it's wired to: a door strike, a gate or
a garage door.

## Choosing a lock or a button

Bold doesn't say what the relay is wired to, so the Connect gets both a lock
and a button. Both are **disabled by default**: enable the one that fits, on
the Connect's device page.

| Entity | Use it for |
|---|---|
| `lock.<connect>` | A door strike, with the relay held for an activation time. **Unlock** activates the Connect, and it shows as unlocked while activated, as an assumed state. Depending on the Connect's firmware, Bold may refuse **Lock**, which ends an activation early. |
| `button.<connect>_activate` | A garage door or gate, or a relay set to pulse. **Press** activates the Connect once. |

Its activity entity, `event.<connect>_activity`, is enabled, and is the
reliable record of who opened it and how. Activations from elsewhere, such as
the Bold app or the Connect's own button, reach Home Assistant a few seconds
late, so with a short activation time, the lock may show as unlocked only
briefly, if at all.

## Voice assistants

Voice assistants treat locks and buttons differently. Google Assistant only
unlocks a lock with the secure devices PIN set in Home Assistant, but runs a
button like a scene, with no PIN. Neither is exposed to voice assistants
unless you choose to, so think twice before exposing the button.

## Garage doors

A garage door opener usually toggles, so the same press opens or closes the
door. If you have a sensor for whether the door is open, a
[template cover](https://www.home-assistant.io/integrations/template/#cover)
can press the button only when the door needs to move. For a Connect named
Garage:

```yaml
template:
  - cover:
      - name: Garage door
        device_class: garage
        state: "{{ is_state('binary_sensor.garage_door', 'on') }}"
        open_cover:
          - condition: state
            entity_id: binary_sensor.garage_door
            state: "off"
          - action: button.press
            target:
              entity_id: button.garage_activate
        close_cover:
          - condition: state
            entity_id: binary_sensor.garage_door
            state: "on"
          - action: button.press
            target:
              entity_id: button.garage_activate
```

## Turning Controller on or off

The lock and button appear within 10 minutes of turning **Controller** on,
and become unavailable when it's turned off.

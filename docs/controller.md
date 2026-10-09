# A Bold Connect with its Controller setting on

With **Controller** on in the Bold app, a Connect switches its relay when
activated, to open whatever it's wired to. Bold doesn't say what that is, so
the Connect gets two ways to activate it, both **disabled by default**: enable
the one that fits, under the Connect's device page.

| Entity | Use it for |
|---|---|
| `lock.<connect>` | A door strike, with the relay held for an activation time. **Unlock** activates the Connect, and it shows as unlocked while activated, as an assumed state. Bold may refuse **Lock**, to end an activation early, depending on the Connect's firmware. |
| `button.<connect>_activate` | A garage door or gate, or a relay set to pulse. **Press** activates the Connect once. |

Activations from elsewhere, such as the Bold app, a PIN or the Connect's own
button, reach Home Assistant a few seconds late: with a short activation time,
the lock only shows as unlocked briefly, if at all. The Connect's
`event.<connect>_activity` is enabled, and is the reliable record of who
opened it and how.

Voice assistants treat locks and buttons differently. Google Assistant only
unlocks a lock with the secure devices PIN set in Home Assistant, but runs a
button like a scene, without one.
Neither is exposed to voice assistants unless you choose to; think twice
before exposing the button.

A garage door opener usually toggles, so the same press opens or closes it.
With a sensor for whether the door is open, and a Connect named Garage, a
[template cover](https://www.home-assistant.io/integrations/template/#cover)
only presses the button when the door needs to move:

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

The lock and button appear within 10 minutes of turning **Controller** on,
and become unavailable when it's turned off.

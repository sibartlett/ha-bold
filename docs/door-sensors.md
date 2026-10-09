# Linking a lock to its door sensor

A lock with locked status on occasionally misses being turned, and keeps
showing its last position, such as locked while the door is actually open. If
the door has a contact sensor, linking the two catches this.

## Linking

1. Go to **Settings → Devices & services → Bold**.
2. Choose **Link a door sensor**.
3. Pick the lock, and its door sensor: a `binary_sensor` with the door or
   opening device class.

Each link is listed there as a **Linked door sensor**, such as
"🔒 Front Door → 🚪 Front Door", where you can change or delete it.

Only locks with locked status on can be linked. For other locks, locked and
unlocked mean whether they're activated, which the door doesn't change.

## How it works

A door can't open while it's locked. So if the door has opened since the lock
last reported it was locked, the lock shows as **unlocked**, until it reports
locked again, even if the door is still open.

- **Closing the door** doesn't make the lock show as locked, as a door can be
  closed without locking it.
- **Restarts** don't lose track: the lock remembers when the door last opened.
- **An unavailable sensor** is ignored. If the door was closed before it went
  unavailable and is open when it's back, that counts as an opening.
- **Changing the sensor's entity ID** keeps the link. Deleting the sensor
  leaves the lock as if it wasn't linked.
- **Turning locked status off** leaves the link in place, but it has no effect.

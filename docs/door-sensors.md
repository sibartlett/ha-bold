# Linking a lock to its door sensor

A lock with locked status on sometimes misses being turned, and keeps showing
its last position: locked while the door is open, for example. With a contact
sensor on the door, link the two: under **Settings → Devices & services →
Bold**, choose **Link a door sensor**, then the lock and its door sensor (a
`binary_sensor` with the door or opening device class). Only locks with locked
status on can be linked: for other locks, locked and unlocked mean whether
they're activated, which a door doesn't change.
Each link is listed there as a **Linked door sensor**, such as
"🔒 Front Door → 🚪 Front Door", to change or delete.

A door can't open with the bolt thrown, so once the door has opened since
the lock last reported it was locked, a linked lock shows as **unlocked**,
until it reports locked again, even with the door still open. The lock
remembers when the door last opened across restarts. A sensor that's
unavailable is ignored. Closing the door doesn't make the lock show as
locked, as the door can be closed without locking it. If locked status is
turned off, the link stays but has no effect.

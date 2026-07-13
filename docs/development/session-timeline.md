# Appliance Session Timeline

Appliance Detail exposes a shared bounded session payload for direct and NILM
appliances. Direct sessions are normalized from retained start/stop events;
NILM sessions come only from the selected assignment's bounded history.

Each session includes the stable appliance key, start/end, elapsed duration,
source type, confidence when estimated, validation or activity status, related
alert IDs, maintenance state, and estimated energy when available.

The panel renders time-of-day strips with these rules:

- solid blocks are directly measured sessions;
- dashed blocks are NILM estimates;
- dotted right edges mean the session is still running;
- gray blocks overlap maintenance; and
- a warning marker means the session has alert evidence.

Every strip is a keyboard-operable disclosure with start/end, duration, energy,
source, status, confidence, and an evidence link. This text detail is the
color-independent fallback for the visual strip. Payloads are capped at 40
sessions and do not duplicate source waveforms.

# Tesla CAN Bus Reverse Engineering Notes: Hazard Lights

## The Problem with DAS_bodyControls (0x3E9)
Initially, we attempted to turn on the hazard lights by spoofing the `DAS_bodyControls` (0x3E9) message, which is the message the Autopilot (DAS) module uses to request hazards. 
* **Signal:** `DAS_hazardLightRequest` (Byte 0, Bits 2-3)
* **Values:** `1 = ON`, `0 = OFF`, `2 = UNUSED`, `3 = SNA`

**Why it failed:** 
1. `0x3E9` uses a complex rolling counter and checksum logic. If you send the same frame multiple times, the Gateway rejects it as a replay attack.
2. Even with correct checksums and rolling counters, the physical DAS module is constantly broadcasting its own `0x3E9` frames (typically commanding `SNA` or `OFF`). Our injected frames were fighting the real hardware and getting overridden.

## The Solution: Spoofing the Physical Button (0x3C2)
Instead of pretending to be the Autopilot module, we discovered it is much more reliable to pretend a human pressed the physical hazard button on the overhead console.

* **Message:** `VCLEFT_switchStatus` (0x3C2)
* **Signal:** `VCLEFT_hazardButtonPressed` (Multiplexed `m0`, Byte 0, Bit 3)

### How to Spoof the Button
The `0x3C2` message is multiplexed using Bits 0-1 of Byte 0 as the index. When the index is `00` (`m0`), Bit 3 represents the physical hazard button.
Because it's a momentary physical push-button, **sending the "pressed" state acts as a TOGGLE.** 

To simulate a button press without corrupting the state of other windows/seats:
1. Sniff and cache the most recent `0x3C2` frame where `(data[0] & 0x03) == 0`.
2. Apply a bitwise OR to set the 3rd bit: `data[0] |= 0x08`.
3. Inject the modified frame **once**.
4. The hazards will toggle their state (OFF -> ON, or ON -> OFF).

### Tracking Actual Hazard State (0x3F5)
Because the button is just a toggle, blindly injecting the `0x3C2` spoof could turn the hazards OFF if they were already ON. To prevent this, we must track the true state of the hazard lights.

* **Message:** `VCFRONT_lighting` (0x3F5)
* **Signal:** `VCFRONT_hazardLightRequest` (Byte 0, Bits 4-7)

If `(data[0] >> 4) & 0x0F` is greater than `0`, the hazard lights are currently active (whether requested by the BUTTON, DAS, CRASH, or ALARM). We use this to only inject the `0x3C2` toggle if the current state does not match our desired state.

## Summary Methodology for Future Hacks
1. **Avoid spoofing Autopilot/ECU command frames** if possible, as they usually have checksums/counters and fight existing hardware.
2. **Look for physical switch/button states** (e.g., `VCLEFT_switchStatus`, `VCRIGHT_doorStatus`). Spoofing a human button press is often unauthenticated and immediately respected by the Gateway.
3. **Always track the actual state** via a status broadcast frame (like `VCFRONT_lighting`) so momentary button toggles don't get out of sync.

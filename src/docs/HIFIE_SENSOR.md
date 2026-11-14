# HIFIE | Froth Interface Detection

**Name:** HIFIE — *HIF Image-based Froth Interface Estimation*.  
**Displayed label:** **HIFIE | Froth Interface Detection**.  
**Stable internal sensor identifier:** `froth_interface` (type `virtual_froth_interface`).

The **HIF** prefix identifies the Helmholtz Institute Freiberg and also serves as a reference to Hilgert. The name refers to an image-based sensor that estimates the physical positions of the froth surface and pulp–froth interface from calibrated camera imagery. In this system, camera geometry, cell references and temporal image analysis support the position estimates.

The full name identifies the method, while the user-facing label describes its function. The short name **HIFIE** is used where horizontal space is limited (for example, the Run workflow progress indicator).

## Compatibility

Do **not** change `froth_interface` in APIs, database records, calibration states, file paths or event identifiers. The change is presentation-only: new sensor registrations, previously saved calibration snapshots, Vision snapshots, Run and Sensors display components now use the HIFIE name. Operator Skip/Recalibrate actions retain their existing API routes and validation behavior.

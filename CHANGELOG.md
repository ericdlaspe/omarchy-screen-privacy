# Changelog

## 0.1.3 - 2026-11-11

- Fixed automatic display checks overriding normal idle screen-off in versions 0.1.0–0.1.2.
- Separated privacy visibility from DPMS power. Visible screens follow desktop idle/input policy; explicit restore wakes once, and hidden-mode virtual capture remains available.
- Preserved idle state across privacy transitions and rearmed local input wake on restoration.
- Refused unsafe mirrored/unresolved targeted DPMS selectors; added regression tests for Hyprland's global fallback behavior.
- Added idle, recovery, and upgrade instructions. Lock and suspend settings are unchanged. This remains an experimental, single-display preview; a fresh client reconnect from idle and an overnight endurance test are not yet verified.

## 0.1.2 - 2026-11-11

- Included the CI runner fix in the released tag: Ubuntu 22.04 supports the Python 3.9/3.13 test matrix.
- Updated installation links, source archive, and Arch package checksums for the new preview.
- No change to display-control behavior or the experimental compatibility scope.

## 0.1.1 - 2026-11-11

- Published the initial unofficial public preview with a versioned GitHub release.
- Added an optional Arch package recipe that installs setup files without modifying any user's configuration.
- Neutralized and bounded dynamic tooltip text according to Omarchy plugin UI safety guidance.
- Added public installation instructions, CI, contribution guidance, and package-build checks.

## 0.1.0 - 2026-11-11

- Extracted the single-display virtual-output / physical-mirror implementation into a preview.
- Detected physical connector, dimensions, refresh rate, scale, and position.
- Added generic icon/tooltip, per-user staging, explicit activation, guarded physical test, and opt-in automatic mode.
- Added journal epoch checks, retained physical state on controller errors, backup manifests, resumable uninstall, and recovery documentation.
- Limited support to one ordinary unrotated SDR output on the Lua/Quickshell Omarchy stack.

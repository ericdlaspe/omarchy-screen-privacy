# Verification record

Date: 2026-11-11. Release: 0.1.3 experimental preview.

## Passed

- 96 Python unittest cases on macOS and an Omarchy Linux host. Some inherited fixture checks deliberately run in more than one lifecycle context.
- DP, HDMI, and eDP connector fixtures; 1080p, 1440p, ultrawide, and 4K modes; fractional/HiDPI scales and negative positions.
- Explicit refusal of extra/headless outputs, disabled setup display, rotation, VRR, HDR/10-bit, mirror conflicts, malformed identifiers, and invalid mode bounds.
- Physical-off prerequisite, generic icon/status, session-scoped overrides, topology-change pause, and targeted recovery.
- Two observed clients, last disconnect, replayed journal cursors, unknown initial epoch, service restart, unmatched events, and unavailable/malformed journal.
- Old test timers cannot reveal a later manual or automatic private session. Guard scheduling failure does not blank the display.
- Supported full dry run performs no writes or service/display changes. The actual existing custom deployment is refused rather than overwritten.
- Installer backups, rollback/retry, repeat-install refusal, missing-backup refusal, and preservation of later user edits.
- Resumable uninstall at all 13 per-file restoration boundaries and after daemon reload, compositor reload, bar reload, or Sunshine restart failure.
- Python compile and shell syntax checks.
- Arch package built successfully using ordinary runtime/build dependency checks, source SHA256 verification, and the full test suite. Package contents include only shared setup files and a setup wrapper; no activation hook. The package was not installed onto the reference system.
- Generated systemd user unit accepted by `systemd-analyze --user verify` on the Linux host.
- Generated Lua monitor and binding files compile under the running Hyprland Lua interpreter without executing those display changes.
- Dynamic tooltip text is bounded, strips control characters, and neutralizes rich-text markers.

## Idle-power regression checks in 0.1.3

- Regression fixtures cover repeated visible polls, idle before/during privacy, disconnect coinciding with idle, setup while idle, explicit one-time wake, session-scoped restore state, keyboard wake, mirror-selector global fallback, and hotplug refusal.
- On the existing reference deployment, the shared controller was checked with bounded, independently restored DPMS tests. Both outputs remained asleep across three watcher polls; three virtual-output screencopy frames were obtained while asleep. Keyboard wake, privacy from idle, virtual capture while hidden, idle-preserving restoration, subsequent keyboard wake, and explicit off/on recovery passed.
- Sunshine was not restarted during those reference tests. Existing lock and no-automatic-system-sleep settings were retained.
- This is not a fresh Moonlight connection test from an idle desktop or an overnight endurance test. Those remain to be verified by a person with access to the client and physical panel.
- Targeted DPMS is refused for mirrored/unresolved output selectors because the tested Hyprland version otherwise falls back to a global operation. Topology validation and dispatch are not atomic; concurrent hotplug remains unsupported.

## Not tested / not promised

- An end-to-end installation of this generalized archive onto a clean machine. The reference deployment was preserved during packaging.
- Any additional physical monitor, connector, GPU, driver, or laptop.
- Actual generalized-package startup/logout/reboot/suspend lifecycle, hotplug races, or multi-client hardware timing.
- Zero-frame local privacy, hardware electrical power-off, authoritative client counting, or security isolation.

The underlying virtual-display technique was physically verified in the single-display reference configuration. Automated tests do not establish hardware compatibility. Follow the guarded 20-second test and verify the real panel before enabling automatic control on another machine.

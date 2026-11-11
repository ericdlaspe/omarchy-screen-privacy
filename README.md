# Omarchy Screen Privacy

**Version 0.1.3 · experimental preview · unofficial**

Keep the physical screen dark while Sunshine streams a virtual Hyprland desktop. A crossed-out monitor button toggles the physical screen; right-click restores it. Automatic mode follows observed Sunshine connection/disconnection events.

This is connector-independent, **not universal display support**. It is a carefully scoped package derived from one working desktop installation, not a hardware-certified release.

## How it works

Sunshine captures a named virtual output, `HEADLESS-9`, using its `wlr` backend. The physical display normally mirrors that output. Turning privacy on disables only the physical output, leaving the virtual desktop available to Moonlight. The virtual desktop uses the physical screen's detected resolution and scale at 60 Hz. Windows remain open, but initial activation can move workspaces and change window placement.

The virtual output exists for the graphical session after activation, even if Sunshine stops. It is recreated before Sunshine starts after a new login. The installer does not alter authentication, firewall settings, idle lock, suspend settings, passwords, or pairing.

## Supported scope

- Linux Omarchy with **Lua-based Hyprland configuration and the Quickshell command-widget bar**.
- Exactly **one connected physical output**, including when disabled outputs are reported. Connector names such as `DP-2`, `HDMI-A-1`, or `eDP-1` are detected rather than hard-coded.
- Ordinary unrotated, 8-bit SDR, non-VRR display mode.
- Sunshine installed with a supported systemd **user** service and working `wlr` capture, already paired with Moonlight.
- Standard `~/.config` layout and the vendor Sunshine user service running `/usr/bin/sunshine` without custom config arguments or config-environment overrides.
- Python 3.9+, Hyprland, systemd user tools, Sunshine, and `omarchy-shell`. No Python packages or downloaded dependencies.
- The bar's normal Nerd Font must include the Material Design monitor-off glyph U+F0D90.

The original implementation was hardware-tested on Hyprland 0.56.2, Sunshine 2026.914.233613, Omarchy's Lua/Quickshell stack, and NVIDIA GTX 780M with nouveau at 2560×1440, scale 1.25. Physical blackout and remote desktop operation were verified on that configuration. **This generalized package has automated fixture tests, packaging checks, and read-only integration checks. A clean-machine end-to-end installation and additional hardware validation remain outstanding.**

Other DP/HDMI/eDP connectors and resolutions are covered by configuration tests, not physical hardware tests. Multi-monitor layouts, hotplugging extra displays, portrait/rotated screens, HDR, VRR, non-wlr capture, legacy Waybar/Hyprland configs, proprietary NVIDIA drivers, and laptop lid/suspend behavior are not validated. The installer rejects incompatible configurations it can identify. It cannot detect every external monitor-management script or driver limitation.

## Privacy and failure behavior

- This is a display convenience feature, **not a security boundary or a session lock**. Leave your normal lock policy enabled.
- A disabled output does not guarantee the panel is electrically powered off. Verify the actual screen in the room, not just a screenshot or software flag.
- Automatic mode reacts to Sunshine log events at roughly one-second intervals. A connection can be visible locally briefly before blackout. For sensitive use, manually turn the screen off **before** connecting.
- Journal events are best-effort observations, not an authoritative Sunshine session API. Logging changes or lost events can invalidate the count. Unknown state pauses automatic changes rather than falsely reporting zero clients.
- If the watcher stops or errors, it **retains the current physical display state**. It does not automatically expose a dark screen. A controller restarted during an existing Sunshine process needs `restart-auto` to establish a new known session epoch.
- A topology change pauses automatic control. A newly plugged screen may light up before detection. Do not attach/change displays while relying on privacy.
- Right-click, the recovery shortcut, `on`, activation, and uninstall deliberately reveal the local desktop. Anyone with local control can use those paths.
- This package does not control other screen-sharing apps, protect content on other computers, or prevent the physical lock screen from being accessible locally.

## Install from GitHub

Clone the public repository and select the published preview tag:

```sh
git clone https://github.com/ericdlaspe/omarchy-screen-privacy.git
cd omarchy-screen-privacy
git checkout v0.1.3
./install --dry-run
./install
```

Continue with **Activate and verify** below. The installer intentionally refuses unsupported systems rather than guessing.

Alternatively, download the versioned source archive and checksum from the [GitHub release](https://github.com/ericdlaspe/omarchy-screen-privacy/releases/tag/v0.1.3).

### Install from the source archive

Review the source before running it. Use your ordinary desktop account, **not sudo**, from the active Omarchy session.

```sh
tar -xzf omarchy-screen-privacy-0.1.3.tar.gz
cd omarchy-screen-privacy-0.1.3
./install --dry-run
./install
```

The dry run checks the configuration and prints affected paths without changing files, services, or displays. Installation backs up every file it changes, installs per-user files, adds the bar button/recovery binding, and stages a Sunshine pre-start hook. **It does not activate a virtual output, enable automatic mode, or restart Sunshine.** Configuration reloads can make the new button appear immediately.

The executable is `~/.local/bin/screen-privacy`. Use that full path if `~/.local/bin` is not in your PATH. Staged integration activates on the next Sunshine restart, including a later login; complete the activation steps below before relying on it.

Existing headless outputs, an existing Sunshine `output_name`, or an assigned recovery shortcut require manual integration. This installer intentionally does not migrate a customized existing deployment. Repeating installation exits without changing files.

## Activate and verify

Be at the physical display, with a keyboard or a separate working SSH connection available. **Activation briefly disconnects Moonlight** and changes the display layout. Apps are not intentionally closed, but save work first.

```sh
~/.local/bin/screen-privacy activate
```

Reconnect Moonlight. Confirm you see the desktop and can interact with it. While connected, run this in a terminal:

```sh
~/.local/bin/screen-privacy test
```

The test arms an independent systemd restore timer **before** disabling the physical output. It restores the screen after about 20 seconds. New manual choices or enabling/restarting automatic mode invalidate that test timer, so an old test cannot reveal a later private session. Verify both the real physical screen being dark and the remote desktop still working. If scheduling the timer fails, the screen is not disabled.

Only after that physical check succeeds:

```sh
~/.local/bin/screen-privacy enable-auto --verified
```

This deliberately disconnects and restarts Sunshine once to establish known session tracking. Reconnect and verify automatic blackout; disconnect and verify local restoration. Test after reboot/login and after relevant Omarchy, Hyprland, Sunshine, or driver updates before relying on the feature.

## Idle power and upgrading

Version 0.1.3 fixes a bug in 0.1.0–0.1.2 that could repeatedly wake the physical display after the desktop's idle timer blanked it. Update older installations before leaving automatic mode running overnight.

When the physical display is visible, normal Omarchy idle blanking and keyboard/mouse wake remain in charge. A manual “on” is a one-time wake, not a keep-awake setting. While privacy hides the physical output, the controller keeps the virtual capture output awake. If the display was idle before or during privacy mode, automatic restoration leaves it idle instead of keeping it lit. Lock and system-sleep settings are not changed.

If you deliberately show the physical screen during a stream, normal idle blanking applies to both outputs. Capture behavior while idle depends on the compositor and driver. Test connecting Moonlight from an already-idle desktop on your machine, as well as local keyboard wake afterward. Restoring a disabled output can briefly light it during the transition; keep the session locked when privacy matters.

There is no in-place upgrade command in this preview. Save your work, keep a keyboard or SSH fallback available, and uninstall the old per-user installation first:

```sh
~/.local/bin/screen-privacy uninstall --yes
```

This disconnects Sunshine and restores the original layout. If uninstall reports changed managed files, resolve those conflicts using the instructions below rather than overwriting them. Then install this release and repeat **Activate and verify**, including the idle/reconnect check. Updating the optional system package alone does not update an existing per-user installation.

## Controls

- **Crossed-out monitor button:** toggle the physical display. Highlighted means the output is reported disabled or asleep; it is not independent proof of physical privacy.
- **Right-click button:** restore the physical screen.
- **Super+Ctrl+Shift+F12:** restore the physical screen, including while locked.
- `screen-privacy off` / `on`: explicitly hide/reveal the physical screen.
- `screen-privacy auto`: clear a manual override. Automatic mode must already be running.
- `screen-privacy disable-auto`: disable automatic control and retain the current physical state.
- `screen-privacy restart-auto`: disconnect Sunshine, restart accounting, then restart Sunshine. Use after an automatic-control tracking error.
- `screen-privacy diagnose`: print version, output geometry/state, and service state. Review before sharing.

Manual choices last until the next observed connected/disconnected state transition. Two observed clients keep the screen dark until the last observed client disconnects. The watcher must see a stopped Sunshine process to establish a reliable initial zero; it does not assume an active process has no clients.

## Recovery

1. Press **Super+Ctrl+Shift+F12**, or right-click the button in Moonlight.
2. From the desktop terminal or SSH as the same desktop user:

   ```sh
   ~/.local/bin/screen-privacy on
   ```

3. If the Python controller is damaged, restore the configured connector directly. Replace `DP-2` with the connector recorded in `~/.config/omarchy-screen-privacy/config.json`:

   ```sh
   export $(systemctl --user show-environment | grep -E '^(HYPRLAND_INSTANCE_SIGNATURE|WAYLAND_DISPLAY|XDG_RUNTIME_DIR)=' | xargs)
   hyprctl eval 'hl.monitor({output="DP-2",mode="preferred",position="auto",scale=1,disabled=false,mirror=""})'
   hyprctl eval 'hl.dispatch(hl.dsp.dpms({action="enable"}))'
   ```

   This intentionally shows the local desktop and may rearrange it. Stop automatic control first if it is still running:

   ```sh
   systemctl --user stop omarchy-screen-privacy.service
   ```

Do not restart or kill the compositor as a first recovery step: that closes the graphical session. An independent SSH connection is the recommended fallback for a display-driver problem. The key binding and commands cannot recover a crashed GPU or compositor.

## Uninstall

Uninstall intentionally disconnects Sunshine, restores the physical layout, removes the virtual output, and restores backed-up configuration. If Sunshine was running, it restarts with the original configuration. Backups remain available.

```sh
~/.local/bin/screen-privacy uninstall --yes
```

Before changing anything, uninstall checks that installed files still match its manifest. If you edited a managed file afterward, it refuses to overwrite your changes and lists the conflicts. It also refuses if a required backup is missing. This is deliberate preservation, not a reason to delete your newer config. Interrupted uninstall is resumable: rerun the command, or from the extracted source directory run `python3 installer.py --uninstall --yes` if the installed helper has already been removed. Progress is saved after every restored file; later user edits are still protected.

### Manual conflict cleanup or interrupted installation

Backups and the manifest are under `${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-screen-privacy/`. The manifest records original paths, backup files, original permissions, and installed hashes. A prepared phase indicates interrupted staging; inspect each file against its backup before retrying. A completed rollback is archived as `last-rollback.json`, so installation can be retried normally. Keep the manifest until recovery is complete.

After saving your current edits:

1. Stop Sunshine and disable/stop `omarchy-screen-privacy.service`.
2. While the installed helper still exists, run `screen-privacy restore-layout` to restore the physical output and remove the virtual output. If that fails, use the direct recovery commands above and do not delete an output still being captured.
3. Remove only the blocks between `-- BEGIN OMARCHY SCREEN PRIVACY` and `-- END OMARCHY SCREEN PRIVACY` from `hypr/monitors.lua` and `hypr/bindings.lua`.
4. Remove only the `omarchy-screen-privacy` entry from `omarchy/shell.json`.
5. Restore the original `capture` and `output_name` settings from the Sunshine config backup, preserving unrelated newer edits.
6. Remove the package's Sunshine drop-in `omarchy-screen-privacy.conf`, user unit, `~/.local/bin/screen-privacy`, `~/.local/share/omarchy-screen-privacy/`, and `~/.config/omarchy-screen-privacy/` after preserving any changes you need.
7. Run `systemctl --user daemon-reload`, `hyprctl reload config-only`, and `omarchy-shell shell reloadConfig`. Restart the original Sunshine user service when ready.
8. Archive the manifest only after successful recovery. Do not remove unrelated service drop-ins or user configuration.

## Development and verification

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile privacy.py installer.py
```

Tests use temporary homes and fake Hyprland/systemd responses; they do not change the current desktop. They cover connector/mode detection, refusal cases, monitor command generation, safe blanking prerequisites, journal transitions, recovery flags, staged installation, rollback, and conflict-safe uninstall checks. They do not simulate actual GPU behavior or certify session transitions on untested hardware.

The package contains source, tests, a per-user installer/uninstaller, MIT license, and this documentation. It is not an official Omarchy or Sunshine project. Source and prerelease downloads are published on [GitHub](https://github.com/ericdlaspe/omarchy-screen-privacy). The project is not in the official Omarchy package repository or AUR. The optional Arch package below installs only shared setup files; per-user configuration is always explicit.

## Optional Arch package

The repository includes `pkgbuild/PKGBUILD`, following Omarchy's tag/release packaging guidance. Build it as your ordinary user from the checked-out release:

```sh
cd pkgbuild
makepkg -s
```

Review and install the resulting package through Omarchy's package tools or pacman. Do not run `makepkg` as root. Installing the Arch package **does not** change any user's display, configuration, or services. Then, from the active desktop account:

```sh
omarchy-screen-privacy-setup --dry-run
omarchy-screen-privacy-setup
```

Follow the same activation/test instructions above. To remove the feature, first run the per-user `screen-privacy uninstall --yes`; remove the Arch package afterward if desired. Removing the system package alone does not undo per-user configuration.

`bin/build-package` runs the build without installing it. No official Omarchy repository submission, automatic upstream merge, or AUR publication is implied.

## Language and integration

This preview uses Omarchy's existing command-widget interface rather than replacing its shell or installing a new QML plugin. Tooltips are currently English. Dynamic error text is bounded and neutralized before display, following Omarchy's plugin UI safety guidance. Translation catalogs and wider hardware support are future contributions, not current guarantees.

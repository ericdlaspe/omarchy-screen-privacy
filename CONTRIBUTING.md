# Contributing

This is an experimental, unofficial utility. Keep changes narrow and make failure/recovery behavior explicit.

Run `bin/test` before opening a pull request. Tests must use temporary files and mocked display/service responses, never alter the contributor's actual desktop. Add regression coverage for state transitions, retries, and recovery, not only the happy path.

For compatibility reports, include Omarchy/Hyprland/Sunshine versions, GPU and driver, connector type, resolution, scale, and which guarded checks succeeded. Review `screen-privacy diagnose` output before posting. Do not include credentials, pairing files, private screenshots, personal paths, IP addresses, or unrelated logs.

Do not claim a physical screen is dark based on compositor state or screenshots of the virtual output. Hardware validation must include observing the actual panel. Never describe this utility as a security boundary or guaranteed privacy protection.

Additional monitors, HDR/VRR, rotation, laptop suspend/lid behavior, new capture backends, and other drivers need explicit compatibility work. Keep unsupported configurations safely rejected until they have adequate tests and documented recovery.

The Arch package must only install shared files. User configuration and activation remain explicit, unprivileged operations. Never modify system-owned Omarchy files or silently enable services in a package install hook.

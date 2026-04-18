# GNOME Display Scale Resetter

A lightweight Python utility to watch and automatically reset GNOME display scaling when running under Wayland.

## Why

Resizing the window of a GNOME desktop environment running inside a VM on Wayland triggers a display reconfiguration. GNOME's Wayland compositor (Mutter) frequently defaults these new resolutions to a 100% scale regardless of the existing display scale setting.

This tool is irrelevant when running under X11, which doesn't support generic display scaling.

## How

This script serves as a watchdog for display configurations. It listens for `MonitorsChanged` signals via the GNOME Mutter DBus API. When a change is detected, such as a VM window resize or physical display hotplug, it checks the current scale and resets to the specified target scale upon a mismatch.

## Features

- Reacts instantly to VM window resizes and display hotplugs.
- Can specify:
  - Separate scaling factors for each display.
  - A default scaling factor for any display not listed by name.
- Automatically "snaps" the preferred scale to the closest value supported by Mutter for each display's current resolution.
  - Specifying a display in a mirror group will scale the entire group based on the supported scales of the first display in that group.
- Runs as a user systemd service that automatically starts on login.
  - Named displays do not need to be present when the service starts.

## Prerequisites

- GNOME Desktop Environment (Wayland)
- Python 3
- `python3-gi` (GObject Introspection)

## Installation

1.  **Install the script:**
    The provided service config will look for the script in `~/libexec`.
    ```bash
    mkdir -p ~/libexec
    cp display-scale-reset.py ~/libexec/
    ```

2.  **Configure the systemd service:**
    Open `display-scale-reset.service` for editing and replace `{{SCALE}}` with the preferred scale configuration.

    Examples:
    - Global scale: `--scale 1.25`
    - Per-display:  `--scale eDP-1:1.25 --scale HDMI-1:1.0`

3.  **Install and start the service:**
    ```bash
    mkdir -p ~/.config/systemd/user/
    cp display-scale-reset.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable display-scale-reset.service
    systemctl --user start display-scale-reset.service
    ```

## Usage

### Listing Displays
Identify connected displays:
```bash
~/libexec/display-scale-reset.py --list-displays
```

Example output:
```text
CONNECTOR       SCALE      PRIMARY
----------------------------------
eDP-1           1.25       Yes
HDMI-1          1.0        No
Virtual-1       1.25       No
```

### Running Once Manually
Force apply a scale configuration and exit:
```bash
~/libexec/display-scale-reset.py --force-once --scale 1.25
```

### Watching for Changes
Watch for scale changes on all displays and set all to 150%:
```bash
~/libexec/display-scale-reset.py --scale 1.5
```

### Targeting a Single Display
Operate on only one display:
```bash
~/libexec/display-scale-reset.py --scale HDMI-1:1.25
```

### Multiple Displays
Custom scale for two displays with a default of 150% for any other display.
```bash
~/libexec/display-scale-reset.py --scale 1.5 --scale eDP-1:1.25 --scale HDMI-1:1.0
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

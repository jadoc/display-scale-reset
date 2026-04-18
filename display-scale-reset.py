#!/usr/bin/python3
import gi
import argparse
import sys
import signal
import os

gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib

def get_display_config_proxy():
    """Sets up and returns a DBus proxy for the GNOME DisplayConfig service."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    return Gio.DBusProxy.new_sync(
        bus, 0, None,
        'org.gnome.Mutter.DisplayConfig',
        '/org/gnome/Mutter/DisplayConfig',
        'org.gnome.Mutter.DisplayConfig',
        None
    )

def to_variant(val):
    """
    Recursively wraps Python types into GLib.Variants.
    Supports: bool, int, float, str, and dict (as a{sv}).
    """
    if isinstance(val, GLib.Variant):
        return val
    
    if isinstance(val, dict):
        return GLib.Variant('a{sv}', {k: to_variant(v) for k, v in val.items()})
        
    type_map = {bool: 'b', int: 'i', float: 'd', str: 's'}
    return GLib.Variant(type_map.get(type(val), 's'), val)

def convert_state_to_config(state):
    """
    Transforms the 'read' data structure to the 'write' data structure.

    Parameters:
    state: a tuple matching the GetCurrentState signature:
           (serial:u, monitors:a((ssss)a(siiddada{sv})a{sv}), logical_monitors:a(iiduba(ssss)a{sv}), properties:a{sv})

    Returns:
    a tuple matching the ApplyMonitorsConfig signature:
    (serial:u, method:u, logical_monitors:a(iiduba(ssa{sv})), properties:a{sv})
    """
    serial, monitors, logical_monitors, properties = state
    
    # Map physical monitors to their currently active Mode ID
    active_modes = {}
    for spec, modes, _ in monitors:
        # monitor spec is (connector, vendor, product, serial)
        current_mode = next((m[0] for m in modes if m[6].get('is-current')), None)
        if current_mode:
            active_modes[spec] = current_mode

    # State Schema: (x, y, scale, rotation, primary, [spec1, spec2, ...], props)
    # Config Schema: (x, y, scale, rotation, primary, [(connector, mode_id, props), ...])
    new_lms = []
    for lm in logical_monitors:
        x, y, scale, rotation, primary, phys_specs, _ = lm
        
        # Transform Physical Monitors: (ssss) -> (ssa{sv})
        new_phys = [
            (s[0], active_modes[s], {}) 
            for s in phys_specs if s in active_modes
        ]
        
        if new_phys:
            new_lms.append((x, y, scale, rotation, primary, new_phys))

    return (serial, 1, new_lms, to_variant(properties))

def calculate_target_scales(display_state, default_scale, per_display_scales):
    """
    Calculates the best supported target scale for each logical monitor.
    Returns a list of target scales and a boolean indicating if any mismatch was detected.
    """
    _, monitors, logical_monitors, _ = display_state
    target_scales = []
    mismatch = False

    for lm in logical_monitors:
        current_scale = lm[2]
        phys_specs = lm[5]
        connectors = [s[0] for s in phys_specs]
        target = current_scale
        
        # Determine preferred scale and snap to closest supported
        preferred = next((per_display_scales[c] for c in connectors if c in per_display_scales), default_scale)
        
        if preferred is not None:
            # Snap to the closest supported scale for the first physical monitor in the group
            monitor_spec = phys_specs[0]
            target = preferred
            for spec, modes, _ in monitors:
                if spec == monitor_spec:
                    current_mode = next((m for m in modes if m[6].get('is-current')), None)
                    if current_mode:
                        supported_scales = current_mode[5]
                        target = min(supported_scales, key=lambda s: abs(s - preferred))
                        break

            if abs(current_scale - target) > 0.001:
                conn_str = ", ".join(connectors)
                print(f"Scale mismatch on display {conn_str}: current {current_scale}, preferred {preferred}, closest supported {target}")
                mismatch = True
            
        target_scales.append(target)

    return target_scales, mismatch

def apply_scale_reset(proxy, default_scale, per_display_scales, force=False):
    # Get current display state
    display_state = proxy.GetCurrentState()

    # Calculate target scales and detect mismatches
    target_scales, mismatch = calculate_target_scales(display_state, default_scale, per_display_scales)

    if not mismatch and not force:
        return
        
    if force:
        print("Forcing display configuration update...")
    else:
        print("Resetting display configuration...")
    
    # Use the display state data structure to constuct a monitor config update
    serial, method, lms, props = convert_state_to_config(display_state)
    
    # Mutate the configuration data
    for i, lm in enumerate(lms):
        # Update scale in-place: lms[i] is (x, y, scale, rotation, primary, phys_monitors)
        lms[i] = (lm[0], lm[1], float(target_scales[i]), lm[3], lm[4], lm[5])

    # Pack the components into the final signature: (uua(iiduba(ssa{sv}))a{sv})
    arg = GLib.Variant.new_tuple(
        GLib.Variant('u', serial),
        GLib.Variant('u', method),
        GLib.Variant('a(iiduba(ssa{sv}))', lms),
        props
    )
    
    try:
        proxy.call_sync('ApplyMonitorsConfig', arg, Gio.DBusCallFlags.NONE, -1, None)
        print("Display scale successfully set.")
    except Exception as e:
        print(f"Failed to set scale: {e}")

def on_displays_changed(proxy, sender_name, signal_name, parameters, default_scale, per_display_scales):
    if signal_name == 'MonitorsChanged':
        apply_scale_reset(proxy, default_scale, per_display_scales)

def list_displays():
    """Prints a clean list of connected displays and their connectors."""
    proxy = get_display_config_proxy()
    display_state = proxy.GetCurrentState()
    serial, monitors, logical_monitors, properties = display_state

    # Create a map for logical monitor information
    lm_map = {}
    for lm in logical_monitors:
        x, y, scale, rot, primary, phys_specs, _ = lm
        for spec in phys_specs:
            connector = spec[0]
            lm_map[connector] = (scale, primary)

    # Prepare data for printing
    display_data = []
    for monitor_info in monitors:
        spec, modes, props = monitor_info
        connector = spec[0]
        scale, primary = lm_map.get(connector, ("N/A", False))
        primary_str = "Yes" if primary else "No"
        display_data.append((connector, str(scale), primary_str))

    # Calculate column widths
    headers = ("CONNECTOR", "SCALE", "PRIMARY")
    widths = [len(h) for h in headers]
    for row in display_data:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(val))

    # Print headers
    fmt = f"{{:<{widths[0] + 2}}}{{:<{widths[1] + 2}}}{{:<{widths[2]}}}"
    print(fmt.format(*headers))
    print("-" * (sum(widths) + 4))

    # Print data
    for row in display_data:
        print(fmt.format(*row))

def force_once(default_scale, per_display_scales):
    """Force applies the scale configuration just once."""
    proxy = get_display_config_proxy()
    apply_scale_reset(proxy, default_scale, per_display_scales, force=True)

def start_monitoring(default_scale, per_display_scales):
    """Sets up signal handlers and runs the GLib main loop for continuous monitoring."""
    proxy = get_display_config_proxy()
    proxy.connect("g-signal", on_displays_changed, default_scale, per_display_scales)
    
    print(f"Watching for GNOME display scale changes...")
    if default_scale is not None:
        print(f"  Default scale: {default_scale}")
    for conn, scale in per_display_scales.items():
        print(f"  Display '{conn}': {scale}")
    
    # Initial check on startup
    apply_scale_reset(proxy, default_scale, per_display_scales)
    
    loop = GLib.MainLoop()

    def signal_handler(sig, frame):
        loop.quit()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        loop.run()
    except KeyboardInterrupt:
        pass

def main():
    if os.environ.get("XDG_SESSION_TYPE") != "wayland":
        print("Warning: XDG_SESSION_TYPE is not 'wayland'.")

    parser = argparse.ArgumentParser(description="GNOME Display Scale Resetter")
    parser.add_argument("--scale", action='append', help="Target scale. Can be a float (default for all) or 'display:float' override. Can be specified multiple times.")
    parser.add_argument("--list-displays", action="store_true", help="List all connected displays and exit")
    parser.add_argument("--force-once", action="store_true", help="Apply the scale configuration once and exit immediately")
    args = parser.parse_args()

    if args.list_displays:
        list_displays()
        return

    if not args.scale:
        parser.error("--scale is required unless using --list-displays")

    default_scale = None
    per_display_scales = {}
    
    for s in args.scale:
        if ':' in s:
            connector, val = s.split(':', 1)
            per_display_scales[connector] = float(val)
        else:
            default_scale = float(s)

    if args.force_once:
        force_once(default_scale, per_display_scales)
        return
        
    start_monitoring(default_scale, per_display_scales)

if __name__ == "__main__":
    main()

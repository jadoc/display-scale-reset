#!/usr/bin/python3
import gi
import argparse
import sys

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

def list_monitors():
    """Prints a clean list of connected monitors and their connectors."""
    proxy = get_display_config_proxy()
    state = proxy.GetCurrentState()
    serial, monitors, logical_monitors, properties = state

    # Create a map for logical monitor information
    lm_map = {}
    for lm in logical_monitors:
        x, y, scale, rot, primary, phys_specs, _ = lm
        for spec in phys_specs:
            connector = spec[0]
            lm_map[connector] = (scale, primary)

    # Prepare data for printing
    monitor_data = []
    for monitor_info in monitors:
        spec, modes, props = monitor_info
        connector = spec[0]
        scale, primary = lm_map.get(connector, ("N/A", False))
        primary_str = "Yes" if primary else "No"
        monitor_data.append((connector, str(scale), primary_str))

    # Calculate column widths
    headers = ("CONNECTOR", "SCALE", "PRIMARY")
    widths = [len(h) for h in headers]
    for row in monitor_data:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(val))

    # Print headers
    fmt = f"{{:<{widths[0] + 2}}}{{:<{widths[1] + 2}}}{{:<{widths[2]}}}"
    print(fmt.format(*headers))
    print("-" * (sum(widths) + 4))

    # Print data
    for row in monitor_data:
        print(fmt.format(*row))

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

def convert_state_to_apply_config(state):
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

    # Transform Logical Monitors: (Read Schema -> Write Schema)
    # Read Schema: (x, y, scale, rotation, primary, [spec1, spec2, ...], props)
    # Write Schema: (x, y, scale, rotation, primary, [(connector, mode_id, props), ...])
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

def apply_scale_reset(default_scale, per_monitor_scales):
    proxy = get_display_config_proxy()
    
    # Get current state
    state = proxy.GetCurrentState()
    logical_monitors = state[2]
    
    # Identify all mismatched monitors
    mismatches = []
    for lm in logical_monitors:
        current_scale = lm[2]
        phys_specs = lm[5]
        connectors = [s[0] for s in phys_specs]
        
        # Determine the target for this logical group
        target = per_monitor_scales.get(connectors[0], default_scale)
        
        if target is not None and abs(current_scale - target) > 0.001:
            mismatches.append((connectors, current_scale, target))
            
    if not mismatches:
        return
        
    for connectors, current, target in mismatches:
        conn_str = ", ".join(connectors)
        print(f"Scale mismatch on {conn_str}: current {current}, target {target}")
    
    print("Resetting display configuration...")
    
    # Transform current monitor state into a config update
    serial, method, lms, props = convert_state_to_apply_config(state)
    
    # Mutate the data
    updated_lms = []
    for x, y, scale, rot, pri, phys in lms:
        connector = phys[0][0]
        target = per_monitor_scales.get(connector, default_scale)
        
        # Use target if specified, otherwise keep current scale
        final_scale = float(target) if target is not None else scale
        updated_lms.append((x, y, final_scale, rot, pri, phys))
    
    # Pack the components into the final signature: (uua(iiduba(ssa{sv}))a{sv})
    arg = GLib.Variant.new_tuple(
        GLib.Variant('u', serial),
        GLib.Variant('u', method),
        GLib.Variant('a(iiduba(ssa{sv}))', updated_lms),
        props
    )
    
    try:
        proxy.call_sync('ApplyMonitorsConfig', arg, Gio.DBusCallFlags.NONE, -1, None)
        print("Display scale successfully reset.")
    except Exception as e:
        print(f"Failed to reset scale: {e}")

def on_monitors_changed(proxy, sender_name, signal_name, parameters, default_scale, per_monitor_scales):
    if signal_name == 'MonitorsChanged':
        apply_scale_reset(default_scale, per_monitor_scales)

def main():
    parser = argparse.ArgumentParser(description="GNOME Display Scale Resetter")
    parser.add_argument("--scale", action='append', help="Target scale. Can be a float (default for all) or 'monitor:float' override. Can be specified multiple times.")
    parser.add_argument("--list-monitors", action="store_true", help="List all connected monitors and exit")
    args = parser.parse_args()

    if args.list_monitors:
        list_monitors()
        return

    if not args.scale:
        parser.error("--scale is required unless using --list-monitors")

    default_scale = None
    per_monitor_scales = {}
    
    for s in args.scale:
        if ':' in s:
            connector, val = s.split(':', 1)
            per_monitor_scales[connector] = float(val)
        else:
            default_scale = float(s)

    proxy = get_display_config_proxy()
    
    proxy.connect("g-signal", on_monitors_changed, default_scale, per_monitor_scales)
    print(f"Watching for GNOME display scale changes...")
    if default_scale is not None:
        print(f"  Default scale: {default_scale}")
    for conn, scale in per_monitor_scales.items():
        print(f"  Monitor '{conn}': {scale}")
    
    # Initial check on startup
    apply_scale_reset(default_scale, per_monitor_scales)
    
    GLib.MainLoop().run()

if __name__ == "__main__":
    main()

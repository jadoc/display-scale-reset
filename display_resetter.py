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

def convert_state_to_write_data(state):
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

    # Return exactly what ApplyMonitorsConfig expects
    return (serial, 1, new_lms, to_variant(properties))

def apply_scale_reset(target_scale):
    proxy = get_display_config_proxy()
    
    # Get current state
    state = proxy.GetCurrentState()
    logical_monitors = state[2]
    
    # Check if reset is actually needed
    if all(abs(lm[2] - target_scale) < 0.001 for lm in logical_monitors):
        return
        
    print(f"Display scale mismatch detected. Resetting to {target_scale}...")
    
    # Transform current monitor state into a config update
    serial, method, lms, props = convert_state_to_write_data(state)
    
    # Update scale to the target
    updated_lms = [
        (x, y, float(target_scale), rot, pri, phys) 
        for x, y, scale, rot, pri, phys in lms
    ]
    
    # Pack the components into the final signature: (uua(iiduba(ssa{sv}))a{sv})
    arg = GLib.Variant.new_tuple(
        GLib.Variant('u', serial),
        GLib.Variant('u', method),
        GLib.Variant('a(iiduba(ssa{sv}))', updated_lms),
        props
    )
    
    try:
        proxy.call_sync('ApplyMonitorsConfig', arg, Gio.DBusCallFlags.NONE, -1, None)
        print(f"Successfully reset display scale to {target_scale}")
    except Exception as e:
        print(f"Failed to reset scale: {e}")

def on_monitors_changed(proxy, sender_name, signal_name, parameters, target_scale):
    if signal_name == 'MonitorsChanged':
        apply_scale_reset(target_scale)

def main():
    parser = argparse.ArgumentParser(description="GNOME Display Scale Resetter")
    parser.add_argument("--scale", type=float, required=True, help="Target display scale (e.g. 1.25)")
    args = parser.parse_args()

    proxy = get_display_config_proxy()
    
    proxy.connect("g-signal", on_monitors_changed, args.scale)
    print(f"Watching for GNOME display scale changes (target: {args.scale})...")
    
    # Initial check on startup
    apply_scale_reset(args.scale)
    
    GLib.MainLoop().run()

if __name__ == "__main__":
    main()

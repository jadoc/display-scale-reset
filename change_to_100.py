#!/usr/bin/python3
import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib

def change_scale(target_scale):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    proxy = Gio.DBusProxy.new_sync(
        bus, 0, None,
        'org.gnome.Mutter.DisplayConfig',
        '/org/gnome/Mutter/DisplayConfig',
        'org.gnome.Mutter.DisplayConfig',
        None
    )
    
    serial, monitors, logical_monitors, properties = proxy.GetCurrentState()
    
    monitor_to_mode = {}
    for monitor_info in monitors:
        spec, modes, monitor_props = monitor_info
        current_mode = None
        for mode in modes:
            mode_id, width, height, refresh, scale_f, supported_scales, mode_props = mode
            if mode_props.get('is-current'):
                current_mode = mode_id
                break
        if current_mode:
            monitor_to_mode[spec] = current_mode

    new_logical_monitors_data = []
    for lm in logical_monitors:
        x, y, scale, rotation, primary, phys_monitors, lm_props = lm
        new_phys_monitors = []
        for pm_spec in phys_monitors:
            connector = pm_spec[0]
            mode_id = monitor_to_mode.get(pm_spec)
            if mode_id:
                new_phys_monitors.append((connector, mode_id, {}))
            
        if new_phys_monitors:
            new_logical_monitors_data.append((x, y, float(target_scale), rotation, primary, new_phys_monitors))
    
    new_properties = {}
    for k, v in properties.items():
        if isinstance(v, GLib.Variant):
            new_properties[k] = v
        elif isinstance(v, bool):
            new_properties[k] = GLib.Variant('b', v)
        elif isinstance(v, int):
            new_properties[k] = GLib.Variant('i', v)
        elif isinstance(v, str):
            new_properties[k] = GLib.Variant('s', v)
        elif isinstance(v, float):
            new_properties[k] = GLib.Variant('d', v)
    
    arg = GLib.Variant.new_tuple(
        GLib.Variant('u', serial),
        GLib.Variant('u', 1),
        GLib.Variant('a(iiduba(ssa{sv}))', new_logical_monitors_data),
        GLib.Variant('a{sv}', new_properties)
    )
    
    proxy.call_sync('ApplyMonitorsConfig', arg, Gio.DBusCallFlags.NONE, -1, None)
    print(f"Triggered scale change to {target_scale}")

if __name__ == "__main__":
    try:
        change_scale(1.0)
    except Exception as e:
        print(f"Test failed: {e}")

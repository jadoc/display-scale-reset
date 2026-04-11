#!/usr/bin/python3
import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib

TARGET_SCALE = 1.25

def get_current_state():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    proxy = Gio.DBusProxy.new_sync(
        bus, 0, None,
        'org.gnome.Mutter.DisplayConfig',
        '/org/gnome/Mutter/DisplayConfig',
        'org.gnome.Mutter.DisplayConfig',
        None
    )
    return proxy.GetCurrentState()

def apply_scale(serial, monitors, logical_monitors, properties):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    proxy = Gio.DBusProxy.new_sync(
        bus, 0, None,
        'org.gnome.Mutter.DisplayConfig',
        '/org/gnome/Mutter/DisplayConfig',
        'org.gnome.Mutter.DisplayConfig',
        None
    )
    
    # Map each physical monitor's spec (ssss) to its current mode
    monitor_to_mode = {}
    for monitor_info in monitors:
        spec, modes, monitor_props = monitor_info
        connector = spec[0]
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
            
            # The Correct Format for ApplyMonitorsConfig monitor list is (ssa{sv})
            # where the strings are (connector, mode_id)
            if mode_id:
                new_phys_monitors.append((connector, mode_id, {}))
            
        if new_phys_monitors:
            new_logical_monitors_data.append((x, y, float(TARGET_SCALE), rotation, primary, new_phys_monitors))
        
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

    try:
        # serial (u), method (u), logical_monitors a(iiduba(ssa{sv})), properties a{sv}
        arg = GLib.Variant.new_tuple(
            GLib.Variant('u', serial),
            GLib.Variant('u', 1), # Persistent
            GLib.Variant('a(iiduba(ssa{sv}))', new_logical_monitors_data),
            GLib.Variant('a{sv}', new_properties)
        )
        
        proxy.call_sync('ApplyMonitorsConfig', arg, Gio.DBusCallFlags.NONE, -1, None)
        print(f"Successfully reset scale to {TARGET_SCALE}")
    except Exception as e:
        print(f"Error applying configuration: {e}")

def on_monitors_changed(proxy, sender_name, signal_name, parameters):
    if signal_name == 'MonitorsChanged':
        check_and_reset()

def check_and_reset():
    state = get_current_state()
    serial, monitors, logical_monitors, properties = state
    
    needs_reset = False
    for lm in logical_monitors:
        scale = lm[2]
        if abs(scale - TARGET_SCALE) > 0.001:
            print(f"Detected scale {scale}, resetting to {TARGET_SCALE}...")
            needs_reset = True
            break
            
    if needs_reset:
        apply_scale(serial, monitors, logical_monitors, properties)

def main():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    proxy = Gio.DBusProxy.new_sync(
        bus, 0, None,
        'org.gnome.Mutter.DisplayConfig',
        '/org/gnome/Mutter/DisplayConfig',
        'org.gnome.Mutter.DisplayConfig',
        None
    )
    
    proxy.connect("g-signal", on_monitors_changed)
    print("Watching for display scale changes.")
    check_and_reset()
    
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()

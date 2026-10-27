#!/usr/bin/env python3
"""
Elan Fingerprint Graphical Manager (GTK 4 / Libadwaita)
Native ASUS Vivobook 16 Biometric Management App
"""

import sys
import os
import threading
import time

# Ensure current and driver directory are on path
DIR = os.path.dirname(os.path.abspath(__file__))
if DIR not in sys.path:
    sys.path.insert(0, DIR)

# Add matching system virtual environment site-packages
py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
opt_site = f"/opt/elan_fingerprint/.venv/lib/{py_ver}/site-packages"
if os.path.isdir(opt_site) and opt_site not in sys.path:
    sys.path.insert(0, opt_site)

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio

from elan_auth import (
    load_templates_dict,
    save_templates,
    get_target_username,
    BiometricMatcher
)
from elan_sensor import ElanSensor


class FingerprintManagerWindow(Adw.PreferencesWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Fingerprint Settings")
        self.set_default_size(520, 560)
        self.user = get_target_username()
        self.finger_rows = []

        # Main Page
        self.page = Adw.PreferencesPage()
        self.add(self.page)

        # Enrolled fingers group
        self.fingers_group = Adw.PreferencesGroup(
            title="Registered Fingerprints",
            description=f"Biometric keys active for user: {self.user}"
        )
        self.page.add(self.fingers_group)

        # Actions group
        self.actions_group = Adw.PreferencesGroup(title="Manage Biometrics")
        self.page.add(self.actions_group)

        # Add Button Row
        self.add_row = Adw.ActionRow(
            title="Add New Fingerprint",
            subtitle="Enroll an additional thumb, index, or other finger"
        )
        self.add_btn = Gtk.Button(label="Enroll Finger", icon_name="list-add-symbolic")
        self.add_btn.add_css_class("suggested-action")
        self.add_btn.connect("clicked", self.on_add_clicked)
        self.add_row.add_suffix(self.add_btn)
        self.actions_group.add(self.add_row)

        # Test Button Row
        self.test_row = Adw.ActionRow(
            title="Test Sensor",
            subtitle="Touch sensor to test recognition score"
        )
        self.test_btn = Gtk.Button(label="Verify Match", icon_name="security-high-symbolic")
        self.test_btn.connect("clicked", self.on_test_clicked)
        self.test_row.add_suffix(self.test_btn)
        self.actions_group.add(self.test_row)

        self.refresh_fingers()

    def refresh_fingers(self):
        # Clear existing tracked rows
        for row in self.finger_rows:
            self.fingers_group.remove(row)
        self.finger_rows.clear()

        gallery, _ = load_templates_dict(self.user)
        if not gallery:
            no_row = Adw.ActionRow(
                title="No fingerprints registered",
                subtitle="Click 'Enroll Finger' below to register your first fingerprint."
            )
            self.fingers_group.add(no_row)
            self.finger_rows.append(no_row)
            return

        for finger_name, samples in gallery.items():
            row = Adw.ActionRow(
                title=finger_name,
                subtitle=f"{len(samples)} captured biometric samples"
            )
            icon = Gtk.Image.new_from_icon_name("fingerprint-symbolic")
            row.add_prefix(icon)

            del_btn = Gtk.Button(icon_name="user-trash-symbolic")
            del_btn.add_css_class("flat")
            del_btn.add_css_class("destructive-action")
            del_btn.set_tooltip_text(f"Delete '{finger_name}'")
            del_btn.connect("clicked", self.make_delete_handler(finger_name))
            row.add_suffix(del_btn)

            self.fingers_group.add(row)
            self.finger_rows.append(row)

    def make_delete_handler(self, finger_name):
        def handler(btn):
            gallery, _ = load_templates_dict(self.user)
            if finger_name in gallery:
                del gallery[finger_name]
                save_templates(self.user, gallery)
                self.show_toast(f"Deleted '{finger_name}'")
                self.refresh_fingers()
        return handler

    def show_toast(self, text):
        toast = Adw.Toast.new(text)
        toast.set_timeout(3)
        self.add_toast(toast)

    def on_add_clicked(self, btn):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Enroll New Fingerprint",
            body="Select which finger you want to enroll:"
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("enroll", "Start Capture")
        dialog.set_response_appearance("enroll", Adw.ResponseAppearance.SUGGESTED)

        # Finger name combo
        combo = Gtk.DropDown.new_from_strings([
            "Right Index Finger",
            "Right Thumb",
            "Right Middle Finger",
            "Left Index Finger",
            "Left Thumb",
            "Left Middle Finger",
            "Custom Finger"
        ])
        dialog.set_extra_child(combo)

        def on_response(dlg, response):
            if response == "enroll":
                finger_name = combo.get_selected_item().get_string()
                self.start_enroll_process(finger_name)

        dialog.connect("response", on_response)
        dialog.present()

    def start_enroll_process(self, finger_name):
        progress_dlg = Adw.MessageDialog(
            transient_for=self,
            heading=f"Enrolling {finger_name}",
            body="👉 [Sample 1/4]: Place your finger straight in the center..."
        )
        progress_dlg.add_response("cancel", "Cancel")
        progress_dlg.present()

        cancelled = [False]
        def on_cancel(dlg, resp):
            cancelled[0] = True
        progress_dlg.connect("response", on_cancel)

        def worker():
            sensor = ElanSensor()
            matcher = BiometricMatcher()
            try:
                sensor.open()
                sensor.init_sensor()
            except Exception as e:
                GLib.idle_add(progress_dlg.set_body, f"❌ Failed to open sensor: {e}")
                return

            samples = []
            hints = [
                "Place your finger straight in the center",
                "Place your finger slightly higher/forward",
                "Place your finger slightly to the left",
                "Place your finger firmly in the center"
            ]
            step = 1
            while step <= 4 and not cancelled[0]:
                GLib.idle_add(progress_dlg.set_body, f"👉 [Sample {step}/4]: {hints[step - 1]}...")
                img = sensor.wait_and_capture(timeout_sec=10)
                if cancelled[0]:
                    break
                if img is None:
                    continue
                pts, desc = matcher.extract_features(img)
                if desc is None or len(pts) < 15:
                    GLib.idle_add(progress_dlg.set_body, f"⚠️ Low contrast touch. Lift and try sample {step} again...")
                    time.sleep(1.2)
                    continue

                samples.append((pts, desc))
                GLib.idle_add(progress_dlg.set_body, f"✅ Sample {step} captured! Lift your finger...")
                step += 1
                time.sleep(1.2)

            sensor.close()

            if len(samples) == 4 and not cancelled[0]:
                gallery, _ = load_templates_dict(self.user)
                gallery[finger_name] = samples
                save_templates(self.user, gallery)
                GLib.idle_add(progress_dlg.close)
                GLib.idle_add(self.refresh_fingers)
                GLib.idle_add(self.show_toast, f"🎉 Enrolled '{finger_name}' successfully!")
            elif cancelled[0]:
                GLib.idle_add(progress_dlg.close)

        threading.Thread(target=worker, daemon=True).start()

    def on_test_clicked(self, btn):
        self.show_toast("👉 Touch the fingerprint sensor now...")
        self.test_btn.set_sensitive(False)

        def worker():
            gallery, _ = load_templates_dict(self.user)
            if not gallery:
                GLib.idle_add(self.show_toast, "❌ No enrolled fingerprints to test against.")
                GLib.idle_add(self.test_btn.set_sensitive, True)
                return

            all_templates = []
            for s_list in gallery.values():
                all_templates.extend(s_list)

            sensor = ElanSensor()
            matcher = BiometricMatcher(inlier_threshold=6)
            try:
                sensor.open()
                sensor.init_sensor()
                img = sensor.wait_and_capture(timeout_sec=6)
                sensor.close()
                if img is None:
                    GLib.idle_add(self.show_toast, "⏱️ Timed out (no finger touched).")
                else:
                    matched, score = matcher.verify(all_templates, img)
                    if matched:
                        GLib.idle_add(self.show_toast, f"✅ Match confirmed! Score: {score}")
                    else:
                        GLib.idle_add(self.show_toast, f"❌ Did not match (Score: {score}/6)")
            except Exception as e:
                GLib.idle_add(self.show_toast, f"❌ Error: {e}")
            finally:
                GLib.idle_add(self.test_btn.set_sensitive, True)

        threading.Thread(target=worker, daemon=True).start()


class FingerprintManagerApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.elan_fingerprint.manager",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )

    def do_activate(self):
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        win = self.props.active_window
        if not win:
            win = FingerprintManagerWindow(self)
        win.present()


def main():
    app = FingerprintManagerApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

"""Gettext Coverage — Translation coverage viewer for distribution packages."""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, Gio, GLib, Pango

import gettext
import locale
import os
import sys
import json
import datetime
import threading
import subprocess
import re
from gettext_coverage.accessibility import AccessibilityManager

LOCALE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "po")
if not os.path.isdir(LOCALE_DIR):
    LOCALE_DIR = "/usr/share/locale"
locale.bindtextdomain("gettext-coverage", LOCALE_DIR)
gettext.bindtextdomain("gettext-coverage", LOCALE_DIR)
gettext.textdomain("gettext-coverage")
_ = gettext.gettext

APP_ID = "se.danielnylander.gettext.coverage"
SETTINGS_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "gettext-coverage"
)
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")


def _load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    return {"welcome_shown": False}


def _save_settings(s):
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(s, f, indent=2)



def _scan_locale_packages():
    """Scan /usr/share/locale for translation stats."""
    results = []
    locale_dir = "/usr/share/locale"
    if not os.path.isdir(locale_dir):
        return results
    
    packages = set()
    for lang_dir in os.listdir(locale_dir):
        lc_path = os.path.join(locale_dir, lang_dir, "LC_MESSAGES")
        if os.path.isdir(lc_path):
            for mo_file in os.listdir(lc_path):
                if mo_file.endswith(".mo"):
                    packages.add(mo_file[:-3])
    
    for pkg in sorted(packages):
        langs_with = 0
        langs_total = 0
        for lang_dir in os.listdir(locale_dir):
            lc_path = os.path.join(locale_dir, lang_dir, "LC_MESSAGES")
            if os.path.isdir(lc_path):
                langs_total += 1
                if os.path.exists(os.path.join(lc_path, f"{pkg}.mo")):
                    langs_with += 1
        if langs_total > 0:
            results.append({
                "package": pkg,
                "languages": langs_with,
                "total_locales": langs_total,
                "coverage": round(langs_with / langs_total * 100, 1),
            })
    return results



class GettextCoverageWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=_("Gettext Coverage"), default_width=1000, default_height=700)
        self.settings = _load_settings()
        
        self._packages = []

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header
        headerbar = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(title=_("Gettext Coverage"), subtitle="")
        headerbar.set_title_widget(title_widget)
        self._title_widget = title_widget

        
        scan_btn = Gtk.Button(icon_name="system-search-symbolic", tooltip_text=_("Scan packages"))
        scan_btn.connect("clicked", self._on_scan)
        headerbar.pack_start(scan_btn)

        export_btn = Gtk.Button(icon_name="document-save-symbolic", tooltip_text=_("Export CSV"))
        export_btn.connect("clicked", self._on_export)
        headerbar.pack_end(export_btn)

        # Menu
        menu = Gio.Menu()
        menu.append(_("Settings"), "app.settings")
        menu.append(_("Copy Debug Info"), "app.copy-debug")
        menu.append(_("Keyboard Shortcuts"), "app.shortcuts")
        menu.append(_("About Gettext Coverage"), "app.about")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        headerbar.pack_end(menu_btn)

        main_box.append(headerbar)

        
        # Main list
        scroll = Gtk.ScrolledWindow(vexpand=True)
        
        # Column view
        self._list_store = Gio.ListStore.new(Gtk.StringObject)
        self._pkg_data = []
        
        self._listbox = Gtk.ListBox()
        self._listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._listbox.add_css_class("boxed-list")
        self._listbox.set_margin_start(12)
        self._listbox.set_margin_end(12)
        self._listbox.set_margin_top(8)
        self._listbox.set_margin_bottom(8)
        
        # Status page
        self._empty = Adw.StatusPage()
        self._empty.set_icon_name("preferences-desktop-locale-symbolic")
        self._empty.set_title(_("No data"))
        self._empty.set_description(_("Click the search icon to scan installed packages."))
        self._empty.set_vexpand(True)
        
        scroll.set_child(self._listbox)
        
        self._stack = Gtk.Stack()
        self._stack.add_named(self._empty, "empty")
        self._stack.add_named(scroll, "list")
        self._stack.set_vexpand(True)
        main_box.append(self._stack)

        # Status bar
        self._status = Gtk.Label(label=_("Ready"), xalign=0)
        self._status.set_margin_start(12)
        self._status.set_margin_end(12)
        self._status.set_margin_top(4)
        self._status.set_margin_bottom(4)
        self._status.add_css_class("dim-label")
        main_box.append(self._status)

        self.set_content(main_box)

        if not self.settings.get("welcome_shown"):
            GLib.idle_add(self._show_welcome)

    def _show_welcome(self):
        dialog = Adw.Dialog()
        dialog.set_title(_("Welcome"))
        dialog.set_content_width(420)
        dialog.set_content_height(480)

        page = Adw.StatusPage()
        page.set_icon_name("preferences-desktop-locale-symbolic")
        page.set_title(_("Welcome to Gettext Coverage"))
        page.set_description(_("View translation statistics for your distribution.\n\n"
            "✓ Scan installed packages for .po/.mo files\n"
            "✓ Show translation percentage per package\n"
            "✓ Sort by popularity and coverage\n"
            "✓ Identify untranslated high-priority packages\n"
            "✓ Export coverage report as CSV"))

        btn = Gtk.Button(label=_("Get Started"))
        btn.add_css_class("suggested-action")
        btn.add_css_class("pill")
        btn.set_halign(Gtk.Align.CENTER)
        btn.set_margin_top(12)
        btn.connect("clicked", self._on_welcome_close, dialog)
        page.set_child(btn)

        box = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        hb.set_show_title(False)
        box.add_top_bar(hb)
        box.set_content(page)
        dialog.set_child(box)
        dialog.present(self)

    def _on_welcome_close(self, btn, dialog):
        self.settings["welcome_shown"] = True
        _save_settings(self.settings)
        dialog.close()

    
    def _on_scan(self, btn):
        self._status.set_text(_("Scanning packages..."))
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        results = _scan_locale_packages()
        results.sort(key=lambda x: x["coverage"])
        GLib.idle_add(self._show_results, results)

    def _show_results(self, results):
        self._packages = results
        while True:
            row = self._listbox.get_row_at_index(0)
            if row is None:
                break
            self._listbox.remove(row)
        
        for pkg in results:
            row = Adw.ActionRow()
            row.set_title(pkg["package"])
            row.set_subtitle(_("%(langs)d / %(total)d languages (%(pct).1f%%)") % 
                           {"langs": pkg["languages"], "total": pkg["total_locales"], "pct": pkg["coverage"]})
            
            # Progress bar
            progress = Gtk.ProgressBar()
            progress.set_fraction(pkg["coverage"] / 100)
            progress.set_valign(Gtk.Align.CENTER)
            progress.set_size_request(120, -1)
            row.add_suffix(progress)
            
            self._listbox.append(row)
        
        self._stack.set_visible_child_name("list")
        self._status.set_text(_("Found %(count)d packages") % {"count": len(results)})

    def _on_export(self, btn):
        if not self._packages:
            return
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Export Coverage Report"))
        dialog.set_initial_name(f"coverage-{datetime.date.today().isoformat()}.csv")
        dialog.save(self, None, self._on_export_done)

    def _on_export_done(self, dialog, result):
        try:
            f = dialog.save_finish(result)
            path = f.get_path()
            import csv
            with open(path, "w", newline="") as csvf:
                w = csv.writer(csvf)
                w.writerow(["Package", "Languages", "Total Locales", "Coverage %"])
                for p in self._packages:
                    w.writerow([p["package"], p["languages"], p["total_locales"], p["coverage"]])
            self._status.set_text(_("Exported to %s") % path)
        except:
            pass


class GettextCoverageApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None

        for name, callback in [
            ("settings", self._on_settings),
            ("copy-debug", self._on_copy_debug),
            ("shortcuts", self._on_shortcuts),
            ("about", self._on_about),
            ("quit", self._on_quit),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        self.set_accels_for_action("app.quit", ["<Ctrl>q"])
        self.set_accels_for_action("app.shortcuts", ["<Ctrl>slash"])

    def do_activate(self):
        if not self.window:
            self.window = GettextCoverageWindow(self)
        self.window.present()

    def _on_settings(self, *_args):
        if not self.window:
            return
        dialog = Adw.PreferencesDialog()
        dialog.set_title(_("Settings"))
        page = Adw.PreferencesPage()
        
        group = Adw.PreferencesGroup(title=_("Scanning"))
        row = Adw.SwitchRow(title=_("Include system packages"))
        row.set_active(self.window.settings.get("include_system", True))
        group.add(row)
        page.add(group)
        dialog.add(page)
        dialog.present(self.window)

    def _on_copy_debug(self, *_args):
        if not self.window:
            return
        from . import __version__
        info = (
            f"Gettext Coverage {__version__}\n"
            f"Python {sys.version}\n"
            f"GTK {Gtk.MAJOR_VERSION}.{Gtk.MINOR_VERSION}\n"
            f"Adw {Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}\n"
            f"OS: {os.uname().sysname} {os.uname().release}\n"
        )
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(info)
        self.window._status.set_text(_("Debug info copied"))

    def _on_shortcuts(self, *_args):
        if self.window:
            dialog = Gtk.ShortcutsWindow(transient_for=self.window)
            section = Gtk.ShortcutsSection(visible=True)
            group = Gtk.ShortcutsGroup(title=_("General"), visible=True)
            for accel, title in [
                ("<Ctrl>q", _("Quit")),
                ("<Ctrl>slash", _("Keyboard shortcuts")),
            ]:
                group.append(Gtk.ShortcutsShortcut(accelerator=accel, title=title, visible=True))
            section.append(group)
            dialog.append(section)
            dialog.present()

    def _on_about(self, *_args):
        from . import __version__
        dialog = Adw.AboutDialog(
            application_name=_("Gettext Coverage"),
            application_icon="preferences-desktop-locale-symbolic",
            version=__version__,
            developer_name="Daniel Nylander",
            website="https://github.com/yeager/gettext-coverage",
            license_type=Gtk.License.GPL_3_0,
            issue_url="https://github.com/yeager/gettext-coverage/issues",
            comments=_("Shows translation coverage per package, identifies most-used untranslated packages."),
        )
        dialog.present(self.window)

    def _on_quit(self, *_args):
        self.quit()


def main():
    app = GettextCoverageApp()
    app.run(sys.argv)


# --- Session restore ---
import json as _json
import os as _os

def _save_session(window, app_name):
    config_dir = _os.path.join(_os.path.expanduser('~'), '.config', app_name)
    _os.makedirs(config_dir, exist_ok=True)
    state = {'width': window.get_width(), 'height': window.get_height(),
             'maximized': window.is_maximized()}
    try:
        with open(_os.path.join(config_dir, 'session.json'), 'w') as f:
            _json.dump(state, f)
    except OSError:
        pass

def _restore_session(window, app_name):
    path = _os.path.join(_os.path.expanduser('~'), '.config', app_name, 'session.json')
    try:
        with open(path) as f:
            state = _json.load(f)
        window.set_default_size(state.get('width', 800), state.get('height', 600))
        if state.get('maximized'):
            window.maximize()
    except (FileNotFoundError, _json.JSONDecodeError, OSError):
        pass


# --- Fullscreen toggle (F11) ---
def _setup_fullscreen(window, app):
    """Add F11 fullscreen toggle."""
    from gi.repository import Gio
    if not app.lookup_action('toggle-fullscreen'):
        action = Gio.SimpleAction.new('toggle-fullscreen', None)
        action.connect('activate', lambda a, p: (
            window.unfullscreen() if window.is_fullscreen() else window.fullscreen()
        ))
        app.add_action(action)
        app.set_accels_for_action('app.toggle-fullscreen', ['F11'])


# --- Plugin system ---
import importlib.util
import os as _pos

def _load_plugins(app_name):
    """Load plugins from ~/.config/<app>/plugins/."""
    plugin_dir = _pos.path.join(_pos.path.expanduser('~'), '.config', app_name, 'plugins')
    plugins = []
    if not _pos.path.isdir(plugin_dir):
        return plugins
    for fname in sorted(_pos.listdir(plugin_dir)):
        if fname.endswith('.py') and not fname.startswith('_'):
            path = _pos.path.join(plugin_dir, fname)
            try:
                spec = importlib.util.spec_from_file_location(fname[:-3], path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                plugins.append(mod)
            except Exception as e:
                print(f"Plugin {fname}: {e}")
    return plugins

"""App-scoped environment changes on test emulators and simulators."""

import json
import re
import subprocess

from contract import CommandError


ANDROID_PERMISSIONS = {
    "camera": "android.permission.CAMERA",
    "contacts": "android.permission.READ_CONTACTS",
    "microphone": "android.permission.RECORD_AUDIO",
    "notifications": "android.permission.POST_NOTIFICATIONS",
}
IOS_PERMISSIONS = {"contacts", "microphone", "photos"}


class MobileEnvironment:
    def __init__(self, driver, configuration):
        self.driver = driver
        self.android = driver.target == "android"
        permissions = ANDROID_PERMISSIONS if self.android else IOS_PERMISSIONS
        self.apps = json.loads(configuration)
        if type(self.apps) is not dict or any(
            app not in driver.app_ids or type(names) is not list or
            any(type(name) is not str or name not in permissions for name in names)
            for app, names in self.apps.items()
        ):
            raise ValueError("Configure mobile test environment entries for approved apps and supported permissions.")
        if self.apps and self.android and not driver.legacy.adb[-1].startswith("emulator-"):
            raise ValueError("App environment controls require an Android emulator.")
        self.previous_locales = {}
        self.previous_permissions = {}
        self.ios_locales = {}

    def capabilities(self):
        if not self.apps:
            return ()
        names = ("app.environment.capabilities", "app.locale.set")
        return (*names, "app.permission.set") if any(self.apps.values()) else names

    def android_locales(self, app):
        output = self.driver.shell("cmd", "locale", "get-app-locales", app).decode()
        match = re.fullmatch(rf"Locales for {re.escape(app)} for user \d+ are \[([A-Za-z0-9,-]*)\]",
                             output.strip())
        if not match:
            raise CommandError("environment_unavailable", "Android could not report the app locale state.", 422)
        return match[1]

    def write_android_locales(self, app, value):
        args = ("--locales", value) if value else ()
        self.driver.shell("cmd", "locale", "set-app-locales", app, *args)
        current = self.android_locales(app)
        if current.casefold() != value.casefold():
            raise CommandError("environment_not_applied", "Android did not apply the requested app locales.", 422)
        return current

    def locale(self, app, value):
        if self.android:
            if app not in self.previous_locales:
                self.previous_locales[app] = self.android_locales(app)
            return {"locale": self.write_android_locales(app, value), "source": "android:locale-manager"}
        self.driver._launch_simulator(app, value)
        self.ios_locales[app] = value
        return {"locale": value, "source": "simulator:launch-arguments"}

    def android_permission(self, app, permission):
        output = self.driver.shell("dumpsys", "package", app).decode()
        users = re.split(r"^ +User (\d+):", output, flags=re.M)
        active = dict(zip(users[1::2], users[2::2])).get("0", "")
        entry = re.search(rf"^ +{re.escape(permission)}: granted=(true|false)\b", active, flags=re.M)
        if not entry:
            raise CommandError("environment_unavailable", "Android did not list this app's runtime permission.", 422)
        return entry[1] == "true"

    def permission(self, app, name, state):
        if name not in self.apps[app]:
            raise CommandError("target_not_found", "This runtime permission was not enabled for the app.", 404)
        if self.android:
            if state == "reset":
                raise CommandError("unsupported_state", "Use granted or denied for Android runtime permissions.", 422)
            permission = ANDROID_PERMISSIONS[name]
            key = (app, permission)
            if key not in self.previous_permissions:
                self.previous_permissions[key] = self.android_permission(app, permission)
            self.driver.shell("pm", "grant" if state == "granted" else "revoke", "--user", "0", app, permission)
            if self.android_permission(app, permission) != (state == "granted"):
                raise CommandError("environment_not_applied", "Android did not apply the requested permission state.", 422)
        else:
            self.driver.simctl("privacy", {"granted": "grant", "denied": "revoke", "reset": "reset"}[state], name, app)
            self.previous_permissions[(app, name)] = None
        return {"permission": name, "state": state}

    def execute(self, command, params):
        if command == "app.environment.capabilities":
            return {"apps": self.apps, "permission_states": ["granted", "denied"] if self.android else
                    ["granted", "denied", "reset"]}
        app = params["id"]
        if app not in self.apps:
            raise CommandError("target_not_found", "This app was not enabled for environment changes.", 404)
        if command == "app.locale.set":
            return {"id": app, **self.locale(app, params["locale"])}
        return {"id": app, **self.permission(app, params["permission"], params["state"])}

    def close(self):
        for app, value in self.previous_locales.items():
            try:
                self.write_android_locales(app, value)
            except (ValueError, OSError, RuntimeError, subprocess.SubprocessError):
                print("An Android app locale could not be restored", flush=True)
        for (app, permission), granted in self.previous_permissions.items():
            try:
                if self.android:
                    self.driver.shell("pm", "grant" if granted else "revoke", "--user", "0", app, permission, timeout=4)
                else:
                    self.driver.simctl("privacy", "reset", permission, app, timeout=4)
            except (ValueError, OSError, RuntimeError, subprocess.SubprocessError):
                print("An app permission could not be restored", flush=True)

# Changelog

## 0.7.4

- Open the actual standalone HTML page instead of a Python static server's directory listing. Preserve explicit routes and uncertain server configurations.
- Remember the HTML file selected through File… across saving, editing and reopening, including folders containing multiple pages.
- Provide private, persistent window.storage get/set compatibility inside Hub for local Python static sites. Keep each project's browser data separate and restore saved state after restarting Hub without changing project source files.
- Use the same resolved page for embedded navigation, readiness checks and Open in browser, without overwriting the saved URL or unnecessarily reloading an unchanged page.
- Resolve Python and other bare tools against a project's configured PATH. Preserve selected interpreters, legacy full Python commands and relative virtual environments; support Windows Python aliases and saved/generated command quoting.
- Report actual executable startup failures instead of leaving projects stuck at Starting.
- Add browser-suppression arguments only when the current script or actual framework server CLI supports them, including older registrations. Do not take options from unrelated parser objects or lexical scopes.
- Discover silent servers through Start, page Start and autostart. Preserve URLs and UTF-8 across stdout pipe boundaries instead of saving partial addresses.
- Retire superseded readiness checks during Edit, Stop and Restart so late callbacks cannot navigate an old endpoint or override a replacement process.

## 0.7.3

- Preserve live dashboard pages and uploaded-image state when selecting an existing project in the sidebar or adding a registration; adding a project no longer steals the active tab.
- Keep the sidebar, toolbar actions and project terminal aligned with the active tab, including project-owned child tabs.
- Attribute close/stop messages to the clicked project's registered identity, and keep popup title updates attached to the correct widget after tabs move.
- Show local date/time on log lines and add Clear log for the displayed pane without stopping projects or clearing other panes.
- Show Stopping while a requested shutdown is still in progress instead of a misleading Project is running card; retain existing termination grace and identity-safe cleanup.

## 0.7.2

- Drag projects up or down in the sidebar and retain their order across restarts, renames, and export/import. New projects appear at the bottom.
- Update the Mac UI runtime to fix an accessibility-triggered crash when sidebar rows change, retaining macOS 12 support and the existing Windows/Linux runtimes.
- Build and verify macOS installers locally; GitHub Actions only stages the verified prebuilt DMG and builds/tests Windows and Ubuntu installers.

## 0.7.1

- Add the first Linux installer, targeting Ubuntu 24.04 LTS on x86-64.
- Keep front-page macOS, Windows and Linux downloads pointed at the latest release using stable asset names.
- Correct false project-error messages during intentional Stop/Restart while retaining genuine failure reporting.
- Update the Windows Qt stack for compatibility with newer Windows hosts, retaining renderer sandboxing and the existing macOS dependency/support floor.
- Include the previously merged audit-remediation and regression work by Tahir Masood (@tahirmasood2), with its original commit history and README credit preserved.

## Earlier releases

See [GitHub Releases](https://github.com/different2/local-project-hub/releases) for earlier version notes.

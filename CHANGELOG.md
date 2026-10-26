# Changelog

## 0.7.2

- Drag projects up or down in the sidebar and retain their order across restarts, renames, and export/import. New projects appear at the bottom.
- Build and verify macOS installers locally; GitHub Actions only stages the verified prebuilt DMG and builds/tests Windows and Ubuntu installers.

## 0.7.1

- Add the first Linux installer, targeting Ubuntu 24.04 LTS on x86-64.
- Keep front-page macOS, Windows and Linux downloads pointed at the latest release using stable asset names.
- Correct false project-error messages during intentional Stop/Restart while retaining genuine failure reporting.
- Update the Windows Qt stack for compatibility with newer Windows hosts, retaining renderer sandboxing and the existing macOS dependency/support floor.
- Include the previously merged audit-remediation and regression work by Tahir Masood (@tahirmasood2), with its original commit history and README credit preserved.

## Earlier releases

See [GitHub Releases](https://github.com/different2/local-project-hub/releases) for earlier version notes.

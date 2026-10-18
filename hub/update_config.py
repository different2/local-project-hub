"""Update endpoint configuration.

These point the in-app updater and the "Report a problem" dialog at this
project's own GitHub repo. They are safe to publish: they are public URLs,
not credentials.

Forks should change them to their own repo (or leave them pointing here to
track upstream releases).
"""

# The GitHub Releases "latest" endpoint this build checks for updates.
# Empty disables the updater; Check for Updates then explains that updates
# are not configured rather than failing silently.
RELEASE_API_URL = (
    "https://api.github.com/repos/different2/local-project-hub/releases/latest"
)

# Where "Report a problem" opens a prefilled issue. Empty disables the
# browser path; saving a report file always works.
ISSUES_URL = "https://github.com/different2/local-project-hub/issues/new"

# Reserved for a future background check (nothing reads this yet): when
# implemented, the app will check for updates on start and only *notify*;
# installation stays user-initiated (release spec §5).
BACKGROUND_CHECK = True

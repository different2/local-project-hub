"""Update endpoint configuration.

Point RELEASE_API_URL at the GitHub Releases "latest" endpoint of the repo
that publishes Local Project Hub. Leave it empty to disable the updater
entirely (the Check for Updates menu item then explains that updates are not
configured, rather than failing silently).

Example:
    RELEASE_API_URL = "https://api.github.com/repos/OWNER/local-project-hub/releases/latest"
"""

# Set this to your fork's releases endpoint before publishing.
RELEASE_API_URL = ""

# Where "Report a problem" opens a prefilled issue. Empty disables the
# browser path; saving a report file always works.
ISSUES_URL = ""

# Optional: when true, the app checks for updates in the background on start
# and only *notifies*; installation stays user-initiated (release spec §5).
BACKGROUND_CHECK = True

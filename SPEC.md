WHAT
====
Full spec text extracted from the user's Local-Project-Hub.rtf, kept as the
requirements reference for this implementation.

DELIVERED IN THIS BUILD (Initial Scope, all items):
  1. Register a Python project manually                (project_dialog.py)
  2. Configure startup command + dashboard URL          (project_dialog.py)
  3. Launch it through the hub                          (process_manager.py)
  4. Display its dashboard in an embedded browser       (QtWebEngine in window.py)
  5. Switch between >= 2 registered projects            (sidebar list)
  6. Restart a backend and reconnect to its dashboard   (restart button)
  7. Inspect startup errors and captured logs           (log drawer, stdout+stderr)
  8. Preserve configs across app restarts               (registry.json via store.py)

IMPLEMENTATION CHOICES (spec left these open):
  - Desktop shell: PySide6 (QtWebEngine) instead of Tauri, per user's choice.
    The doc said "language and process-management boundary should be chosen
    after reviewing the desktop shell's capabilities" — with Qt we get the
    process manager natively via QProcess, so it lives in Python.
  - Registry: JSON at ~/Library/Application Support/LocalProjectHub/registry.json
    (doc allowed "a local configuration file or SQLite").
  - Readiness: TCP connect poll + HTTP GET poll against the dashboard URL,
    so a server that binds late (e.g. the hub's own obs project) still works.

KNOWN LIMITS OF v0.1 (deferred, not hidden):
  - No icon picker (icons are emoji/initial only).
  - No auto-discovery of frameworks — startup is user-configured (per spec).
  - Logs are per-process-session, not persisted across hub restarts.
  - Env vars are a simple KEY=VALUE text field, not a vault.
  - Windows/Linux untested; macOS only.

FULL SOURCE SPEC (verbatim from the RTF) FOLLOWS
================================================
Project Description: Local Project Hub
Overview
Local Project Hub is a macOS desktop application that acts as a personal browser and launcher for locally hosted applications, particularly Python projects with web-based graphical interfaces.
Instead of manually opening a terminal, running a Python startup command, finding the local IP address and port, and navigating to the dashboard in Firefox, users can register their projects once and access them through a single desktop application.
The goal is to make independently developed projects feel like applications that can be launched, switched between, and managed from one central location, without requiring each project to be packaged into its own desktop application.
Core Concept
The application consists of a project library, a process manager, and an embedded browser interface.
Users register existing projects by selecting their project folders and configuring the information needed to run them. Once registered, projects appear in a list or dropdown menu. Selecting a project starts its backend if necessary and opens its web interface inside the application's main window.
Projects remain in their original directories and retain their existing development workflows. The hub manages how projects are launched and accessed rather than taking ownership of their source code.
Core Features
1. Project Library
Register existing projects by selecting their folders.
Assign each project a display name and optional description or icon.
Configure the working directory, Python interpreter or virtual environment, startup command, environment variables, and dashboard URL.
Store project configurations persistently between application launches.
Support different Python frameworks and project structures without requiring every project to follow one specific template.
2. Project Lifecycle Management
Start a project's backend automatically when its dashboard is opened.
Wait for the server to become ready before displaying its interface.
Track whether each project's process is running, stopped, starting, or experiencing an error.
Stop and restart projects when requested.
Capture standard output and standard error for troubleshooting.
Handle failed startup commands, unavailable ports, and unexpected process termination gracefully.
3. Embedded Browser Workspace
Display project dashboards inside the desktop application's main window.
Provide a dropdown menu, sidebar, or tabs for switching between registered projects.
Reuse each project's existing web interface rather than requiring its UI to be rewritten.
Remember the selected project between application launches.
Handle loading states, unavailable servers, navigation, and dashboard reconnection after backend restarts.
Provide an option to open the current dashboard in an external browser.
4. Diagnostics
Display basic project status and server readiness in the main interface.
Provide an optional panel for application logs and startup errors.
Keep diagnostics unobtrusive during normal use.
Allow logs to be inspected without requiring a separate terminal window.
5. Development-Friendly Behavior
Keep project source files editable in their original directories.
Allow projects to be restarted or reloaded after source changes.
Support development servers that offer automatic reload.
Avoid freezing, bundling, or rebuilding individual Python projects simply to make them accessible through the hub.
Keep the hub's own code and release lifecycle separate from the code of the projects it manages.
Proposed Architecture
The application should have three primary components:
Desktop shell: Provides the macOS application window, menus, navigation, and embedded browser. Tauri with React and TypeScript is a candidate implementation.
Project manager: Responsible for configuration, process creation and termination, readiness checks, environment setup, and log collection. The implementation language and process-management boundary should be chosen after reviewing the desktop shell's capabilities.
Project registry: Stores project metadata and runtime settings separately from project source files. A local configuration file or SQLite database would be sufficient initially.
The architecture should separate project management from individual dashboard webviews so that a failed dashboard or Python process does not crash the entire application.
Initial Scope
The first version should prioritize a reliable local development workflow:
Register a Python project manually.
Configure its startup command and dashboard URL.
Launch it through the hub.
Display its dashboard in an embedded browser.
Switch between at least two registered projects.
Restart a backend and reconnect to its dashboard.
Inspect startup errors and captured logs.
Preserve project configurations across application restarts.
Automatic source-code updating, automatic discovery of every possible Python framework, remote machine management, container orchestration, and a general-purpose plugin system are outside the initial scope.
Design Principles
Local-first: Projects and their data remain on the user's machine.
Non-invasive: Existing projects should not need substantial modifications to work with the hub.
Framework-agnostic: Project startup behavior should be configurable rather than hardcoded for a single framework.
Separation of concerns: The hub, project source code, running processes, and dashboard interfaces should remain independent.
Recoverability: A failed project should not prevent other projects from being launched or accessed.
Incremental development: The architecture should support adding more capabilities without requiring a complete redesign.
Long-Term Direction
The long-term goal is a personal application workspace where locally developed tools can be registered once and then launched, accessed, and managed as easily as opening a bookmark in a browser.
The hub should make the operational side of development nearly invisible while preserving the flexibility of ordinary Python projects.

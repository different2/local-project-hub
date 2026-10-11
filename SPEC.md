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
Project Specification: Local Project Hub — Cross-Platform Desktop Application
1. Project Goal
Transform the existing Local Project Hub into a polished, distributable desktop application for macOS and Windows, preserving as much of the existing implementation as possible.
Local Project Hub is a desktop control center for managing locally hosted Python projects. Users can register project folders, configure how each project starts, launch and stop processes, and access project dashboards from a shared application window.
The finished application should feel like a normal desktop product rather than a Python script. Users should not need to install Python manually, open a terminal, or execute commands to install or update the Hub.
Primary objectives:
Preserve existing functionality and avoid unnecessary rewrites.
Support macOS and Windows with platform-appropriate application packages.
Provide a proper application icon, menus, version information, and installer.
Support user-initiated application updates from within the application.
Protect registered projects, configuration, logs, and other user data during installation and updates.
Make development and future releases straightforward.
2. Begin by Auditing the Existing Project
Before changing the architecture, inspect the entire existing codebase and identify:
The current GUI framework and application entry point.
How the application starts, monitors, and stops project processes.
How project registrations, settings, and application state are stored.
How Python interpreters, virtual environments, dependencies, ports, and dashboard URLs are configured.
Any macOS-specific paths, commands, APIs, or assumptions.
Existing error handling, logging, and tests.
Which components can be reused without modification.
Produce a short architecture assessment listing what can be retained, what needs adaptation for Windows, and what genuinely needs replacement.
Do not rewrite the application from scratch just to make it distributable. Prefer incremental changes and preserve the existing GUI framework if it is suitable for a cross-platform release. Recommend a framework migration only when there is a concrete technical reason.
3. Cross-Platform Compatibility
The application must support macOS and Windows.
Implement platform-specific behavior behind small, clearly defined interfaces where practical. Examples include:
Application data and configuration directories.
File paths and filesystem permissions.
Starting, monitoring, terminating, and restarting subprocesses.
Discovering or selecting Python interpreters.
Opening dashboard URLs in the user's browser when needed.
Launch-at-login registration and removal.
Installer, application icon, and update mechanisms.
Use cross-platform Python libraries and APIs wherever possible. Avoid shell commands and hard-coded paths that work only on macOS.
Do not assume that a Python project registered in the Hub is itself cross-platform. The Hub should clearly report when a project's interpreter, dependencies, startup command, or other requirements are unavailable on the current operating system.
Keep platform-specific code isolated so that supporting additional platforms later does not require redesigning the core application.
4. Desktop Application Experience
The Hub must run in its own desktop application window.
Provide:
A proper application name, icon, and version number.
Native or framework-appropriate application menus.
An About dialog containing the installed version.
Clear startup, shutdown, and error states.
A settings area for application preferences.
A menu item such as Help → Check for Updates or About → Check for Updates, following platform conventions.
Clear feedback when an update is available, downloading, installing, or failing.
Preserve the existing project-management interface and workflows wherever possible. Do not redesign the entire interface unless necessary.
5. In-App Updates — A Core Requirement
Users must be able to update Local Project Hub without manually downloading a new release, opening a terminal, or running installation commands.
Implement a reliable update mechanism appropriate for the chosen desktop framework and packaging strategy.
Required user experience
The user opens the application's menu and selects Check for Updates.
The application checks a trusted release endpoint for a newer compatible version.
If no update exists, it reports that the application is up to date.
If an update exists, it displays the new version and a concise summary of the release notes.
The user selects Download and Install.
The application downloads the appropriate update for the user's operating system and CPU architecture, verifies its integrity and authenticity, and prepares the installation.
If the application must restart, it asks the user to restart now or finish later when safe.
The application restarts into the new version and confirms the result.
The update process must not require administrator privileges unless the chosen installation location or a specific operation genuinely requires them.
Update implementation requirements
Use a maintained update mechanism compatible with the selected application framework.
Prefer a secure, established update system over a custom implementation that executes arbitrary downloaded scripts.
Publish versioned releases and platform-specific update artifacts through a reliable release channel, such as GitHub Releases or an equivalent hosting service.
Verify downloaded artifacts using the updater's supported signature verification or cryptographic integrity mechanisms. Do not rely on HTTPS alone as proof that an artifact is the authentic publisher release.
Support separate macOS and Windows artifacts, including the appropriate CPU architectures.
Handle network failures, interrupted downloads, invalid signatures, incompatible releases, and insufficient disk space gracefully.
Never replace a running executable in an unsafe manner. Use the framework's supported update-and-restart procedure.
If an update fails, preserve the existing installation wherever possible and provide actionable error information.
Display meaningful release notes and version numbers.
Allow the user to decline or defer an update.
Do not claim an update succeeded until the installed version has been verified.
An optional background check may notify the user when a new version is available, but the user must retain control over installation and restart timing.
6. Application Packaging and Installation
Create distributable release packages for both operating systems.
macOS
Produce a proper .app bundle and, where appropriate, a distributable .dmg installer.
Include the application icon, metadata, and required runtime components.
Configure code signing and Apple notarization for normal distribution outside the development environment.
Ensure the updater can install future versions correctly.
Windows
Produce a conventional installer, such as an .exe installer or .msi package, using a format compatible with the selected updater.
Include the application icon, required runtime components, and version metadata.
Support normal installation and uninstallation.
Sign release artifacts where feasible to establish publisher identity and improve user trust.
Ensure the application and updater work without requiring users to install Python separately.
The initial release must not require users to clone a repository, install development tools, configure an environment manually, or run a terminal command.
7. Protect User Projects and Data
Application updates must be independent of registered projects.
Maintain a strict separation between:
Application files: the Hub's executable, GUI resources, bundled runtime, and internal implementation.
Application state: project registrations, preferences, history, and user-managed settings.
Project contents: the user's actual source code, virtual environments, data, and configuration files.
Store application state in the operating system's appropriate per-user application data location. Do not store essential user data inside a directory that an installer or updater may replace.
Updating or uninstalling the Hub must not silently delete, overwrite, migrate destructively, or modify registered projects.
If a future version requires a configuration migration, back up the relevant state first and provide a safe recovery path.
The Hub's own updates must not automatically update, reinstall, or alter the dependencies of registered projects.
8. Project Process Management
Preserve the Hub's existing project-management capabilities.
Ensure that:
Projects can be launched and stopped reliably on both platforms.
Process tracking does not depend on a terminal window remaining open.
Stopping the Hub does not leave unexpected orphaned processes.
The application handles crashes, missing interpreters, occupied ports, and failed startup commands.
The user can distinguish the Hub's own health from the status of individual projects.
Updating or restarting the Hub does not corrupt project state.
Running projects are handled deliberately during application updates. Ask the user to stop projects or implement a safe, documented restart strategy where necessary.
Avoid terminating unrelated user processes. Only manage processes that the Hub has sufficient evidence and authorization to own.
9. Optional Launch at Login
Provide a user-controlled preference such as Launch Local Project Hub at Login.
The feature must be optional and disabled by default.
Implement it using supported macOS and Windows mechanisms.
Provide a clear way to disable it.
Do not install a hidden background service or start the application automatically without user consent.
Do not automatically launch every registered project unless the user separately configures that behavior.
If the user disables launch at login, remove the associated registration cleanly.
10. Release and Build Workflow
Create a repeatable release process so future versions can be published without manually assembling every artifact.
Where practical, configure a CI workflow that:
Runs tests and platform compatibility checks.
Builds the macOS release on a macOS runner.
Builds the Windows release on a Windows runner.
Produces correctly versioned packages and update metadata.
Publishes release artifacts and notes when a release is approved.
Makes the new version available to the in-app updater.
Keep signing credentials and publishing tokens out of the source code. Use protected CI secrets and document any required developer accounts, certificates, or paid services.
Development builds should remain easy to run and debug without packaging the entire application every time.
11. Testing and Acceptance Criteria
Do not consider the project complete merely because an executable was generated.
Test the actual installation and update workflows on clean macOS and Windows environments.
Acceptance criteria:
A new user can install and launch the application without manually installing Python.
Existing project-management functionality still works.
Project registration and configuration persist across application restarts and upgrades.
A project using compatible Python dependencies can be launched and stopped successfully.
The application handles unsupported project requirements with useful errors.
The application can detect and install a newer release from its own menu.
A successful update preserves user configuration and registered project contents.
A failed or interrupted update does not unnecessarily destroy the working installation.
The application displays the correct version after restarting.
Launch at login works only when enabled and can be disabled again.
Uninstalling the Hub does not silently delete the user's projects.
The release process can generate new macOS and Windows builds reproducibly.
No essential installation or update operation requires the user to type terminal commands.
Document any remaining limitations, required signing credentials, external services, or manual release steps.
12. Implementation Strategy
Work in small, reviewable phases rather than attempting a complete rewrite in one pass.
Phase 1 — Audit: Understand the current implementation and establish a baseline of working features.
Phase 2 — Compatibility: Resolve Windows incompatibilities and separate platform-specific operations.
Phase 3 — Packaging: Produce a working, installable build for each operating system while preserving the current interface.
Phase 4 — Updating: Implement the in-app update workflow, including version checks, safe installation, restart behavior, and failure recovery.
Phase 5 — Polish: Add icons, menus, About/version information, and optional launch-at-login settings.
Phase 6 — Release: Configure signing, distribution, CI builds, and clean-machine testing.
At the end of each phase, report the changes made, tests performed, remaining issues, and the next recommended step. Do not mark a phase complete based solely on code inspection when it requires a real installation or runtime test.
Final Guiding Principle
Build a dependable desktop application around the existing Local Project Hub, not a new application that merely resembles it.
Prioritize preserving working code, protecting user data, predictable process management, safe in-app updates, and easy installation on both macOS and Windows. Choose the simplest architecture that meets these requirements and explain any proposed major framework change before implementing it.

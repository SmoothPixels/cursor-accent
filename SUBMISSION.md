# Marketplace submission

Pre-filled answers for the submission issue at
https://github.com/omacom/omarchy-plugin-marketplace/issues/new?template=submit-plugin.yml

Do not file this until the plugin has been installed and tested on a real
Omarchy machine: the checklist below asserts things that need to be true,
not aspirational.

**Repository URL**
```
https://github.com/SmoothPixels/cursor-accent
```

**Category**
```
Appearance
```

**Tags** (max 3)
```
Cursor, Theme, Hyprland
```

**Suggest a missing tag**
_(leave blank)_

**Maintainer notes**
```
Recolors the system pointer to the active Omarchy theme's accent color,
automatically on every `omarchy theme set`, by compiling a Bibata cursor
through hyprcursor-util (already installed: hyprcursor is a hard Hyprland
dependency). No matugen, no new runtime dependency beyond Python (already
required, stdlib tomllib needs >=3.11).

Ships as a `service`-kind plugin with no UI of its own; the actual
recoloring is a theme-set hook (a documented Omarchy extension point), opt-in
via a bundled installer script, same as this author's other plugins. A
second opt-in script adds an optional "Style > Cursor" point-and-click menu,
since service-kind plugins have no `omarchy bar set` equivalent to configure
from. Also supports locking to one fixed color, reverting to the system
default cursor, and choosing between two Bibata pointer shapes.

GPL-3.0-or-later, not MIT like this author's other plugins: it vendors
src/svg/config from rtgiskard/bibata_cursor (GPL-3.0-or-later, pinned
commit, no network access at runtime), documented in NOTICE.md.

No install hooks run automatically, no sudo, no network access at runtime.
```

**Submission checklist**
- [x] The repository is public and contains installation and removal instructions.
- [x] I have documented the plugin license and any external dependencies.
- [x] I confirm that I own or have permission to submit this plugin and its preview assets.
- [x] The plugin does not overwrite user configuration without explicit consent.
- [x] I understand that approval is for listing and is not a security review.

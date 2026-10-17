import QtQuick
import Quickshell.Io

// No UI (that's CursorSettings.qml): the actual work happens in recolor.py,
// run by the theme-set and post-boot hooks (see tools/install-cursor-hook.sh). This service only
// re-applies the current settings once when the shell (re)loads the plugin,
// so a fresh `omarchy plugin add --enable` or `omarchy-restart-shell` shows
// the right cursor immediately instead of waiting for the next theme switch.
// It only runs while the plugin is enabled in the shell, so the post-boot
// hook, not this file, is what keeps the cursor right across reboots.
Item {
  id: root

  readonly property string pluginDir: Qt.resolvedUrl(".").toString().replace("file://", "")

  Component.onCompleted: {
    applyProcess.running = true
    menuSyncProcess.running = true
  }

  // Keep the Style > Cursor menu in step with this version's snippet, but
  // only for users who already opted into it (install-cursor-hook.sh or
  // install-menu-entries.sh): an update that adds rows, like new shapes,
  // shows up without re-running setup. Never adds the menu on its own.
  Process {
    id: menuSyncProcess
    running: false
    command: ["bash", "-c",
      "menu=\"$HOME/.config/omarchy/extensions/omarchy-menu.jsonc\"; " +
      "snippet='" + root.pluginDir + "extensions/omarchy-menu.snippet.jsonc'; " +
      "grep -qF '\"style.cursor' \"$menu\" 2>/dev/null || exit 0; " +
      "[[ $(grep -F '\"style.cursor' \"$menu\") == \"$(grep -F '\"style.cursor' \"$snippet\")\" ]] && exit 0; " +
      "exec '" + root.pluginDir + "tools/install-menu-entries.sh'"
    ]
    stdout: StdioCollector { onStreamFinished: if (text) console.log("cursor-accent:", text.trim()) }
    stderr: StdioCollector { onStreamFinished: if (text) console.warn("cursor-accent:", text.trim()) }
  }

  Process {
    id: applyProcess
    running: false
    command: ["bash", "-c",
      "exec python3 '" + root.pluginDir + "recolor.py' \"$(omarchy-theme-current 2>/dev/null || echo unknown)\""
    ]
    stdout: StdioCollector { onStreamFinished: if (text) console.log("cursor-accent:", text.trim()) }
    stderr: StdioCollector { onStreamFinished: if (text) console.warn("cursor-accent:", text.trim()) }
  }
}

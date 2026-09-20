import QtQuick
import Quickshell
import Quickshell.Io

// No UI: the actual work happens in recolor.py. This service applies the
// cursor once at startup and again whenever the active theme's colors.toml
// changes, so `omarchy theme set` recolors the pointer immediately — no
// shell restart and no opt-in hook required. The opt-in theme-set hook
// (tools/install-cursor-hook.sh) is still honored; recolor.py short-circuits
// on unchanged colors, so having both never double-builds.
Item {
  id: root

  readonly property string pluginDir: Qt.resolvedUrl(".").toString().replace("file://", "")
  readonly property string colorsPath: Quickshell.env("HOME") + "/.local/state/omarchy/current/theme/colors.toml"

  // Theme switches replace the whole current/theme directory (rm -rf + mv,
  // see omarchy-theme-set), so a watch on the colors.toml path itself is
  // dropped after the first rename. Poll instead: re-read a ~600B file once
  // a second and rebuild only when the palette actually changed.
  property string lastColors: ""
  property bool pendingApply: false
  property int pollIntervalMs: 1000

  FileView {
    id: colorsFile
    path: root.colorsPath
    printErrors: false
    onLoaded: root.onColorsLoaded(text())
    // colors.toml is briefly absent mid-swap (the theme dir is moved, not
    // updated in place); wait for the next poll rather than applying a stale
    // palette.
    onLoadFailed: function() {}
  }

  Timer {
    id: pollTimer
    interval: root.pollIntervalMs
    running: true
    repeat: true
    onTriggered: colorsFile.reload()
  }

  function onColorsLoaded(raw) {
    if (raw === root.lastColors) return
    root.lastColors = raw
    root.apply()
  }

  function apply() {
    if (applyProcess.running) {
      // Rebuilds take a few seconds; if the theme changes mid-build, run the
      // fresh palette when the in-flight one finishes instead of dropping it.
      root.pendingApply = true
      return
    }
    applyProcess.running = true
  }

  Process {
    id: applyProcess
    running: false
    command: ["bash", "-c",
      "exec python3 '" + root.pluginDir + "recolor.py' \"$(omarchy-theme-current 2>/dev/null || echo unknown)\""
    ]
    stdout: StdioCollector { onStreamFinished: if (text) console.log("cursor-accent:", text.trim()) }
    stderr: StdioCollector { onStreamFinished: if (text) console.warn("cursor-accent:", text.trim()) }
    onRunningChanged: if (!running && root.pendingApply) {
      root.pendingApply = false
      running = true
    }
  }
}

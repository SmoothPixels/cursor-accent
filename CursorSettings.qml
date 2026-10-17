import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// Settings window: pick the color mode and the pointer style.
//
// Open with `cursor-accent settings` (or Style > Cursor > Settings… in the
// menu), which runs `omarchy-shell shell summon io.github.smoothpixels.cursor-accent`.
// State is ~/.local/state/cursor-accent/config.json, watched here, so the
// window stays in sync with the CLI and menu. Every change goes through the
// `cursor-accent` command, same as those.
Item {
  id: root

  // Injected by the Omarchy shell loader.
  property var shell: null
  property var manifest: null
  readonly property string pluginId: String((manifest && manifest.id) || "io.github.smoothpixels.cursor-accent")

  property bool opened: false

  readonly property string pluginDir: Qt.resolvedUrl(".").toString().replace(/^file:\/\//, "")
  readonly property string home: Quickshell.env("HOME")

  // name, label, blurb; order is the grid order
  readonly property var styles: [
    { key: "modern",         label: "Modern",         blurb: "Bibata, rounded" },
    { key: "original",       label: "Original",       blurb: "Bibata, sharp" },
    { key: "macos",          label: "macOS",          blurb: "Classic, with tail" },
    { key: "macos-tailless", label: "macOS Tailless", blurb: "Modern macOS" },
    { key: "dart",           label: "Dart",           blurb: "Slim and sharp" },
    { key: "retro",          label: "Retro",          blurb: "1-bit pixels" },
    { key: "crosshair",      label: "Crosshair",      blurb: "Precision pointer" },
    { key: "dot",            label: "Dot",            blurb: "Round, tablet-style" }
  ]
  readonly property var modes: [
    { key: "theme", label: "Follow Theme", cmd: ["follow"] },
    { key: "fixed", label: "Fixed Color",  cmd: null },
    { key: "off",   label: "System Default", cmd: ["default"] }
  ]
  readonly property int columns: 4

  // ── State ──────────────────────────────────────────────────────────────
  property string mode: "theme"
  property string shape: "modern"
  property string fixedColor: "#F25623"
  property var theme: ({})
  property bool busy: false
  property string message: ""
  // Keyboard cursor over modes (0..2) then styles (3..)
  property int cursor: 0

  readonly property bool hexValid: /^#[0-9a-fA-F]{6}$/.test(hexField.text)
  readonly property color previewAccent: mode === "fixed" ? fixedColor : (theme.accent || "#F25623")
  readonly property color previewBody: mode === "fixed" ? "#171717" : (theme.dark_background || theme.background || "#171717")

  FileView {
    path: root.home + "/.local/state/cursor-accent/config.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.readConfig(text())
    onFileChanged: reload()
  }
  function readConfig(raw) {
    try {
      var c = JSON.parse(raw)
      root.mode = String(c.mode || "theme")
      root.shape = String(c.shape || "modern")
      root.fixedColor = String(c.fixed_color || "#F25623")
    } catch (e) {}
  }

  // Same keys recolor.py reads from the active theme.
  FileView {
    path: root.home + "/.local/state/omarchy/current/theme/colors.toml"
    watchChanges: true
    printErrors: false
    onLoaded: root.readTheme(text())
    onFileChanged: reload()
  }
  function readTheme(raw) {
    var t = {}
    var re = /^\s*(accent|background|dark_background)\s*=\s*["']([^"']+)["']/gm
    var m
    while ((m = re.exec(raw)) !== null) t[m[1]] = m[2]
    root.theme = t
  }

  // ── Applying ───────────────────────────────────────────────────────────
  Process {
    id: applyProc
    running: false
    stderr: StdioCollector { id: applyErr }
    onExited: function (code) {
      root.busy = false
      root.message = code === 0 ? "" : (applyErr.text.trim().split("\n").pop() || "cursor-accent failed (" + code + ")")
    }
  }
  function run(args) {
    if (applyProc.running) return
    root.busy = true
    root.message = ""
    applyProc.command = [root.pluginDir + "cursor-accent"].concat(args)
    applyProc.running = true
  }
  function pickMode(i) {
    var m = root.modes[i]
    if (m.key === "fixed") applyFixed()
    else run(m.cmd)
  }
  function applyFixed() {
    if (!root.hexValid) { root.message = "Enter a color as #rrggbb"; hexField.forceActiveFocus(); return }
    run(["fixed", hexField.text])
  }
  function pickStyle(i) { run(["shape", root.styles[i].key]) }
  function activate(i) {
    if (i < root.modes.length) pickMode(i)
    else pickStyle(i - root.modes.length)
  }

  // key -> raw preview SVG (body/outline still the #00FF00/#0000FF keys)
  property var previews: ({})
  function previewSource(key) {
    var text = root.previews[key]
    if (!text) return ""
    text = text.replace(/#00FF00/gi, String(root.previewBody))
               .replace(/#0000FF/gi, String(root.previewAccent))
               .replace(/#FF0000/gi, String(root.previewBody))
    return "data:image/svg+xml;utf8," + encodeURIComponent(text)
  }
  Instantiator {
    model: root.styles
    delegate: FileView {
      required property var modelData
      path: root.pluginDir + "assets/previews/" + modelData.key + ".svg"
      printErrors: false
      onLoaded: {
        var next = Object.assign({}, root.previews)
        next[modelData.key] = text()
        root.previews = next
      }
    }
  }

  // ── Overlay contract ───────────────────────────────────────────────────
  function open(payloadJson) {
    root.opened = true
    root.message = ""
    hexField.text = root.fixedColor
    var idx = root.styles.findIndex(function (s) { return s.key === root.shape })
    root.cursor = root.mode === "theme" || root.mode === "off"
      ? root.modes.length + Math.max(0, idx)
      : 1
    Qt.callLater(function () { keys.forceActiveFocus() })
  }
  function close() { root.opened = false }
  function dismiss() {
    root.close()
    if (root.shell && typeof root.shell.hide === "function") root.shell.hide(root.pluginId)
  }
  function toggle() { if (root.opened) root.dismiss(); else root.open("{}") }
  function summon(payloadJson) { root.open(payloadJson || "{}") }
  function hide() { root.dismiss() }

  function move(delta) {
    var n = root.modes.length + root.styles.length
    root.cursor = Math.max(0, Math.min(n - 1, root.cursor + delta))
  }
  function moveRow(dir) {
    var m = root.modes.length
    if (root.cursor < m) {
      if (dir > 0) root.cursor = m + Math.min(root.cursor, root.columns - 1)
      return
    }
    var i = root.cursor - m + dir * root.columns
    if (i < 0) root.cursor = Math.min(root.cursor - m, m - 1)
    else if (i < root.styles.length) root.cursor = m + i
  }

  PanelWindow {
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"

    WlrLayershell.namespace: "omarchy-cursor-accent"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: Util.alpha(Color.background, 0.7)
      TapHandler { onTapped: root.dismiss() }
    }

    Item {
      id: keys
      anchors.fill: parent
      focus: true
      Keys.onPressed: function (event) {
        var t = event.text, k = event.key
        if (k === Qt.Key_Escape || t === "q") root.dismiss()
        else if (k === Qt.Key_Left || t === "h") root.move(-1)
        else if (k === Qt.Key_Right || t === "l") root.move(1)
        else if (k === Qt.Key_Up || t === "k") root.moveRow(-1)
        else if (k === Qt.Key_Down || t === "j") root.moveRow(1)
        else if (k === Qt.Key_Return || k === Qt.Key_Enter || k === Qt.Key_Space) root.activate(root.cursor)
        else if (k === Qt.Key_Tab || t === "c") hexField.forceActiveFocus()
        else return
        event.accepted = true
      }

      Rectangle {
        id: card
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 640)
        height: body.implicitHeight + 2 * pad
        readonly property int pad: Style.spacing.huge * 2
        radius: 12
        color: Color.popups.background
        border.width: 1
        border.color: Util.alpha(Color.popups.border, 0.6)
        MouseArea { anchors.fill: parent }  // swallow scrim taps

        ColumnLayout {
          id: body
          anchors { fill: parent; margins: card.pad }
          spacing: Style.spacing.huge

          RowLayout {
            Layout.fillWidth: true
            Text {
              text: "Cursor"
              color: Color.foreground
              font { family: Style.font.family; pixelSize: Style.font.display; bold: true }
            }
            Item { Layout.fillWidth: true }
            Text {
              text: root.busy ? "Applying…" : root.message
              color: root.message ? Color.urgent : Color.muted
              font { family: Style.font.family; pixelSize: Style.font.body }
            }
          }

          // ── Color mode ──
          Text {
            text: "COLOR"
            color: Color.muted
            font { family: Style.font.family; pixelSize: Style.font.caption; letterSpacing: 1.5 }
          }
          RowLayout {
            Layout.fillWidth: true
            spacing: Style.spacing.controlGap
            Repeater {
              model: root.modes
              delegate: Button {
                required property var modelData
                required property int index
                text: modelData.label
                bordered: true
                selected: root.mode === modelData.key
                hasCursor: root.cursor === index
                onClicked: { root.cursor = index; root.pickMode(index) }
              }
            }
            Item { Layout.fillWidth: true }
            Rectangle {
              Layout.preferredWidth: 22; Layout.preferredHeight: 22
              radius: 11
              color: root.hexValid ? hexField.text : "transparent"
              border.width: 1
              border.color: Util.alpha(Color.foreground, 0.4)
            }
            TextField {
              id: hexField
              Layout.preferredWidth: 96
              placeholderText: "#rrggbb"
              maximumLength: 7
              onAccepted: { root.applyFixed(); keys.forceActiveFocus() }
              Keys.onEscapePressed: keys.forceActiveFocus()
            }
          }

          // ── Style grid ──
          Text {
            text: "STYLE"
            color: Color.muted
            font { family: Style.font.family; pixelSize: Style.font.caption; letterSpacing: 1.5 }
          }
          GridLayout {
            Layout.fillWidth: true
            columns: root.columns
            columnSpacing: Style.spacing.xxl
            rowSpacing: Style.spacing.xxl
            Repeater {
              model: root.styles
              delegate: Rectangle {
                id: tile
                required property var modelData
                required property int index
                readonly property bool current: root.shape === modelData.key
                readonly property bool cursorOn: root.cursor === root.modes.length + index
                Layout.fillWidth: true
                Layout.preferredHeight: 132
                radius: 10
                color: current ? Util.alpha(Color.accent, 0.14)
                     : (hover.hovered || cursorOn) ? Util.alpha(Color.foreground, 0.07)
                     : Util.alpha(Color.foreground, 0.03)
                border.width: current ? 2 : (cursorOn ? 1 : 0)
                border.color: current ? Color.accent : Util.alpha(Color.foreground, 0.5)
                opacity: root.mode === "off" ? 0.5 : 1

                Image {
                  anchors { top: parent.top; topMargin: 10; horizontalCenter: parent.horizontalCenter }
                  width: 72; height: 72
                  sourceSize { width: 144; height: 144 }
                  smooth: tile.modelData.key !== "retro"
                  source: root.previewSource(tile.modelData.key)
                }
                Column {
                  anchors { bottom: parent.bottom; bottomMargin: 10; horizontalCenter: parent.horizontalCenter }
                  Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: tile.modelData.label
                    color: Color.foreground
                    font { family: Style.font.family; pixelSize: Style.font.subtitle; bold: tile.current }
                  }
                  Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: tile.modelData.blurb
                    color: Color.muted
                    font { family: Style.font.family; pixelSize: Style.font.caption }
                  }
                }
                HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: { root.cursor = root.modes.length + tile.index; root.pickStyle(tile.index) } }
              }
            }
          }

          Text {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            text: "←↓↑→ / hjkl move · Enter apply · Tab color · Esc close"
            color: Color.muted
            font { family: Style.font.family; pixelSize: Style.font.caption }
          }
        }
      }
    }
  }
}

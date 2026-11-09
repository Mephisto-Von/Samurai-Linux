/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
import QtQuick
import QtQuick.Layouts
import QtQuick.Dialogs
import org.kde.kcmutils as KCMUtils
import org.kde.kirigami as Kirigami
import QtQuick.Controls as Controls

KCMUtils.SimpleKCM {
    // The themes come from the Hub's own presets.json via the C++ side, so
    // this page can never show a theme the Hub does not offer.
    readonly property var themes: JSON.parse(kcm.themesJson())
    readonly property var roles: ["background", "panel", "surface", "text", "text_dim", "accent", "gold", "border"]

    // The theme the Hub's marker names, so the page opens on the current one.
    readonly property var activeTheme: {
        const current = kcm.currentTheme()
        for (var i = 0; i < themes.length; i++) {
            if (themes[i].slug === current) {
                return i
            }
        }
        return 0
    }

    readonly property var theme: themes.length > 0 ? themes[themeBox.currentIndex] : undefined

    // role -> "#RRGGBB" as shown in the swatches; seeded from the theme and
    // changed through the colour picker below.
    property var swatches: ({})

    // The custom button is only interesting when a swatch differs from the
    // chosen theme's own palette.
    readonly property bool coloursDirty: {
        if (theme === undefined) {
            return false
        }
        for (const role of roles) {
            if (String(swatches[role] || "").toUpperCase() !== String(theme.palette[role] || "").toUpperCase()) {
                return true
            }
        }
        return false
    }

    property bool busy: false
    property string statusText: ""

    function reloadColours() {
        const next = {}
        if (theme !== undefined) {
            for (const role of roles) {
                next[role] = theme.palette[role] || "#000000"
            }
        }
        swatches = next
    }

    function roleLabel(role) {
        switch (role) {
        case "background": return i18n("Background")
        case "panel": return i18n("Panel")
        case "surface": return i18n("Surface")
        case "text": return i18n("Text")
        case "text_dim": return i18n("Dimmed text")
        case "accent": return i18n("Accent")
        case "gold": return i18n("Gold")
        case "border": return i18n("Borders")
        default: return role
        }
    }

    function applyTheme() {
        if (theme === undefined || busy) {
            return
        }
        busy = true
        statusText = i18n("Applying %1…", theme.name)
        const ok = kcm.applyTheme(theme.slug)
        statusText = ok ? i18n("Applied the %1 theme", theme.name) : kcm.lastApplyMessage()
        busy = false
    }

    function applyColours() {
        if (theme === undefined || busy) {
            return
        }
        busy = true
        statusText = i18n("Saving custom colours for %1…", theme.name)
        const ok = kcm.applyCustomColors(theme.slug, JSON.stringify(swatches))
        statusText = ok ? i18n("Saved and applied a custom variant of %1", theme.name) : kcm.lastApplyMessage()
        busy = false
    }

    Component.onCompleted: reloadColours()

    Kirigami.FormLayout {
        Kirigami.Heading {
            level: Kirigami.Heading.Secondary
            text: i18n("Samurai Customization Hub")
        }

        Controls.Label {
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            text: i18n("Pick a built-in theme, or change individual colours. Applying colours saves a custom variant (samurai-custom-…) beside the built-in schemes; the full Hub window does the same thing in more detail, with live preview, wallpapers and a theme library.")
        }

        Controls.ComboBox {
            id: themeBox
            Kirigami.FormData.label: i18n("Theme")
            model: themes
            textRole: "name"
            enabled: themes.length > 0 && !busy
            Component.onCompleted: currentIndex = activeTheme
            onCurrentIndexChanged: reloadColours()
        }

        Controls.Label {
            Kirigami.FormData.label: i18n("About")
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            text: theme === undefined ? "" : theme.tagline
        }

        // One row per palette role: a swatch, the name, the hex value for
        // anyone who reads schemes by hand, and the picker.
        ColumnLayout {
            Repeater {
                model: roles
                delegate: RowLayout {
                    Layout.fillWidth: true

                    Rectangle {
                        radius: 3
                        Layout.preferredWidth: 44
                        Layout.preferredHeight: 22
                        color: swatches[modelData] || "#000000"
                        border.color: Kirigami.Theme.disabledTextColor
                        border.width: 1
                    }

                    Controls.Label {
                        Layout.fillWidth: true
                        text: roleLabel(modelData) + ": " + String(swatches[modelData] || "").toUpperCase()
                    }

                    Controls.Button {
                        text: i18n("Choose…")
                        enabled: !busy
                        onClicked: {
                            colourPicker.currentColor = swatches[modelData] || "#000000"
                            colourPicker.targetRole = modelData
                            colourPicker.open()
                        }
                    }
                }
            }
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Apply")
            Controls.Button {
                text: i18n("Apply theme")
                enabled: theme !== undefined && !busy
                onClicked: applyTheme()
            }
            Controls.Button {
                text: i18n("Apply colours")
                enabled: coloursDirty && !busy
                onClicked: applyColours()
            }
            Controls.Button {
                text: i18n("Reset colours")
                enabled: coloursDirty && !busy
                onClicked: reloadColours()
            }
        }

        RowLayout {
            Kirigami.FormData.label: i18n("More")
            Controls.Button {
                icon.name: "preferences-desktop-color"
                text: i18n("Open Samurai Customization Hub")
                enabled: kcm.hubAvailable() && !busy
                onClicked: kcm.openHub()
            }
        }

        RowLayout {
            Controls.BusyIndicator {
                visible: busy
                running: busy
            }
            Controls.Label {
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
                text: statusText
            }
        }
    }

    // One picker for every row; the row that asked is remembered because the
    // dialog only has one accepted signal.
    ColorDialog {
        id: colourPicker
        property string targetRole: ""
        title: i18n("Choose colour")
        modality: Qt.WindowModal

        onAccepted: {
            const c = currentColor
            const hex = (v) => Math.round(v * 255).toString(16).toUpperCase().padStart(2, "0")
            const next = Object.assign({}, swatches)
            next[targetRole] = "#" + hex(c.r) + hex(c.g) + hex(c.b)
            swatches = next
        }
    }
}

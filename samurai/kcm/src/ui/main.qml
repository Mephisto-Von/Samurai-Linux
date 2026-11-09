/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
import QtQuick
import QtQuick.Layouts
import org.kde.kcmutils as KCMUtils
import org.kde.kirigami as Kirigami
import QtQuick.Controls as Controls

KCMUtils.SimpleKCM {
    Kirigami.FormLayout {
        Kirigami.Heading {
            level: Kirigami.Heading.Secondary
            text: i18n("Samurai Customization Hub")
        }

        Controls.Label {
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            text: i18n("Themes, colours and wallpapers for Samurai Linux are managed in the Customization Hub. The Hub opens as a window, previews changes before applying them, and keeps your own pictures out of the system image.")
        }

        Controls.Button {
            icon.name: "preferences-desktop-color"
            text: i18n("Open Samurai Customization Hub")
            enabled: kcm.hubAvailable()
            onClicked: kcm.openHub()
        }

        Controls.Label {
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            text: i18n("Without the Hub the appearance can still be changed from a terminal: 'samurai-theme list' and 'samurai-theme set <theme>'.")
        }
    }
}

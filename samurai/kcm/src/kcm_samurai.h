/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#pragma once

#include <KQuickConfigModule>

#include <QJsonArray>
#include <QString>

/**
 * @brief Entry for the Samurai Customization Hub inside System Settings.
 *
 * The Hub's theme data (presets.json) is the source of truth, so this module
 * reads it once and exposes just the surface its page needs: the theme list
 * and its colours. Applying a theme or a set of custom colours goes through
 * the Hub's own headless commands, so a change from this page and the same
 * change in the Hub window produce the same scheme file.
 */
class KcmSamurai : public KQuickConfigModule
{
    Q_OBJECT

public:
    KcmSamurai(QObject *parent, const KPluginMetaData &data);

    /** True when the Hub launcher is installed. */
    Q_INVOKABLE bool hubAvailable() const;

    /** Open the Hub window on the current session. */
    Q_INVOKABLE void openHub();

    /**
     * The built-in themes as a JSON array: slug, name, tagline, wallpaper and
     * the palette (one #RRGGBB entry per role), ready for JSON.parse in QML.
     */
    Q_INVOKABLE QString themesJson() const;

    /** The slug of the theme the Hub last applied, or an empty string. */
    Q_INVOKABLE QString currentTheme() const;

    /** Apply a theme exactly as the Hub does. Returns true on success. */
    Q_INVOKABLE bool applyTheme(const QString &slug);

    /**
     * Save a custom variant of a theme with per-role colours (a JSON object of
     * role -> "#RRGGBB") and apply it. Returns true on success.
     */
    Q_INVOKABLE bool applyCustomColors(const QString &slug, const QString &overridesJson);

    /** What the last apply said; use it for the status line. */
    Q_INVOKABLE QString lastApplyMessage() const;

private:
    bool runHubCommand(const QStringList &arguments);

    QJsonArray m_themes;
    QString m_lastApplyMessage;
};

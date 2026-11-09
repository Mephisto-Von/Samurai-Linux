/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#pragma once

#include <KQuickConfigModule>

/**
 * @brief Entry for the Samurai Customization Hub inside System Settings.
 *
 * The Hub itself is a Qt window (Business logic in /usr/share/samurai/hub),
 * which System Settings cannot host, so this module is deliberately small:
 * it tells the user where the Hub is and opens it.
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
};

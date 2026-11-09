/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "kcm_samurai.h"

#include <KPluginFactory>
#include <QFileInfo>
#include <QProcess>

K_PLUGIN_CLASS_WITH_JSON(KcmSamurai, "kcm_samurai.json")

KcmSamurai::KcmSamurai(QObject *parent, const KPluginMetaData &data)
    : KQuickConfigModule(parent, data)
{
    // Nothing to save or reset: the KCM front of the Hub, not a settings store.
    setButtons(Help);
}

bool KcmSamurai::hubAvailable() const
{
    return QFileInfo::exists(QStringLiteral("/usr/local/bin/samurai-customize"));
}

void KcmSamurai::openHub()
{
    QProcess::startDetached(QStringLiteral("/usr/local/bin/samurai-customize"));
}

#include "kcm_samurai.moc"

/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "kcm_samurai.h"

#include <KPluginFactory>

#include <QJsonDocument>
#include <QJsonObject>
#include <QFile>
#include <QFileInfo>
#include <QProcess>
#include <QStandardPaths>

K_PLUGIN_CLASS_WITH_JSON(KcmSamurai, "kcm_samurai.json")

namespace
{
constexpr auto kLauncher = "/usr/local/bin/samurai-customize";
constexpr auto kPresetsPath = "/usr/share/samurai/hub/presets.json";
constexpr int kApplyTimeoutMs = 120000;

QString runHubProcess(const QStringList &arguments, QString *message)
{
    QProcess process;
    process.start(QString::fromUtf8(kLauncher), arguments);
    if (!process.waitForStarted(10000)) {
        if (message) {
            *message = QString::fromUtf8(kLauncher) + QStringLiteral(": ") + process.errorString();
        }
        return QStringLiteral("error");
    }
    if (!process.waitForFinished(kApplyTimeoutMs)) {
        process.kill();
        if (message) {
            *message = QStringLiteral("The Hub did not answer within %1 seconds").arg(kApplyTimeoutMs / 1000);
        }
        return QStringLiteral("error");
    }
    const QString output = QString::fromUtf8(process.readAllStandardOutput()).trimmed();
    const QString errors = QString::fromUtf8(process.readAllStandardError()).trimmed();
    if (message) {
        *message = output.isEmpty() ? errors : output;
    }
    return process.exitStatus() == QProcess::NormalExit && process.exitCode() == 0 ? QStringLiteral("ok") : QStringLiteral("error");
}

} // namespace

KcmSamurai::KcmSamurai(QObject *parent, const KPluginMetaData &data)
    : KQuickConfigModule(parent, data)
{
    // Nothing here is stored by the KCM; the overrides go to the Hub's scheme
    // files, so there is nothing to save, reset or apply row by row.
    setButtons(Help);

    QFile file(QString::fromUtf8(kPresetsPath));
    if (file.open(QIODevice::ReadOnly | QIODevice::Text)) {
        m_themes = QJsonDocument::fromJson(file.readAll()).object().value(QStringLiteral("presets")).toArray();
    }
}

bool KcmSamurai::hubAvailable() const
{
    QFileInfo info(QString::fromUtf8(kLauncher));
    return info.exists() && info.isExecutable();
}

void KcmSamurai::openHub()
{
    QProcess::startDetached(QString::fromUtf8(kLauncher));
}

QString KcmSamurai::themesJson() const
{
    return QJsonDocument(m_themes).toJson(QJsonDocument::Compact);
}

QString KcmSamurai::currentTheme() const
{
    const QString marker = QStandardPaths::writableLocation(QStandardPaths::ConfigLocation)
        + QStringLiteral("/samurai/theme");
    QFile file(marker);
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) {
        return {};
    }
    return QString::fromUtf8(file.readAll()).trimmed();
}

bool KcmSamurai::runHubCommand(const QStringList &arguments)
{
    const QString status = runHubProcess(arguments, &m_lastApplyMessage);
    return status == QStringLiteral("ok");
}

bool KcmSamurai::applyTheme(const QString &slug)
{
    if (!hubAvailable()) {
        m_lastApplyMessage = QStringLiteral("The Samurai Customization Hub is not installed");
        return false;
    }
    return runHubCommand({QStringLiteral("--apply-theme"), slug});
}

bool KcmSamurai::applyCustomColors(const QString &slug, const QString &overridesJson)
{
    if (!hubAvailable()) {
        m_lastApplyMessage = QStringLiteral("The Samurai Customization Hub is not installed");
        return false;
    }
    const QJsonDocument document = QJsonDocument::fromJson(overridesJson.toUtf8());
    if (!document.isObject()) {
        m_lastApplyMessage = QStringLiteral("The colour values were not understood");
        return false;
    }
    QStringList arguments{QStringLiteral("--apply-custom-theme"), slug};
    for (auto it = document.object().begin(); it != document.object().end(); ++it) {
        arguments << (it.key() + QLatin1Char('=') + it.value().toString());
    }
    return runHubCommand(arguments);
}

QString KcmSamurai::lastApplyMessage() const
{
    return m_lastApplyMessage;
}

#include "kcm_samurai.moc"

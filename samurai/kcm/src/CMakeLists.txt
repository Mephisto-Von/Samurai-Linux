# SPDX-License-Identifier: GPL-2.0-or-later
kcmutils_add_qml_kcm(kcm_samurai)

target_sources(kcm_samurai PRIVATE kcm_samurai.cpp kcm_samurai.h)

target_link_libraries(kcm_samurai PRIVATE
    Qt::Quick
    KF6::CoreAddons
    KF6::KCMUtils
    KF6::I18n
)

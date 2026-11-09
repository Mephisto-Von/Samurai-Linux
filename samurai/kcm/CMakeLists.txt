# SPDX-License-Identifier: GPL-2.0-or-later
#
# Samurai Customization Hub - Settings module (KCM).
#
# The Hub is a Qt window, not a KCM (System Settings only hosts KCM plugins),
# so this tiny compiled plugin exists for one job: put an entry for the Hub in
# System Settings -> Personalization that opens the window. It is built by
# build/build.sh, which installs the CMake dev packages on the build host and
# refuses nothing if cmake is missing (it logs a warning and builds without
# the KCM; build/verify-iso.sh then points at the missing packages).
cmake_minimum_required(VERSION 3.16)

set(QT_MIN_VERSION "6.5.0")
set(KF6_MIN_VERSION "6.0.0")
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED TRUE)

project(kcm_samurai)

find_package(ECM ${KF6_MIN_VERSION} REQUIRED NO_MODULE)
set(CMAKE_MODULE_PATH ${ECM_MODULE_PATH} ${CMAKE_CURRENT_SOURCE_DIR}/cmake)

include(KDEInstallDirs)
include(KDECompilerSettings NO_POLICY_SCOPE)
include(KDECMakeSettings)

find_package(Qt6 ${QT_MIN_VERSION} CONFIG REQUIRED Core Quick Gui Qml)
find_package(KF6 ${KF6_MIN_VERSION} REQUIRED COMPONENTS Config CoreAddons KCMUtils I18n)

add_subdirectory(src)

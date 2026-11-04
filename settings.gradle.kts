/*
 * Purpose: Gradle settings for the Music Player Android app (plugin repos + module list).
 * Version: v1 (2026-10-11)
 * Scope: PRODUCTION - build config for the music phone's player app.
 * Architecture: root of the Gradle build; includes the single :app module.
 * Invocation: read by ./gradlew (gradlew.bat) on every build.
 */
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "music-player"
include(":app")

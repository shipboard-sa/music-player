/*
 * Purpose: Root build file - declares plugin versions for the :app module.
 * Version: v1 (2026-10-11)
 * Scope: PRODUCTION - build config for the music phone's player app.
 * Architecture: plugin versions only; all real config is in app/build.gradle.kts.
 * Invocation: read by ./gradlew on every build.
 */
plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.0.21" apply false
}

/*
 * Purpose: Android app module build - SDK levels, Compose, Media3 player, tests.
 * Version: v1 (2026-10-11)
 * Scope: PRODUCTION - build config for the music phone's player app.
 * Architecture: the only module; sources in src/main, JVM unit tests in src/test.
 * Invocation: ./gradlew assembleDebug (APK -> app/build/outputs/apk/debug/),
 *   ./gradlew testDebugUnitTest, ./gradlew installDebug (phone on adb).
 */
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "us.unladenswallow.musicplayer"
    compileSdk = 35

    defaultConfig {
        applicationId = "us.unladenswallow.musicplayer"
        minSdk = 26
        targetSdk = 35
        versionCode = 7
        versionName = "0.3.3"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
    }
}

dependencies {
    val media3 = "1.4.1"
    implementation("androidx.media3:media3-exoplayer:$media3")
    implementation("androidx.media3:media3-session:$media3")

    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-guava:1.8.1")

    implementation(platform("androidx.compose:compose-bom:2024.10.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")

    testImplementation("junit:junit:4.13.2")
}

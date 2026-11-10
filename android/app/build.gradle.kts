plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.example.yingbian"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "com.example.yingbian"
        minSdk = 24
        targetSdk = 37
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    // Two demo packages: emulator (offline mock) and LAN (talks to the PC backend).
    // Override the LAN address at build time: -PbaseUrl=http://192.168.1.23:8000
    flavorDimensions += "env"
    productFlavors {
        create("emulator") {
            dimension = "env"
            buildConfigField("String", "DEFAULT_BASE", "\"http://10.0.2.2:8000\"")
            buildConfigField("boolean", "DEFAULT_MOCK", "true")
        }
        create("lan") {
            dimension = "env"
            // 真实通道的默认后端地址，优先级从高到低：
            //   1) 打包时 -PbaseUrl=http://x.x.x.x:8000
            //   2) 这里的兜底值（当前开发机 IP）
            //   3) App 内「连接设置」的运行时覆盖（prefs 优先于 BuildConfig）
            //      → 演示当天 IP 变了，在设置里改一下即可，不用重新打包
            // ⚠️ IP 会变，每次演示前用 ipconfig 确认 WLAN 的 IPv4 地址。
            val baseUrl = (project.findProperty("baseUrl") as String?) ?: "http://10.195.151.83:8000"
            buildConfigField("String", "DEFAULT_BASE", "\"$baseUrl\"")
            buildConfigField("boolean", "DEFAULT_MOCK", "false")
        }
    }

    buildTypes {
        release {
            optimization {
                enable = true
                packageScope = setOf("androidx.**", "kotlin.**", "kotlinx.**")
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons.core)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    testImplementation(libs.junit)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
    debugImplementation(libs.androidx.compose.ui.tooling)
}

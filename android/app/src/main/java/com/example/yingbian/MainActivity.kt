package com.example.yingbian

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.example.yingbian.ui.YingBianRoot
import com.example.yingbian.ui.theme.YingBianTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            YingBianTheme {
                YingBianRoot()
            }
        }
    }
}

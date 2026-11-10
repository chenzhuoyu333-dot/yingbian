package com.example.yingbian.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.yingbian.data.verifyConnection
import kotlinx.coroutines.launch

private val ConnectOk = Color(0xFF2E7D32)
private val ConnectFail = Color(0xFFC62828)

@Composable
fun SettingsDialog(
    initialBase: String,
    initialMock: Boolean,
    defaultBase: String,
    defaultMock: Boolean,
    onSave: (String, Boolean) -> Unit,
    onDebug: () -> Unit,
    onDismiss: () -> Unit,
) {
    var base by remember { mutableStateOf(initialBase) }
    var mock by remember { mutableStateOf(initialMock) }
    var testing by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf<String?>(null) }
    var resultOk by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("连接设置") },
        text = {
            Column {
                Text(
                    "模拟器用 10.0.2.2；真机填电脑的局域网 IP，启动后端时会打印出来。",
                    fontSize = 12.sp,
                    color = Muted,
                )
                Spacer(Modifier.height(10.dp))

                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("离线演示", fontSize = 14.sp, fontWeight = FontWeight.Medium)
                        Text("不连后端，直接用内置数据", fontSize = 11.sp, color = Muted)
                    }
                    Switch(
                        checked = mock,
                        onCheckedChange = {
                            mock = it
                            result = null
                        },
                    )
                }

                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = base,
                    onValueChange = {
                        base = it
                        result = null
                    },
                    label = { Text("服务器地址") },
                    singleLine = true,
                    enabled = !mock,
                    modifier = Modifier.fillMaxWidth(),
                )

                Spacer(Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(
                        enabled = !mock && !testing,
                        onClick = {
                            testing = true
                            result = null
                            scope.launch {
                                val text = verifyConnection(base)
                                result = text
                                resultOk = text.startsWith("通")
                                testing = false
                            }
                        },
                    ) {
                        Text(if (testing) "测试中…" else "测试连接", fontSize = 13.sp)
                    }
                    TextButton(
                        onClick = {
                            base = defaultBase
                            mock = defaultMock
                            result = null
                        },
                    ) {
                        Text("恢复默认", fontSize = 13.sp)
                    }
                }

                result?.let { text ->
                    Text(
                        text,
                        fontSize = 12.sp,
                        color = if (resultOk) ConnectOk else ConnectFail,
                    )
                }
                Text("默认地址：$defaultBase", fontSize = 11.sp, color = Muted)
                TextButton(onClick = onDebug) {
                    Text("演示调试选项", fontSize = 12.sp)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onSave(base, mock) }) { Text("保存并重载") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        },
    )
}

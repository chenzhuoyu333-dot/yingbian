package com.example.yingbian.data

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * 后台定位服务和界面之间只传“最近一次判断结果”。
 * 不存轨迹、不落盘；界面活着就即时显示，界面不在就等下次打开再看。
 */
object TrackBus {
    private val _results = MutableStateFlow<LocateResult?>(null)
    val results: StateFlow<LocateResult?> = _results

    fun publish(result: LocateResult) {
        _results.value = result
    }
}

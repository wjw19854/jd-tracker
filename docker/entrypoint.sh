#!/bin/bash
set -e

INTERVAL="${JD_TRACKER_INTERVAL:-${1:-1800}}"
ACTIVE_HOURS="${JD_TRACKER_ACTIVE_HOURS:-}"  # e.g. "8-23"

echo "============================================"
echo " jd-tracker container started"
echo " Interval: ${INTERVAL}s ($((INTERVAL/60))m$((INTERVAL%60))s)"
echo " Active hours: ${ACTIVE_HOURS:-全天}"
echo " Headless: $JD_TRACKER_HEADLESS"
echo " Chrome Channel: '${JD_TRACKER_CHROME_CHANNEL}'"
echo "============================================"

# 检查当前是否在活跃时间段内
is_active() {
    if [ -z "$ACTIVE_HOURS" ]; then
        return 0  # 未设置 = 全天运行
    fi
    local start_hour="${ACTIVE_HOURS%-*}"
    local end_hour="${ACTIVE_HOURS#*-}"
    # 去掉前导零防止被解释为八进制
    local now_hour=$((10#$(date +%H)))
    if [ "$now_hour" -ge "$start_hour" ] && [ "$now_hour" -lt "$end_hour" ]; then
        return 0
    fi
    return 1
}

# 休眠到下一个活跃时段开始
sleep_until_active() {
    local start_hour="${ACTIVE_HOURS%-*}"
    local now_hour=$((10#$(date +%H)))
    local now_min=$((10#$(date +%M)))
    local now_sec=$((10#$(date +%S)))

    local wait_sec
    if [ "$now_hour" -ge "$start_hour" ]; then
        # 当天活跃时段已过，等到明天
        wait_sec=$(( (24 - now_hour + start_hour) * 3600 - now_min * 60 - now_sec ))
    else
        # 还没到今天的开始时间
        wait_sec=$(( (start_hour - now_hour) * 3600 - now_min * 60 - now_sec ))
    fi
    echo "$(date '+%H:%M:%S') [SKIP] 非活跃时段，休眠 ${wait_sec}s (约 $((wait_sec/3600))h$(((wait_sec%3600)/60))m) 后在 ${ACTIVE_HOURS%-*}:00 恢复"
    sleep "$wait_sec"
}

# 主循环
while true; do
    if is_active; then
        echo "$(date '+%H:%M:%S') [RUN] 开始执行..."
        python -m jd_tracker --headless || echo "$(date '+%H:%M:%S') [ERR] 执行失败"
        echo "$(date '+%H:%M:%S') [WAIT] 等待 ${INTERVAL}s..."
        # 分段 sleep，每 60s 检查一次是否仍在活跃时段
        REMAINING=$INTERVAL
        while [ "$REMAINING" -gt 0 ] && is_active; do
            STEP=$((REMAINING > 60 ? 60 : REMAINING))
            sleep "$STEP"
            REMAINING=$((REMAINING - STEP))
        done
    else
        sleep_until_active
    fi
done

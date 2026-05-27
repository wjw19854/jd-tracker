#!/bin/bash
set -e

INTERVAL="${JD_TRACKER_INTERVAL:-${1:-1800}}"

echo "============================================"
echo " jd-tracker container started"
echo " Interval: ${INTERVAL}s ($(echo "scale=1; $INTERVAL/60" | bc)m)"
echo " Headless: $JD_TRACKER_HEADLESS"
echo " Chrome Channel: '${JD_TRACKER_CHROME_CHANNEL}'"
echo "============================================"

# 首次立即执行
echo "$(date '+%H:%M:%S') [RUN] 首次执行..."
python -m jd_tracker --headless || echo "$(date '+%H:%M:%S') [ERR] 执行失败，将在下一轮重试"

# 定时循环
while true; do
    echo "$(date '+%H:%M:%S') [WAIT] 等待 ${INTERVAL}s 后执行下一轮..."
    sleep "$INTERVAL" &
    wait $!
    echo "$(date '+%H:%M:%S') [RUN] 开始执行..."
    python -m jd_tracker --headless || echo "$(date '+%H:%M:%S') [ERR] 执行失败"
done

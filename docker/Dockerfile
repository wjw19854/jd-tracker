FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

WORKDIR /app

# 复制源代码
COPY src/ ./src/
COPY pyproject.toml ./

# Playwright 已预装在镜像中，仅安装额外依赖
RUN pip install --no-cache-dir playwright-stealth

ENV PYTHONPATH=/app/src
ENV JD_TRACKER_HEADLESS=true
ENV JD_TRACKER_CHROME_CHANNEL=""
ENV JD_TRACKER_DATA_DIR=/app/data
ENV JD_TRACKER_LOG_DIR=/app/logs

# 创建数据/日志目录
RUN mkdir -p /app/data /app/logs

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["1800"]

# Shelf-Life Copilot · 零配置自助试用镜像（包 A · Open Core 模式）
#
# 食品厂 IT 主管 5 分钟看到完整 demo 的路径：
#   docker compose up
#   curl http://localhost:8000/health        # 服务起
#   docker compose exec app make demo        # 离线渲染示例卡片
#
# 默认 LLM_PROVIDER=offline，不需要任何 API key。真实部署时把环境变量
# 替换为 anthropic / moonshot 即可切换。

FROM python:3.11-slim AS base

# uv 提供毫秒级安装，避免镜像构建时间被 pip 拖慢
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /app

# 先复制 lock 文件单独缓存层（项目代码改动时不会重装依赖）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# 再复制项目代码
COPY src ./src
COPY data ./data
COPY tools ./tools
COPY Makefile README.md ./
COPY docs ./docs

# 安装项目本身（editable）
RUN uv sync --frozen --no-dev

# 试用模式默认值——客户真用时通过 docker-compose env 覆盖
ENV LLM_PROVIDER=offline \
    APP_ENV=demo \
    LOG_LEVEL=INFO

EXPOSE 8000

# uvicorn 直接挂 src.main:app — FastAPI lifespan 自动起 Daily/Monthly scheduler
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

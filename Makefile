.DEFAULT_GOAL := help
.PHONY: help install dev test lint fmt check run scan demo clean

help: ## 显示所有命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## 仅安装运行依赖（生产）
	uv sync

dev: ## 安装运行 + 开发依赖，启用 pre-commit
	uv sync --all-groups
	uv run pre-commit install

test: ## 跑 pytest + coverage
	uv run pytest

lint: ## ruff check + ruff format --check + mypy
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src

fmt: ## ruff format + ruff --fix
	uv run ruff format .
	uv run ruff check --fix .

check: lint test ## 跑所有检查（等效 CI）

run: ## 启动 FastAPI dev server
	uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

scan: ## 跑一次扫描，用法 make scan CUSTOMER=customerA [TODAY=2026-05-26] [DRY=1]
	@uv run python -m src.cli \
		--customer $(CUSTOMER) \
		$(if $(TODAY),--today $(TODAY),) \
		$(if $(DRY),--dry-run,)

demo: ## 离线渲染 demo 卡片到 docs/demo_samples/ (彩排 + 兜底用)
	@uv run python tools/render_demo_cards.py

clean: ## 清理缓存与覆盖率产物
	find . -type d -name '__pycache__' -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov

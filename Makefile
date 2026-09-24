.DEFAULT_GOAL := help
.PHONY: help install dev test lint fmt check docs-check no-internal-leak run scan demo report validate-llm push monthly db-backup db-restore db-verify db-drill load-test clean

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

docs-check: ## 校验 Markdown 相对链接和文档中的 Make 命令
	uv run python tools/check_docs.py

no-internal-leak: ## 检查公开仓库内容边界
	uv run python tools/check_no_internal_leak.py

check: lint test docs-check no-internal-leak ## 跑所有检查（等效 CI）

run: ## 启动 FastAPI dev server
	uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

scan: ## 跑一次扫描，用法 make scan CUSTOMER=customerA [TODAY=2026-05-26] [DRY=1]
	@uv run python -m src.cli \
		--customer $(CUSTOMER) \
		$(if $(TODAY),--today $(TODAY),) \
		$(if $(DRY),--dry-run,)

demo: ## 离线渲染 demo 卡片到 docs/demo_samples/ (彩排 + 兜底用)
	@uv run python tools/render_demo_cards.py

report: ## 生成月度 PDF 报告 (用法 make report [SOURCE=mock|sqlite] [MONTH=2026-05] [DB=data/decisions.db])
	@uv run python tools/render_monthly_report.py \
		$(if $(SOURCE),--source $(SOURCE),) \
		$(if $(MONTH),--month $(MONTH),) \
		$(if $(DB),--db $(DB),)

validate-llm: ## 真实 LLM 5+ 场景合规率验证 (用法 PROVIDER=moonshot)
	@uv run python tools/validate_llm.py --provider $(or $(PROVIDER),anthropic)

monthly: ## 手动触发月度报告管线 (写 PDF; 加 PUSH=1 推送摘要卡到企微群)
	@uv run python tools/trigger_monthly_now.py $(if $(PUSH),--push,)

db-backup: ## 创建一致性 SQLite 备份（DB=... BACKUP=...）
	uv run python tools/sqlite_ops.py backup $(DB) $(BACKUP)

db-restore: ## 从备份恢复 SQLite（DB=... BACKUP=...）
	uv run python tools/sqlite_ops.py restore $(BACKUP) $(DB)

db-verify: ## 运行 SQLite 完整性检查（DB=...）
	uv run python tools/sqlite_ops.py verify $(DB)

db-drill: ## 在临时目录演练备份、删库和恢复
	uv run python tools/sqlite_ops.py drill

load-test: ## 验证 1000 租户任务持久性和入队 p99 SLO
	uv run python tools/load_test_queue.py --tasks 1000 --p99-ms 20

push: ## 真推卡片到企微群 (用法 make push CUSTOMER=customerA [TODAY=2026-05-26] [PROVIDER=moonshot]，需先 export WECOM_WEBHOOK_URL)
	@test -n "$$WECOM_WEBHOOK_URL" || (echo "ERROR: 先 export WECOM_WEBHOOK_URL=<群机器人 URL>"; exit 1)
	@uv run python -m src.cli \
		--customer $(CUSTOMER) \
		$(if $(TODAY),--today $(TODAY),) \
		--provider $(or $(PROVIDER),moonshot) \
		--push-webhook "$$WECOM_WEBHOOK_URL"

clean: ## 清理缓存与覆盖率产物
	find . -type d -name '__pycache__' -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov

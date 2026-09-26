# Operations Runbook

## SQLite 备份与恢复

运行服务使用 WAL 模式。备份必须通过 SQLite backup API 创建一致性快照，不能只复制主数据库文件而遗漏 `-wal`。

```bash
make db-backup DB=data/decisions.db BACKUP=backups/decisions-2026-09-24.db
make db-verify DB=backups/decisions-2026-09-24.db
```

恢复前停止应用并保留当前数据库：

```bash
make db-restore DB=data/decisions.db BACKUP=backups/decisions-2026-09-24.db
make db-verify DB=data/decisions.db
```

恢复命令会拒绝不存在或完整性检查失败的备份，并将现有数据库移动为带 UTC 时间戳的 `.before-restore-*` 文件，因此可以人工回退。

## 发布与 schema 回滚

1. 停止应用，创建并验证备份。
2. 部署新版本；启动迁移按版本逐个事务执行。
3. 检查 `/health`、`/metrics` 和启动日志。
4. 如需回滚，停止新版本，恢复发布前备份，再部署旧版本。

不要尝试用反向 DDL 降级 SQLite schema；数据和 schema 必须作为同一份快照恢复。

## 演练

在临时目录执行 `make db-drill`。该命令创建测试库、备份、删除工作副本、恢复并运行 `PRAGMA integrity_check`，不会触碰生产数据库。

## PostgreSQL 运行时

PostgreSQL 部署需先安装可选依赖，再显式选择后端：

```bash
uv sync --extra postgres
export PERSISTENCE_BACKEND=postgres
export POSTGRES_DSN='postgresql://user:password@db:5432/shelf_life'
export POSTGRES_POOL_MIN_SIZE=1
export POSTGRES_POOL_MAX_SIZE=10
```

应用启动时在一个连接上执行幂等 schema 初始化，然后由 FastAPI lifespan 统一管理连接池。选择 PostgreSQL 后，所有运行时持久化边界使用同一后端，不会静默写入 `DECISIONS_DB_PATH`。多实例部署必须让所有实例指向同一 PostgreSQL 数据库：幂等认领和 `rate_limit_windows` 计数器依赖该共享边界。SQLite 模式仅支持单节点限流，不应用于水平扩容。

`RATE_LIMIT_REQUESTS` 和 `RATE_LIMIT_WINDOW_SECONDS` 必须在所有实例保持一致。PostgreSQL 使用数据库事务时间划分窗口，通过原子 upsert 增加配额，并在同一语句中清理过期窗口。数据库不可用时受保护的 POST 接口返回 `503`，应就 `rate_limit_backend_failure_total` 增长和 PostgreSQL 可用性告警，不要临时切回进程内限流。

切换前必须单独备份现有 SQLite 库并完成数据导入验收；切换开关本身不会自动复制历史数据。回滚时停止应用、恢复切换前 SQLite 备份，再将 `PERSISTENCE_BACKEND` 改回 `sqlite`。

## OIDC、Prometheus 与 Trace

生产建议安装 `.[oidc,observability,postgres]`，设置 `AUTH_MODE=oidc` 及 issuer/audience/JWKS URL。OIDC 客户端必须在 `customer_ids` 声明发放租户列表，在 `roles` 声明发放 `viewer`、`operator` 或 `admin`。角色或租户拒绝会增加 `authorization_denied_total`，输出 `authorization.denied` 日志，并在当前持久化后端写入只追加审计事件；事件不保存 token、请求体或库存载荷。

`SECURITY_AUDIT_RETENTION_DAYS` 默认 365。应用启动时删除更早的 `security_audit_events`，因此数据库备份/归档周期必须短于该值；需延长在线调查窗口时应在所有实例统一调整。管理员可调用 `GET /api/security/audit-events?customer_id=...&start=...&end=...` 分页检索其获授权租户。审计写入故障不会放行请求，原拒绝仍返回 `403`；应对 `security_audit_persistence_failure_total` 告警并立即检查数据库。清理数量记录在 `security_audit_purged_total`。

Prometheus 应拉取每个实例的 `/metrics`；不要对该端点做单实例粘滞会话。设置 `OTEL_EXPORTER_OTLP_ENDPOINT` 后应用将 FastAPI span 导出到 OTLP/HTTP collector。反向代理必须保留 `traceparent` 请求头和响应头。

## SAP Business One

设置 `ERP_BACKEND=sap_b1`、`SAP_B1_BASE_URL` 和会话 Cookie。SAP 侧需先建立受审核的 `ShelfLifeBatches` SQLQuery，输出 `Batch`、`ItemCode`、`ItemDescription`、`ManufacturingDate`、`ExpirationDate`、`Quantity`、`UoM` 和 `WarehouseCode`，并接收 `customerId` 参数。推荐使用 `SAP_B1_SESSION_COOKIE_FILE`存放 `B1SESSION=...; ROUTEID=...`：密钥管理器以原子 rename 替换文件后，下一个 SAP 请求即使用新会话，无需重启。生产启用前仍须在厂商沙箱执行分页、429、5xx、超时和凭据轮换验收；当前公开仓库不包含该凭据。

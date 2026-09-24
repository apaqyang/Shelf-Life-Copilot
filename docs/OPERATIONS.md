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

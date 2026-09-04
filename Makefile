.PHONY: install test check demo agent-demo model-check dev ask chat db-check

# install: 安装运行及开发依赖；用法：make install
install:
	cd backend && uv sync --all-groups

# test: 运行完整测试并输出覆盖率；用法：make test
test:
	cd backend && uv run pytest --cov=ad_rca --cov-report=term-missing

# check: 检查 Ruff 格式、代码规范及 Pyright 类型；用法：make check
check:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright

# demo: 运行纯计算 Phase 1 固定数据示例；用法：make demo
demo:
	cd backend && uv run profitlens investigate ../fixtures/demo/pricing_error.json --format json

# agent-demo: 用本地固定数据和假模型运行 LangGraph；用法：make agent-demo
agent-demo:
	cd backend && uv run profitlens agent ../fixtures/demo/pricing_error.json --model fake --format json

# model-check: 检查 DeepSeek API Key 和模型连通性；用法：make model-check
model-check:
	cd backend && uv run profitlens model-check

# dev: 启动基于固定数据的 FastAPI 开发服务；用法：make dev
dev:
	cd backend && uv run profitlens serve

# ask: 用一句自然语言查询 MySQL 并分析利润；用法：make ask QUESTION='分析昨天利润为什么下降'
ask:
	cd backend && uv run profitlens ask "$(QUESTION)"

# chat: 启动可追问的终端对话；用法：make chat
chat:
	cd backend && uv run profitlens chat

# db-check: 仅执行固定 SELECT 1 检查两个 MySQL 数据源；用法：make db-check
db-check:
	cd backend && uv run profitlens db-check

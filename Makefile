.PHONY: install test check demo agent-demo model-check dev ask chat db-check \
	docker-build docker-chat docker-ask docker-db-check db-profile docker-db-profile test-mysql-live

DOCKER_IMAGE ?= profitlens:local
DOCKER_RUN = docker run --rm --network host --env-file .env \
	--user "$$(id -u):$$(id -g)" \
	-v "$(CURDIR)/backend/artifacts:/app/backend/artifacts"

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

# db-profile: 只读诊断 stat 最近7天的时间覆盖、粒度及空值；用法：make db-profile
db-profile:
	cd backend && uv run profitlens db-profile

# test-mysql-live: 使用本地 .env 连接 MySQL，仅 SELECT 合成派生表验证金额，不写表。
test-mysql-live:
	cd backend && PROFITLENS_LIVE_MYSQL=1 uv run pytest tests/test_mysql_live_reliability.py -q

# docker-build: 构建包含 Python 3.12 和生产依赖的镜像；用法：make docker-build
docker-build:
	docker build -t "$(DOCKER_IMAGE)" .

# docker-chat: 先按当前源码构建镜像，再启动交互对话；用法：make docker-chat
docker-chat: docker-build
	mkdir -p backend/artifacts
	$(DOCKER_RUN) -it "$(DOCKER_IMAGE)" chat

# docker-ask: 先构建镜像，再执行单次自然语言分析；用法：make docker-ask QUESTION='分析昨天利润下降原因'
docker-ask: docker-build
	mkdir -p backend/artifacts
	$(DOCKER_RUN) "$(DOCKER_IMAGE)" ask "$(QUESTION)"

# docker-db-check: 先构建镜像，再检查 DB20 和 DB40；用法：make docker-db-check
docker-db-check: docker-build
	mkdir -p backend/artifacts
	$(DOCKER_RUN) -it "$(DOCKER_IMAGE)" db-check

# docker-db-profile: 构建镜像后执行上述只读数据诊断；用法：make docker-db-profile
docker-db-profile: docker-build
	mkdir -p backend/artifacts
	$(DOCKER_RUN) -it "$(DOCKER_IMAGE)" db-profile

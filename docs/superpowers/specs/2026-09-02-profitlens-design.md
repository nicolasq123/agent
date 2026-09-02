# ProfitLens 设计规格

**状态：** 已批准

**日期：** 2026-09-02

**仓库名：** `ad-rca-agent`

**产品名：** ProfitLens

**定位：** Evidence-grounded advertising profit RCA agent

## 1. 目标

ProfitLens 是一个面向效果广告联盟的利润异常检测与根因调查 Agent。系统从只读广告数据中发现利润异常，将损失定位到具体业务维度，再使用受控的 LangGraph 工作流验证候选原因，输出带来源、计算过程、反证和置信度的诊断报告。

项目首先服务于 GitHub 作品集和求职展示。招聘者应能在五分钟内理解业务问题、运行方式、Agent 调查过程以及工程质量。

## 2. 核心原则

1. 数据库交互严格只读。应用不得执行任何数据库写入、DDL、锁定读取或文件导出语句。
2. 数值计算由确定性程序完成，LLM 不计算指标、不生成 SQL、不虚构证据。
3. 根因结论必须引用结构化 Evidence，并同时保留反证。
4. 系统允许输出证据不足，不为追求完整报告而过度声明因果。
5. 工作流有明确轮数、查询次数、并发数和超时预算。
6. 默认 Fixture 模式无需数据库和模型即可运行。
7. 领域算法与 LangGraph、API、数据库驱动隔离。

## 3. V1 业务边界

### 3.1 业务模型

系统模拟一个效果广告联盟：Advertiser 为有效转化支付 Revenue，平台向 Channel 支付 Payout。

```text
Advertiser
  -> Offer
    -> Channel
      -> Click / Conversion
```

核心经济指标：

```text
profit = revenue - payout
margin = profit / revenue
```

### 3.2 主流程

V1 负责异常检测和异常归因的完整闭环：

```text
只读数据 -> 统计异常检测 -> Incident -> Agent 调查 -> Evidence -> 报告与回放
```

异常检测由确定性统计程序负责。LLM 只参与调查优先级和报告表达。

### 3.3 核心维度

主归因维度为：

- `advertiser_id`
- `offer_id`
- `channel_id`
- `country`

`os`、`carrier`、`creative` 和 `sub_channel` 可存在于 Fixture 或源数据中，但不进入 V1 主组合搜索。

### 3.4 核心指标

- `clicks`
- `conversions`
- `approved_conversions`
- `revenue`
- `payout`
- `profit`
- `margin`
- `cvr`
- `approval_rate`
- `epc`
- `cost_per_click`

## 4. 异常检测

### 4.1 动态基线

对目标时间窗取过去八周相同星期和相同小时的数据，以中位数作为期望值，以 MAD 衡量波动：

```text
expected_profit = median(history_profit)
robust_z = 0.6745 * (actual_profit - expected_profit) / MAD
```

MAD 为零或历史不足时使用明确的 fallback 或输出 `INSUFFICIENT_HISTORY`，不得通过任意极小除数制造异常。

### 4.2 触发条件

`PROFIT_DROP` 同时满足：

- `robust_z <= -3`
- 相对利润下降至少 20%
- 绝对损失超过账户配置门槛
- 最近三个完整时间窗中至少两个命中
- 数据质量门禁通过

当历史期望利润接近零时，不使用相对下降率。实际持续亏损由 `NEGATIVE_PROFIT` 独立表达。

### 4.3 数据质量门禁

检测前检查：

- 时间窗完整性
- 数据延迟
- 最小点击和转化样本
- Revenue/Payout 缺失率
- 时区和币种一致性

数据不完整时输出 `DATA_QUALITY_BLOCKED`，不得将缺失数据解释为收入下降。

## 5. 损失归因

系统先扫描单维贡献，再对高贡献分支搜索二维和三维组合。只有解释总损失至少 10% 的分支才继续展开，最大组合深度为 3。

归因结果包括：

- 维度路径
- 实际值与基线值
- 绝对损失
- 总损失占比
- 可解释损失
- 未解释残差

归因算法区分：

- 数量效应：总流量变化
- 结构效应：流量在不同切片间迁移
- 效率效应：同类流量的收入或成本能力变化

程序必须校验各路径贡献之和与总损失一致，允许显式残差，不得静默吞掉差异。

## 6. 原因分类与证据

### 6.1 原因类型

V1 支持五类可验证原因：

1. 单价与利润结构变化
2. 流量数量或结构变化
3. 转化链路异常
4. Cap、预算与投放限制
5. 流量质量异常

对应的受控假设包括：

- `PAYOUT_PRICE_INCREASE`
- `REVENUE_PRICE_DECREASE`
- `TRAFFIC_VOLUME_DROP`
- `TRAFFIC_MIX_SHIFT`
- `CONVERSION_PATH_FAILURE`
- `CAP_REACHED`
- `TRAFFIC_QUALITY_DEGRADATION`

### 6.2 Verifier

每类原因由独立、确定性的 verifier 验证：

- `PricingVerifier`
- `TrafficMixVerifier`
- `ConversionPathVerifier`
- `CapVerifier`
- `TrafficQualityVerifier`

Verifier 返回假设状态、影响切片、解释损失、证据、反证和数据缺口，不返回无结构的分析文章。

### 6.3 结论等级

- `CONFIRMED`：存在直接事件证据、时间一致，并且重算可以解释主要损失。
- `LIKELY`：至少两个独立信号支持，没有明显反证。
- `INSUFFICIENT_EVIDENCE`：只有相关性、单一信号或存在冲突。
- `REJECTED`：关键数据与假设相反。

流量作弊等无法直接证明的判断默认最高为 `LIKELY`，除非数据中存在可靠的直接裁决记录。

### 6.4 Evidence 合同

每条 Evidence 至少包含：

- 唯一 ID
- 支持或反对的假设
- 强度和观测时间
- 数据来源与脱敏记录引用
- 事实陈述
- 使用的公式与参数
- 可解释损失

报告中的关键事实和结论必须引用 Evidence ID。LLM 不得创建不存在的 Evidence ID。

## 7. Agent 编排

### 7.1 选择方案

采用单个受控 LangGraph，不采用开放式 ReAct 循环和多 Agent 专家团队。

```text
START
  -> validate_data
  -> load_baseline
  -> attribute_loss
  -> generate_candidates
  -> plan_investigation
  -> run_verifiers_in_parallel
  -> aggregate_evidence
  -> evidence_guard
  -> optional_second_round
  -> compose_report
  -> END
```

### 7.2 调查限制

- 最大调查轮数：2
- 每轮最大 verifier 数：3
- 单次调查最大数据库查询数：20
- 单次查询最大返回行数：10,000
- 单次数据库查询超时：10 秒

程序首先生成不会遗漏明显线索的候选假设。LLM 只能从允许枚举中选择优先级和验证计划。存在强直接信号时，程序可以强制加入对应 verifier。

### 7.3 状态模型

LangGraph 顶层状态使用 `TypedDict` 和 reducer，状态内部数据使用 Pydantic v2 模型。并行 verifier 只能追加 Evidence 或 Error，不得互相覆盖结果。

Graph state 保存结构化摘要、查询条件、Evidence ID 和来源引用，不保存大批原始数据、连接对象、凭证或任意 SQL。

### 7.4 LLM 边界

LLM 可以：

- 对受控候选假设排序
- 选择允许的 verifier
- 在最多一轮补充调查中请求缺失证据
- 将结构化结论表达为业务报告
- 回答当前 Incident 范围内的追问

LLM 不可以：

- 生成或执行 SQL
- 直接读取数据库或文件系统
- 计算财务指标或损失
- 创建新根因类型
- 修改置信度规则
- 执行业务配置操作

模型通过 `InvestigationPlanner` 和 `ReportComposer` 协议隔离，支持 OpenAI-compatible 服务。测试使用 Fake 实现。

## 8. 技术架构

### 8.1 后端

- Python 3.12
- uv
- FastAPI
- LangGraph
- Pydantic v2
- Polars / NumPy
- clickhouse-connect
- SQLAlchemy 2 / asyncmy
- sqlglot（只读 SQL AST 校验）
- pytest
- pydantic-evals
- OpenTelemetry

### 8.2 前端

- React
- TypeScript
- Vite
- TanStack Query
- React Router
- Apache ECharts
- Tailwind CSS
- Vitest
- Playwright

### 8.3 模块边界

```text
backend/src/ad_rca/
  domain/          领域模型与合同
  detection/       基线、异常检测、数据质量
  rca/             贡献分解、候选生成、verifier
  workflow/        LangGraph 状态、节点与路由
  application/     用例服务
  infrastructure/  只读数据源、模型、遥测、本地产物
  api/             FastAPI 与 SSE
  evaluation/      场景执行与评分
```

依赖方向为 `API -> Application -> Domain/RCA`，Infrastructure 实现由 Application 使用的端口。`domain`、`detection` 和 `rca` 不得导入 LangGraph、FastAPI 或数据库驱动。

## 9. 数据源与严格只读约束

### 9.1 运行模式

`fixture` 模式读取仓库内不可变 Parquet/JSON 数据，不需要数据库。

`readonly_db` 模式读取：

- ClickHouse：小时广告指标、转化、Postback、质量信号
- MySQL：Advertiser、Offer、Channel、Pricing、Cap、Routing 和配置变更日志

### 9.2 禁止操作

代码、初始化流程、测试和文档示例中均不得提供数据库写操作。禁止：

- `INSERT`
- `UPDATE`
- `DELETE`
- `REPLACE`
- `CREATE`
- `ALTER`
- `DROP`
- `TRUNCATE`
- `RENAME`
- `MERGE`
- `GRANT` / `REVOKE`
- 多语句查询
- `SELECT ... INTO OUTFILE/DUMPFILE`
- `SELECT ... FOR UPDATE`
- 任意文件、URL 或远程表函数

数据库账号必须由用户在外部预先创建并仅具有指定表的 `SELECT` 权限。应用不负责建库、建表、迁移或灌数。

### 9.3 防御层

1. 数据库只读账号。
2. Repository 仅暴露语义化读取方法，不提供通用 `execute` 或原始连接。
3. 查询来自固定 QuerySpec；值使用绑定参数；表和列来自白名单。
4. SQL AST 在测试和运行时校验为单条只读查询。
5. 禁用 multi-statements，并在 ClickHouse 使用 readonly profile 和资源限制。
6. LLM 只接收聚合摘要，不接收 SQL、凭证和未脱敏原始记录。

### 9.4 本地运行状态

V1 使用 LangGraph 内存 checkpoint。本地普通文件保存已完成或进行中的演示产物：

```text
artifacts/<incident_id>/<run_id>/
  incident.json
  events.jsonl
  evidence.json
  report.json
```

数据库不会保存 Incident 或 Agent 状态。服务中断后，已完成运行可从文件回放；未完成运行从头执行。所有节点只读且幂等，因此重跑不会改变业务数据。

## 10. API 与用户体验

### 10.1 API

- `GET /api/incidents`
- `POST /api/detections/run`
- `GET /api/incidents/{incident_id}`
- `POST /api/incidents/{incident_id}/investigations`
- `GET /api/investigations/{run_id}/events`
- `GET /api/investigations/{run_id}/report`
- `POST /api/investigations/{run_id}/questions`

POST 端点只启动内存计算或生成本地文件，不写数据库。

### 10.2 调查工作台

产品不是空白聊天框。主界面包括：

- Incident 列表
- Actual / Expected / Loss 摘要
- 利润损失瀑布图
- 多维贡献路径
- Agent 调查时间线
- verifier 状态
- Evidence 与反证详情
- 根因、置信度、解释损失和行动建议
- 调查回放
- 当前 Incident 范围内的受限追问

SSE 事件包括：

- `baseline_loaded`
- `attribution_completed`
- `hypothesis_generated`
- `verifier_started`
- `evidence_found`
- `hypothesis_rejected`
- `root_cause_confirmed`
- `report_generated`

## 11. 合成数据与场景

仓库提供固定随机种子生成的不可变 Fixture，不向数据库灌数。数据包含八周正常历史、约 20 个 Advertiser、50 个 Offer、30 个 Channel、8 个 Country，以及必要的转化、Postback、质量和配置事件样本。

三个 UI 演示案例：

1. Payout 配置错误：直接配置变更证据，输出 `CONFIRMED`。
2. Cap 导致高利润流量迁移：Cap 与 mix-shift 共同解释损失，输出 `CONFIRMED`。
3. Channel 流量质量恶化：重复 IP、短 CTIT 和有效率下降，默认输出 `LIKELY`。

评测集约 20 个场景：

- 5 个正常波动
- 3 个数据质量问题
- 4 个价格或配置异常
- 3 个 Cap 或流量结构异常
- 3 个转化链路异常
- 2 个流量质量异常

Ground truth 记录预期 Incident、影响维度、根因、最高置信度和最低解释损失比例。展示场景与评测场景分离。

## 12. 错误处理

统一错误码：

- `SOURCE_UNAVAILABLE`
- `QUERY_TIMEOUT`
- `DATA_INCOMPLETE`
- `INSUFFICIENT_HISTORY`
- `QUERY_BUDGET_EXCEEDED`
- `VERIFIER_FAILED`
- `LLM_UNAVAILABLE`
- `INVALID_LLM_OUTPUT`
- `EVIDENCE_CONFLICT`

核心基线查询失败时终止调查。辅助 verifier 失败时标记 `UNKNOWN`，其他分支继续。只读查询对瞬时错误最多重试一次。

LLM 结构校验失败最多修复一次；仍失败时使用程序候选顺序和模板报告完成降级运行。降级报告标记 `generated_without_llm`。

运行最终状态仅包括：

- `COMPLETED`
- `COMPLETED_WITH_WARNINGS`
- `INSUFFICIENT_EVIDENCE`
- `DATA_QUALITY_BLOCKED`
- `FAILED`

## 13. 测试与验收

测试包括：

1. 领域算法单元测试
2. Verifier 合同测试
3. LangGraph 工作流测试
4. 只读 SQL 与 Repository 安全测试
5. 带 Ground truth 的场景评测
6. React 组件测试与 Playwright 关键路径

V1 目标：

| 指标 | 目标 |
|---|---:|
| 正常场景误报 | 0 |
| 异常检测召回率 | >= 90% |
| 正确根因 Top-1 | >= 80% |
| 正确根因 Top-3 | >= 95% |
| 正确维度路径召回率 | >= 90% |
| 损失解释误差 | <= 10% |
| 关键结论 Evidence 引用率 | 100% |
| 无直接证据却输出 CONFIRMED | 0 |
| 非法数据库语句 | 0 |

Fixture 模式性能目标：RCA 纯计算 P95 小于 3 秒，不含模型的完整 Graph P95 小于 5 秒，含远程模型的完整调查目标小于 30 秒。

CI 使用 Fake LLM，不依赖网络或 API Key。真实模型评测通过手动 workflow 执行。

## 14. 交付与展示

`make demo` 启动 Fixture 模式，不需要数据库和模型。`make dev` 可以在显式配置后使用真实模型或只读数据库。

README 顺序：

1. 30 秒演示 GIF
2. 业务问题和最终结果
3. 三个核心能力
4. 架构图
5. 一键启动
6. 三个案例
7. 评测结果
8. 数据库只读设计
9. 技术细节
10. 已知限制

## 15. 非目标

V1 不实现：

- 通用 Text-to-SQL
- 数据库或业务配置写入
- 自动暂停 Channel 或 Offer
- 多 Agent 系统
- 开放式无限 ReAct 循环
- 多租户、登录和权限管理
- 工作流拖拽编辑器
- 模型训练
- 严格因果推断
- 大规模生产部署
- 移动端适配

## 16. 成功标准

项目完成时应满足：

1. 新用户能够在无数据库、无模型密钥的环境运行三个案例。
2. 主演示在五分钟内说明异常、归因、证据、结论和建议。
3. 相同 Fixture 和 Fake LLM 产生可复现结果。
4. 任何关键结论均可追踪到 Evidence 和确定性计算。
5. 代码库中不存在数据库写入口或危险 SQL。
6. 自动化测试和合成场景评测达到本规格目标。
7. 核心 RCA 模块可以脱离 LangGraph 单独使用和测试。

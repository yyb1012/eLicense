# LangGraph 项目实施与多角色子图 Harness 合并文档

## 1. 文档定位

本文件是后续开发唯一基线文档。  
整合以下两份稿件并补充定时巡检模块：
- `LangGraph项目实施文档.md`
- `LangGraph单编排多角色子图_Harness设计稿.md`

适用范围：几千用户规模、单系统部署、以企业审查/核验流程为主。

## 2. 目标与边界

### 2.1 目标

1. 以 LangGraph 实现“单编排 + 多角色子图”Agent 系统
2. 支持混合检索（FTS + Vector）
3. 支持记忆分层、工具调用、质量门禁、结果回写
4. 引入 Harness 工程体系，实现可评测、可回放、可发布门禁
5. 引入定时巡检模块，实现稳定性运营闭环

### 2.2 非目标

1. 不做分布式多 Agent 首发版本
2. 不做重 DDD 全套战术建模
3. 不做复杂前端平台，先以 API 为中心

## 3. 技术选型（统一版）

### 3.1 语言与框架

- 语言：Python 3.11+
- 编排：LangGraph
- API：FastAPI

### 3.2 存储与检索

- PostgreSQL（主库）：
- 业务持久化
- 审计日志
- 全文检索（FTS）
- 向量检索（pgvector）
- Redis（短期记忆和缓存）
- 对象存储（证件图片原件，不入库大字段）

### 3.3 可观测与任务调度

- OpenTelemetry + JSON 日志
- 可选 LangSmith（调试/追踪）
- 定时任务：APScheduler 或 Celery Beat

## 4. 轻量分层原则（非重 DDD）

保留职责边界，不追求概念复杂化。

- `domain`：业务规则、状态枚举、硬约束
- `application`：用例编排、事务边界、重试补偿
- `agent`：graph、prompt、memory、tool 绑定
- `infrastructure`：数据库、缓存、向量、MCP/外部系统
- `interfaces`：HTTP API、后台任务入口
- `harness`：评测、回放、发布门禁
- `ops`：巡检与告警

## 5. 项目目录（最终建议）

```text
project/
  src/
    interfaces/
      api/
        main.py
        routes_chat.py
        routes_ops.py
    application/
      services/
        chat_service.py
        workflow_service.py
        inspection_service.py
      dto/
    domain/
      models/
      rules/
      enums/
    agent/
      graph/
        state.py
        builder.py
        subgraphs/
          planner_subgraph.py
          evidence_subgraph.py
          analysis_subgraph.py
          decision_subgraph.py
          quality_gate_subgraph.py
          writeback_subgraph.py
          audit_subgraph.py
        nodes/
      prompts/
      memory/
      tools/
    infrastructure/
      db/
        postgres_repo.py
        redis_repo.py
      vector/
        hybrid_retriever.py
      llm/
      mcp/
    ops/
      scheduler/
        jobs.py
      inspection/
        rule_checker.py
        agent_inspector.py
        alert_dispatcher.py
    shared/
      config.py
      logger.py
      tracing.py
  harness/
    scenarios/
    replay/
    eval/
    fault/
    gates/
  scripts/
  docs/
  .env.example
  requirements.txt
```

## 6. LangGraph 架构（单编排多角色子图）

### 6.1 顶层编排图

```text
START
  -> ContextBootstrap
  -> PlannerSubgraph
  -> EvidenceSubgraph
  -> AnalysisSubgraph
  -> DecisionSubgraph
  -> QualityGateSubgraph
  -> (pass) WriteBackSubgraph -> AuditSubgraph -> END
  -> (degrade/reject/human_review) AuditSubgraph -> END
```

### 6.2 子图职责

1. `PlannerSubgraph`
- 意图分类
- 执行计划生成与校验

2. `EvidenceSubgraph`
- 工具查询
- 混合检索
- 证据融合

3. `AnalysisSubgraph`
- 规章合规校验（PolicyChecker）
- 风险评估（RiskAssessor）

4. `DecisionSubgraph`
- 草案生成
- 一轮自我反思
- 定稿输出

5. `QualityGateSubgraph`
- 一致性
- 完整性
- 置信门禁与路由

6. `WriteBackSubgraph`
- 幂等校验
- 副作用写回
- 补偿处理

7. `AuditSubgraph`
- 轨迹组装
- 指标上报
- 日志落库

## 7. GraphState 统一契约

```python
from typing import TypedDict, Dict, Any, List

class GraphState(TypedDict, total=False):
    trace_id: str
    session_id: str
    work_order_id: str
    user_input: str

    intent: str
    plan: Dict[str, Any]

    tool_results: List[Dict[str, Any]]
    rag_hits_vector: List[Dict[str, Any]]
    rag_hits_fts: List[Dict[str, Any]]
    evidence_bundle: List[Dict[str, Any]]

    policy_report: Dict[str, Any]
    risk_report: Dict[str, Any]

    decision_draft: Dict[str, Any]
    decision_final: Dict[str, Any]
    self_critic_report: Dict[str, Any]

    quality_report: Dict[str, Any]
    route: str  # pass/degrade/reject/human_review

    writeback_result: Dict[str, Any]
    answer_text: str
    errors: List[str]
```

契约规则：
1. 节点只能写自己负责字段
2. 关键结论必须包含 `evidence_refs`
3. `route` 仅由质量门禁子图产出

## 8. Memory 分层设计

### 8.1 Redis（短期）

- 最近 8~12 轮消息
- 最近工具结果摘要
- 当前轮临时状态
- TTL：24~72h

### 8.2 PostgreSQL（长期）

- 原始 user/assistant 消息
- 结构化摘要（task_state/risk_flags/pending_actions）
- 决策记录、审计记录、版本信息

### 8.3 摘要压缩触发

- 轮次阈值超限
- token 预算接近上限

压缩字段：
- `confirmed_facts`
- `risk_flags`
- `missing_materials`
- `completed_steps`
- `pending_actions`
- `evidence_refs`
- `last_decision`

## 9. 混合检索设计

### 9.1 数据模型建议

同表存文本和向量：
- `content`（text）
- `embedding`（vector）
- `metadata`（jsonb）

### 9.2 索引

- FTS：`GIN(to_tsvector(...))`
- Vector：`HNSW/IVFFLAT`（pgvector）

### 9.3 在线流程

1. 业务过滤（license_type/current_node/effective_date）
2. 并行召回：
- FTS topK
- Vector topK
3. RRF 融合
4. 重排
5. 输出 `evidence_bundle`

建议参数：
- `topK_fts=8`
- `topK_vector=8`
- `final_topN=6`

## 10. 工具与 MCP 规范

### 10.1 工具分级

- 查询工具：幂等、可重试
- 副作用工具：必须幂等键 + 重试上限 + 补偿策略

### 10.2 返回结构统一

```json
{
  "ok": true,
  "code": "SUCCESS",
  "message": "done",
  "data": {},
  "trace_id": "xxx"
}
```

### 10.3 超时与重试

- 超时：3~8s（按 SLA 调整）
- 重试：指数退避，最多 2~3 次
- 持续失败：降级或转人工

## 11. 新增模块：定时巡检（Ops Inspection）

### 11.1 定位

定时巡检是独立运维子系统，不进入用户主链路。  
采用“两层机制”：
1. 规则巡检（硬阈值）
2. Agent 巡检（归因与建议）

### 11.2 巡检流程

```text
Scheduler Trigger
  -> MetricsCollector
  -> RuleChecker
  -> (normal) SummaryStore
  -> (abnormal) AgentInspector
  -> ActionPlanner
  -> AlertDispatcher
  -> IncidentStore
```

### 11.3 巡检指标

- 请求错误率
- P95/P99 延迟
- 工具失败率
- 空召回率
- 写回失败率
- 补偿触发次数
- 人工复核比例

### 11.4 调度频率建议

- 快速巡检：每 5 分钟
- 深度巡检：每 1 小时
- 日报汇总：每天 1 次

### 11.5 Agent 巡检输出

- `possible_causes`
- `impact_scope`
- `recommended_actions`
- `confidence`

限制：
- 不允许自动执行高风险修复动作
- 高风险动作必须人工确认

## 12. Harness 工程体系

### 12.1 组成

1. Scenario Harness：结构化样例回归
2. Replay Harness：trace_id 重放
3. Eval Harness：批量评测
4. Fault Harness：故障注入
5. Release Gate：发布门禁

### 12.2 样例格式（示例）

```yaml
id: CASE-001
name: 基础证照核验通过
input:
  session_id: S-001
  work_order_id: WO-001
  message: 请审核该营业执照
context:
  license_type: 营业执照
expectations:
  route: pass
  must_include_evidence_refs: true
  max_latency_ms: 5000
```

### 12.3 发布门禁指标

- 决策准确率 >= 0.90
- 证据一致性 >= 0.95
- 拒答合理性 >= 0.90
- P95 时延 <= 6s
- 降级成功率 >= 0.98

## 13. API 合同（MVP）

### 13.1 用户接口

1. `POST /api/v1/chat`
- 入参：`session_id/work_order_id/message/user_id`
- 出参：`answer/decision/risk_level/next_action/trace_id`

2. `GET /api/v1/sessions/{session_id}/summary`
- 返回结构化摘要

### 13.2 运维接口

1. `POST /api/v1/ops/inspection/run`
- 手动触发一次巡检

2. `GET /api/v1/ops/inspection/reports`
- 获取巡检报告列表

3. `GET /api/v1/ops/incidents`
- 获取异常事件记录

## 14. 配置项

`.env.example` 至少包含：
- `MODEL_PROVIDER`
- `MODEL_NAME`
- `MODEL_API_KEY`
- `POSTGRES_DSN`
- `REDIS_URL`
- `OBJECT_STORAGE_ENDPOINT`
- `LOG_LEVEL`
- `FEATURE_ENABLE_WRITEBACK`
- `FEATURE_ENABLE_INSPECTION_AGENT`

## 15. 测试与验证

### 15.1 单元测试

- 业务规则、路由决策、幂等校验覆盖关键分支

### 15.2 集成测试

- 主链路成功
- 工具失败降级
- 检索空结果
- 写回补偿
- 巡检告警触发

### 15.3 离线评测

- 50~200 条样例
- 每次 Prompt 或策略变更必须重跑评测

## 16. 里程碑（4 周）

1. 第 1 周：脚手架 + 顶层图 + 基础 API
2. 第 2 周：混合检索 + Evidence/Analysis 子图
3. 第 3 周：Decision/Quality/WriteBack 子图 + 幂等补偿
4. 第 4 周：Harness + 定时巡检 + 灰度发布

## 17. 实施硬约束

1. 禁止仅靠 Prompt 承载核心业务规则
2. 无证据不出确定性结论
3. 副作用节点必须幂等
4. 每次执行必须可追踪、可回放
5. 定时巡检与用户主链路隔离

## 18. 第一版交付清单

1. 可运行 `POST /api/v1/chat`
2. 单编排多角色子图主链路
3. PostgreSQL + pgvector + Redis 接入
4. 混合检索可用
5. Harness 最小闭环（scenario + eval + gate）
6. 定时巡检模块（规则巡检必做，Agent 巡检可灰度）
7. 基线评测报告与运维 runbook


## 19. 检索增强规范（HNSW + 混合检索 + 重排精排）

本项目检索阶段统一采用三段式：`召回 -> 融合 -> 重排`。

### 19.1 检索流水线

1. `Hard Filter`（先过滤）
- 按 `license_type/current_node/effective_date/risk_tag` 做结构化过滤。

2. `Hybrid Recall`（并行召回）
- 路1：PostgreSQL FTS（关键词/BM25）
- 路2：pgvector HNSW（语义召回）

3. `Fusion`（融合）
- 使用 RRF（Reciprocal Rank Fusion）融合两路候选。

4. `Rerank`（精排）
- 对融合候选做重排（cross-encoder 或外部 reranker API）。

5. `Context Packing`
- 选择最终 TopN 证据片段进入模型上下文。
- 所有结论必须带 `evidence_refs`。

### 19.2 HNSW 参数基线

建议初始参数：
- `m = 16`
- `ef_construction = 200`
- `ef_search = 100`（可在 80~120 之间调优）

参数调优原则：
- 召回不足：先提高 `ef_search`
- 内存压力大：适度降低 `m`
- 写入构建慢：降低 `ef_construction`

### 19.3 召回与精排参数基线

- `topK_fts = 50`
- `topK_vector = 50`
- `topN_after_rrf = 80`
- `topN_final = 8~12`

RRF 建议公式：
- `score = Σ 1 / (k + rank_i)`，其中 `k` 取 60。

### 19.4 精排策略

可选方案：
1. 本地重排模型（如 `bge-reranker`）
2. 托管重排 API（如 Cohere Rerank 或同类服务）

精排输入：
- query
- 候选 chunk（content + metadata）

精排输出：
- `rerank_score`
- `final_rank`
- `selected_for_context`（bool）

### 19.5 检索质量验收指标（加入 Harness Gate）

- `Recall@20 >= 0.90`（离线标注集）
- `MRR@10 >= 0.75`
- `NDCG@10 >= 0.80`
- 空召回率低于阈值（建议 < 3%）
- 平均检索耗时满足 SLA

### 19.6 失败降级

- 向量召回失败：仅走 FTS + 精排
- FTS 失败：仅走向量 + 精排
- 双路失败：返回 `human_review` 并记录告警事件

## 20. 证件上传与 OCR 规范（PaddleOCR）

用户需要上传证件照，OCR 方案固定为 `PaddleOCR`，并纳入主流程证据体系。

### 20.1 模块定位

- OCR 属于 `EvidenceSubgraph` 的上游数据生产模块。
- 上传文件存对象存储；数据库只保存索引信息、OCR 结果与引用关系。

### 20.2 数据流

1. 用户上传证件图片/PDF
2. 文件写入对象存储（返回 `file_url`）
3. `PaddleOCR` 执行文本识别
4. 抽取结构化字段（证件号、姓名、有效期、发证机关等）
5. 结果写入 PostgreSQL（`document_assets`/`ocr_results`）
6. OCR 文本进入检索索引（FTS + 向量）
7. EvidenceSubgraph 在检索时可直接召回 OCR 证据

### 20.3 建议表结构（逻辑）

1. `document_assets`
- `id`
- `work_order_id`
- `file_url`
- `file_type`
- `uploaded_at`

2. `ocr_results`
- `id`
- `asset_id`
- `raw_text`
- `structured_fields` (jsonb)
- `avg_confidence`
- `ocr_model_version`
- `created_at`

3. `doc_chunks`（复用检索表）
- 增加 `source_type = ocr`
- 增加 `asset_id`

### 20.4 接口补充

1. `POST /api/v1/documents/upload`
- 入参：`session_id/work_order_id/file`
- 出参：`asset_id/file_url/ocr_status`

2. `GET /api/v1/documents/{asset_id}/ocr`
- 返回 OCR 原文、结构化字段、置信度

### 20.5 质量门禁

- OCR 平均置信度低于阈值（如 0.75）时：
- 不直接作为确定性结论依据
- 路由到 `human_review`
- 关键字段缺失时：
- 标记 `missing_materials`
- 进入补件或人工复核

### 20.6 可观测与巡检指标新增

- OCR 平均耗时
- OCR 失败率
- 低置信度占比
- OCR 证据被采纳率

上述指标需纳入定时巡检规则与日报。

# LangGraph 项目施工文档（软件工程 + Vibe Coding）

## 1. 文档目的

把架构设计稿转成可执行施工计划，确保项目按阶段推进、每个节点可验收、可回滚、可持续迭代。  
本文件是工程推进手册，与架构基线文档配套使用。

## 2. 关联基线

基线文档：`LangGraph项目实施与多角色子图_Harness合并文档.md`

本施工文档只做三件事：
1. 拆节点
2. 定验收
3. 控风险

## 3. 项目组织与职责

建议最小角色配置（3~5 人）：

1. `PM/PO`
- 管理需求优先级、业务验收、上线窗口

2. `Tech Lead`
- 维护技术基线、架构一致性、质量门禁

3. `Agent Engineer`
- 开发 LangGraph 子图、Prompt、Tool 绑定

4. `Platform Engineer`
- 负责 PostgreSQL/Redis/部署、可观测与巡检

5. `QA/Eval Owner`（可兼职）
- 维护 Harness 用例、指标、回归报告

职责边界规则：  
业务规则归 `domain`，流程路由归 `graph`，副作用归 `application/infrastructure`。

## 4. 生命周期与里程碑

采用 5 阶段推进，每阶段有进入条件、退出条件和交付物。

### 阶段 P0：立项与基线冻结（2~3 天）

进入条件：
- 需求范围已明确
- 合并基线文档已确认

施工任务：
1. 冻结 MVP 范围（只做一条主业务流）
2. 冻结技术栈（Python + LangGraph + PostgreSQL + Redis）
3. 建立项目目录与编码规范

交付物：
- `README`、目录脚手架、`.env.example`
- 任务看板（Backlog）

退出条件：
- 可以启动编码，且无关键技术分歧

### 阶段 P1：骨架搭建（3~5 天）

进入条件：
- P0 完成

施工任务：
1. 建立 FastAPI 服务与健康检查接口
2. 建立 GraphState 与顶层 Orchestrator 空图
3. 打通 PostgreSQL/Redis 基础连接
4. 接入结构化日志与 `trace_id`

交付物：
- 可启动服务
- `POST /api/v1/chat` 空流程可调用

退出条件：
- 单测可跑
- 主链路可返回占位响应

### 阶段 P2：核心能力施工（5~8 天）

进入条件：
- P1 完成

施工任务：
1. 完成 `Planner/Evidence/Analysis` 子图
2. 实现混合检索（FTS + pgvector + RRF）
3. 完成 Tool Registry 与查询工具接入
4. 完成 Memory 分层读写与摘要压缩触发

交付物：
- 能输出带 `evidence_refs` 的决策草案
- 检索可观测指标（召回数、耗时）可见

退出条件：
- 50 条样例中，流程成功率达到预设阈值

### 阶段 P3：质量闭环施工（4~6 天）

进入条件：
- P2 完成

施工任务：
1. 完成 `Decision/QualityGate` 子图
2. 实现置信门禁（pass/degrade/reject/human_review）
3. 完成 `WriteBack` 幂等与补偿
4. 完成 `Audit` 子图落日志

交付物：
- 全链路可执行（含写回开关）
- 失败可降级，且可追溯

退出条件：
- 故障注入场景通过率达标
- 发布门禁指标可产出

### 阶段 P4：Harness 与巡检上线（4~6 天）

进入条件：
- P3 完成

施工任务：
1. 完成 Scenario/Replay/Eval/Fault/Release Gate
2. 实现定时巡检（规则巡检）
3. 实现 Agent 巡检（异常归因建议）
4. 建立日报、告警、事件台账

交付物：
- 首版评测报告
- 巡检报告与异常告警链路

退出条件：
- 灰度发布门禁通过
- 值班手册可执行

## 5. WBS 施工节点（可直接建看板）

建议节点编码：`N00 ~ N16`，并新增 OCR 节点 `N07A`。

1. `N00` 基线冻结与任务拆解
2. `N01` 工程脚手架与配置管理
3. `N02` API 骨架与健康检查
4. `N03` GraphState 与 Orchestrator 骨架
5. `N04` PostgreSQL/Redis 适配层
6. `N05` Planner 子图
7. `N06` Evidence 子图与混合检索
8. `N07` Analysis 子图
9. `N07A` 证件上传与 OCR 入链（PaddleOCR）
10. `N08` Decision 子图（含 Self-Critic）
11. `N09` QualityGate 子图
12. `N10` WriteBack 子图（幂等 + 补偿）
13. `N11` Audit 子图（日志/指标）
14. `N12` Harness Scenario + Eval
15. `N13` Harness Replay + Fault
16. `N14` 定时巡检（规则巡检）
17. `N15` 异常归因 Agent 巡检
18. `N16` 灰度发布与回滚演练

每个节点必须带 4 项信息：
1. 输入依赖
2. 代码产物
3. 测试用例
4. 验收标准

## 6. Vibe Coding 执行协议

目标：用高频小步快跑提升效率，同时不牺牲工程质量。

### 6.1 单次 Vibe Loop（60~120 分钟）

1. `Define`
- 定义一个最小目标（只做一个节点或一个接口）

2. `Context Pack`
- 准备当前文件、约束、验收标准、已有实现

3. `Generate`
- 让模型生成实现草稿

4. `Constrain`
- 立刻加约束：边界、幂等、日志、异常处理、测试

5. `Verify`
- 跑单测/集成测试/样例回放

6. `Record`
- 更新变更记录与看板状态

规则：
1. 每次 Loop 只改一类问题（功能/重构/测试三选一）
2. 未通过测试不进入下一 Loop
3. 未通过 Gate 不允许并入主干

## 7. 质量门禁（Gate）

Gate-1（开发完成）：
1. 单测通过
2. 静态检查通过
3. 接口契约未破坏

Gate-2（集成完成）：
1. 主链路可跑通
2. 关键异常路径可降级

Gate-3（发布前）：
1. Eval 指标达标
2. 巡检规则正常触发
3. 回滚演练通过

## 8. 度量指标（项目级）

开发效率：
1. 节点准时完成率
2. 平均 Loop 周期时长

工程质量：
1. 缺陷逃逸率
2. 回归失败率
3. 测试覆盖率（关键模块）

Agent 质量：
1. 决策准确率
2. 证据一致性
3. 拒答合理性
4. P95 延迟与 token 成本

运维稳定性：
1. 巡检发现率
2. 告警误报率
3. 事件平均恢复时长（MTTR）

## 9. 风险台账（首版）

1. `R1` Prompt 漂移导致结论不稳定  
应对：Prompt 版本化 + Eval 回归门禁

2. `R2` 检索质量波动  
应对：RRF 参数固定 + 周期性重评估

3. `R3` 写回副作用重复执行  
应对：幂等键 + 补偿 + 失败告警

4. `R4` Vibe Coding 变更失控  
应对：小步提交 + 每 Loop 验收 + 节点边界控制

5. `R5` 线上异常定位困难  
应对：`trace_id` 全链路 + Replay Harness

## 10. 发布与回滚策略

发布策略：
1. 先灰度（5% -> 20% -> 50% -> 100%）
2. 关键指标连续稳定后放量

回滚触发条件：
1. 决策准确率跌破阈值
2. 写回失败率超阈值
3. 巡检连续告警

回滚动作：
1. 关闭写回开关
2. 回退到上一个稳定版本
3. 启动事件复盘

## 11. 施工产物清单（必须落库/落文档）

1. 架构与接口文档
2. 节点任务看板与状态
3. 每日变更记录（含风险与阻塞）
4. 每周评测报告
5. 巡检日报与事件台账
6. 上线/回滚操作手册

## 12. 首两周执行模板（建议）

第 1 周目标：完成 `P0 + P1`。  
第 2 周目标：`P2` 完成 70%（到 `N07`）。

每日节奏（参考）：
1. 09:30 站会：昨日结果、今日节点、阻塞项
2. 10:00-12:00 Vibe Loop 1
3. 14:00-16:00 Vibe Loop 2
4. 16:30 回归与记录
5. 18:00 更新看板与风险台账

## 13. Definition of Done（DoD）

一个节点完成必须同时满足：
1. 功能实现完成
2. 单测与集成测试通过
3. 日志与监控埋点齐全
4. Harness 至少有 1 条对应样例
5. 文档更新完成
6. 可被下一节点直接复用

## 14. N06 检索施工细则（HNSW + 混合检索 + 精排）

### 14.1 施工范围

1. 并行双路召回
- PostgreSQL FTS 召回
- pgvector HNSW 召回

2. RRF 融合
- 统一候选池并去重

3. 重排精排
- 对融合候选做 rerank
- 输出最终上下文候选

### 14.2 推荐初始参数

- HNSW：`m=16`, `ef_construction=200`, `ef_search=100`
- 召回：`topK_fts=50`, `topK_vector=50`
- 融合后：`topN_after_rrf=80`
- 最终：`topN_final=8~12`

### 14.3 代码产物清单

- `src/infrastructure/vector/hybrid_retriever.py`
- `src/infrastructure/vector/rrf_fuser.py`
- `src/infrastructure/vector/reranker.py`
- `tests/unit/test_hybrid_retriever.py`
- `tests/integration/test_retrieval_pipeline.py`

### 14.4 N06 验收标准

1. 功能验收
- 双路召回可并行执行
- 融合与精排结果可复现

2. 质量验收
- `Recall@20 >= 0.90`
- 空召回率低于阈值

3. 稳定性验收
- 单路失败可降级
- 双路失败进入 `human_review`

4. 可观测验收
- 日志包含：召回数、融合前后数量、重排耗时、最终入上下文条数

## 15. OCR 模块施工细则（PaddleOCR）

用户会上传证件照，本项目 OCR 方案固定为 `PaddleOCR`。

### 15.1 施工范围

1. 上传链路
- 新增证件上传接口（图片/PDF）
- 文件落对象存储，数据库只存元数据与 URL

2. OCR 抽取链路
- `PaddleOCR` 提取文本与版面信息
- 输出结构化字段（姓名、证件号、有效期、发证机关等）

3. 质量校验链路
- OCR 置信度阈值校验
- 低置信度进入 `human_review`

4. 检索融合链路
- OCR 文本入检索索引（FTS + 向量）
- 作为 `EvidenceSubgraph` 的证据来源之一

### 15.2 建议代码产物

- `src/infrastructure/ocr/paddle_ocr_service.py`
- `src/application/services/document_ingest_service.py`
- `src/interfaces/api/routes_upload.py`
- `src/domain/rules/ocr_quality_rules.py`
- `tests/unit/test_paddle_ocr_service.py`
- `tests/integration/test_upload_ocr_pipeline.py`

### 15.3 验收标准

1. 功能验收
- 上传后可拿到 OCR 结构化结果
- OCR 文本可进入检索

2. 质量验收
- 关键字段抽取准确率达到预设阈值
- 低置信度样例可正确转人工

3. 稳定性验收
- 大图/模糊图失败可降级，不阻断主流程

4. 可观测验收
- 日志包含：OCR 耗时、字段置信度、失败原因

## 16. 编码执行时文档主从关系

为了避免开发过程中标准漂移，按以下规则执行：

1. 主文档（唯一事实来源）  
`LangGraph项目实施与多角色子图_Harness合并文档.md`

2. 辅文档（施工推进与验收）  
`LangGraph项目施工文档_软件工程_vibe版.md`

3. 使用方式  
- 编码前：先看主文档确认“做什么”  
- 编码中：按施工文档对应节点确认“怎么做、怎么验收”  
- 冲突处理：一律以主文档为准，随后同步更新施工文档

---

执行建议：  
优先完成 `N00~N04` 骨架，再进入高价值节点 `N06/N07A/N09/N10/N12/N14`。这些节点决定系统是否可用。

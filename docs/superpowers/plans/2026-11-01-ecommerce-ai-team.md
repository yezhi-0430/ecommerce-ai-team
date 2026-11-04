# 电商 AI 团队 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 以真实模型运行可追溯的四群电商协作演示。
**Architecture:** 本地 Web 工作台连接单一后端；后端持久化阶段、事件、版本和成果，以服务端调用 OpenRouter。任务编排与模型适配、页面分离。
**Tech Stack:** Python 3.11+, FastAPI, SQLite, React + TypeScript + Vite, pytest, Vitest；具体依赖版本实现时锁定。
**Spec:** docs/superpowers/specs/2026-11-01-ecommerce-ai-team-design.md

## Global Constraints
- 虚构商品、客户和询盘明确标记；不接入真实店铺或发送消息。
- 图片默认 OpenRouter GPT Image 2；模型 ID 可配置，实际接口和价格实现时核验。
- 密钥服务端环境变量读取，禁止提交；讨论最多两轮，生图数量可配置且默认一张。
- 决策不预设结果；失败不静默跳过，备用图片需主动选择并标记。

## Review Focus
- 缺失密钥：任务明确失败并可配置后重试（任务 2）。
- 不支持的模型或超时：阶段保持失败状态并保留原因（任务 2、3）。
- Lead 维持原方案：原版本继续传递，不伪造变化（任务 3）。
- 上游修订：旧成果标记过期，不被误认为最新（任务 1、3）。
- 图片或文案缺少事实依据：质检标记待人工复核（任务 4）。

## 文件结构
- `backend/app/models.py`：商品、版本、事件、阶段和成果类型。
- `backend/app/store.py`：SQLite 存取和过期标记。
- `backend/app/providers.py`：OpenRouter 文本和图像适配。
- `backend/app/workflow.py`：讨论、Lead 决策和交接状态机。
- `backend/app/quality.py`：事实与成果检查。
- `backend/app/main.py`：任务、事件、成果和重试 API。
- `backend/tests/`：状态机、提供商和质检测试。
- `frontend/src/`：群聊、进度、决策及成果界面；`frontend/src/*.test.tsx` 负责交互验证。
- `examples/`：虚构商品与标明来源的示例素材；`README.md` 和 `.env.example`：运行与配置。

### Task 1: 数据及版本
- [ ] 创建商品事实、任务单、事件、成果和阶段模型，记录稳定 ID、版本与来源。
- [ ] 编写 pytest：新版本使依赖旧版的成果过期，原版和事件仍可追溯；实现 SQLite 存取。
- [ ] 运行 `pytest backend/tests -q`，确认通过。

### Task 2: 真实模型适配
- [ ] 编写 pytest，模拟文本成功、图片成功、缺密钥、超时和上游错误；验证错误信息无密钥。
- [ ] 实现服务端 OpenRouter 文本和图片接口，模型可配置、设超时，图片持久化；查官方文档核实模型 ID 和请求格式。
- [ ] 运行 `pytest backend/tests -q`，确认通过；添加 `.env.example` 和忽略规则。

### Task 3: 群聊协作和交接
- [ ] 用假提供商测试：有理由的反馈可产生新任务单且下游引用新版；Lead 保持原决定时仍引用原版；失败后重试仅重跑失败阶段。
- [ ] 实现固定四群状态机、至多两轮反驳、Lead 结构化决策与阶段事件；模拟询盘反馈显式标记。
- [ ] 提供创建任务、查询状态/事件/成果及重试接口；运行 `pytest backend/tests -q`。

### Task 4: 产物与质检
- [ ] 测试未知参数被标记待核实、不同版本引用被拦截或标记过期、示例图标记来源。
- [ ] 实现图片素材存储、基于模板的确定性文字排版和模拟问答，检查尺寸、版本引用和事实依据；不把模型判断当作保证。
- [ ] 运行 `pytest backend/tests -q`，确认通过。

### Task 5: 展示与运行说明
- [ ] 实现四群聊天、进度、Lead 决策、任务单版本、成果追溯、错误重试和主动选择备用素材；明显标记虚构和示例。
- [ ] 添加交互测试，验证失败、重试和成果来源；运行前端测试与生产构建。
- [ ] 写 README：本地运行、网络及 API 配置、估算费用、示例素材限制和私有仓库注意事项。
- [ ] 用假提供商跑完整演示；有用户配置的凭证时再做一次真实小额端到端验证，记录结果和未验证项。

实现补充：询盘群分为初版模拟反馈和终版回复两个阶段；假模型测试固定反馈导致版本变化。质检不通过时任务进入待审核，不能显示交付完成，允许修订或重试。

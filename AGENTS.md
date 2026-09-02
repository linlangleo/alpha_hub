# AGENTS.md - KB-Builder Codebase Guide

## 工作规则

遇到问题时先完成根因分析，向用户说明可选方案、优缺点和推荐方案，获得确认后再进行破坏性或大范围修改。保留用户已有改动，不提交密钥或真实服务凭证。

**遇到问题时，必须遵守以下流程：**

1. **先分析**：仔细分析问题的根本原因，不要急于修改代码
2. **汇报**：向用户清楚解释：
   - 问题的原因是什么
   - 可能有哪些解决方案
   - 每种方案的优缺点
3. **等待指示**：等用户确认后再进行代码修改
4. **不要**：没理解清楚就改代码，或者改完代码才发现有问题

**典型错误示例**：
- ❌ "我发现了问题，马上修改！" → 不分析就改
- ❌ 改完代码才发现还有其他问题 → 分析不全面
- ✅ "问题A是由B导致的，有两个解决方案X和Y，建议用X因为...，你觉得呢？" → 分析后汇报


## 开发约束

- `config/config.json` 提供开发默认值，环境变量或 `.env` 可选覆盖；不要提交真实服务凭证。
- 禁止在业务代码中直接调用 OSS、Qdrant 或具体 Embedding SDK；必须经过抽象服务。
- 文档状态使用 `UPLOADED`、`PROCESSING`、`INDEXED`、`FAILED`。
- 所有检索必须携带 `knowledge_base_id` 过滤条件。
- 不使用 SQLite；数据库开发与集成测试使用 PostgreSQL，单元测试 mock repository 边界。
- 保持 PEP 8、4 空格缩进、120 字符以内，并为公共接口添加类型标注。

## API 开发规范

- 业务接口只使用 GET 和 POST，禁止新增 PUT、PATCH、DELETE。
- GET 仅用于无副作用查询；业务 ID 使用路径参数并放在 URL 最后。
- POST 用于新增、修改、删除和触发任务；业务参数放入 JSON Body，不使用路径参数。
- 文件上传使用 POST 和 `multipart/form-data`。
- 登录 Token 统一通过 `Authorization: Bearer <token>` 请求头传递，不放入 URL 或请求体。
- 接口路径必须体现行为，例如 `/list`、`/detail/{id}`、`/update-summary`、`/delete`。
- 所有 JSON API 响应统一为 `{code: number, msg: string, data: any}`；`code=0` 表示成功，失败响应的 `data` 固定为 `null`。
- 只要应用形成 JSON 响应，HTTP 状态码统一为 `200`；成功和失败只通过响应体 `code` 判断。
- 路由成功时返回 `R.ok(...)`；业务失败抛出 `BusinessException`。业务代码禁止抛出 `HTTPException` 或直接返回 `JSONResponse`。
- 业务错误码按 `docs/API.md` 的 4 位模块号段分配，并集中维护在 `app/common/codes/`；新增枚举必须加入 `ALL_CODE_ENUMS`。
- API 异常由 `app/common/handler.py` 的全局处理器转换，响应不得包含未包装的 `detail` 或异常堆栈。
- 新增或修改接口时必须同步更新 `docs/API.md`、前端调用和自动化测试。
- 完整接口约定和接口清单以 `docs/API.md` 为准。

## 常用命令

```bash
docker compose up -d --build
pytest
python -m py_compile app/main.py
```

测试启动服务后，结束前必须停止测试进程并确认端口 8000 已释放。

# AlphaHub API

默认地址：`http://127.0.0.1:8000`，Swagger：`/docs`。

## 通用规范

- 查询使用 GET，不得修改服务端数据。
- 新增、修改、删除和触发任务使用 POST。
- GET 的业务 ID 使用路径参数并放在 URL 最后。
- POST 的业务参数使用 JSON Body，URL 不携带业务参数。
- 文件上传使用 `multipart/form-data`。
- 除登录和健康检查外，接口均需携带：

```http
Authorization: Bearer <access_token>
```

Token 是鉴权信息，不属于业务参数。后端根据 Token 从 Redis Session 获取当前用户 ID，
客户端不得传入或覆盖操作用户 ID。

雪花 ID 在 JSON 中使用字符串传输，避免 JavaScript 数值精度丢失。

## 统一响应格式

所有 JSON API 均返回以下结构：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {}
}
```

- `code` 为 `0` 表示成功，非 `0` 表示失败。
- `msg` 是可直接展示或记录的结果说明。
- `data` 的成功类型由具体接口确定，同一接口必须保持稳定。
- 失败响应的 `data` 固定为 `null`，不得改成 `{}`、省略字段或返回其他类型。
- 只要请求进入应用并形成 JSON 响应，HTTP 状态码统一为 `200`。
- 成功与失败只通过响应体 `code` 判断，客户端不能仅依赖 HTTP 状态码。

成功示例：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "id": "352750836159352832"
  }
}
```

失败示例：

```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "code": 3001,
  "msg": "知识文档不存在",
  "data": null
}
```

前端类型可定义为：

```typescript
type ApiResponse<T> =
  | { code: 0; msg: string; data: T }
  | { code: number; msg: string; data: null };
```

请求参数校验异常、框架路由异常、业务异常和未捕获异常均由全局异常处理器转换。
未捕获异常只记录在服务端日志中，响应不得包含堆栈、密钥或底层连接信息。连接失败、
网关错误和进程崩溃等应用无法形成响应的情况仍可能产生真实 HTTP 4xx/5xx。

## 业务错误码

业务错误码使用 4 位模块号段；`0` 和 `1` 是保留的全局特殊值。

| 号码段 | 模块 | 说明 |
|---|---|---|
| `0` | 成功 | 所有成功响应固定使用 |
| `1` | 公共 | 未细分失败，只用于无需前端分类处理的兜底 |
| `1000-1999` | 公共 | 参数校验、路由和通用状态 |
| `2000-2999` | 认证授权 | 登录、Session 和权限 |
| `3000-3999` | 知识库 | 文档、Chunk 和入库操作 |
| `4000-4999` | 检索问答 | Hybrid Retrieval 和 RAG 问答 |
| `5000-5999` | 策略 | 策略管理 |
| `9000-9999` | 系统 | 内部错误和基础设施 |

当前已分配错误码：

| code | 枚举成员 | 含义 |
|---|---|---|
| `0` | `CommonCode.SUCCESS` | 成功 |
| `1` | `CommonCode.FAIL` | 未细分失败 |
| `1000` | `CommonCode.PARAM_ERROR` | 请求参数校验失败 |
| `1001` | `CommonCode.ROUTE_NOT_FOUND` | 请求接口不存在 |
| `1002` | `CommonCode.METHOD_NOT_ALLOWED` | 请求方法不允许 |
| `2000` | `AuthCode.LOGIN_REQUIRED` | 请先登录 |
| `2001` | `AuthCode.SESSION_EXPIRED` | 登录已失效 |
| `2002` | `AuthCode.INVALID_CREDENTIALS` | 用户名或密码错误 |
| `2003` | `AuthCode.FORBIDDEN` | 无操作权限 |
| `3000` | `KnowledgeCode.INVALID_PARAMETER` | 知识库请求参数错误 |
| `3001` | `KnowledgeCode.DOCUMENT_NOT_FOUND` | 知识文档不存在 |
| `3002` | `KnowledgeCode.DOCUMENT_FORBIDDEN` | 无权操作该知识文档 |
| `3003` | `KnowledgeCode.DOCUMENT_STATE_INVALID` | 当前文档状态不允许操作 |
| `3004-3008` | `KnowledgeCode` | 上传、删除、Chunk 和原文件错误 |
| `4000-4001` | `RagCode` | 知识检索和问答失败 |
| `5000` | `StrategyCode.STRATEGY_NOT_FOUND` | 策略不存在 |
| `9001` | `SystemCode.INTERNAL_ERROR` | 系统内部错误 |
| `9002` | `SystemCode.SERVICE_UNAVAILABLE` | 基础服务暂不可用 |
| `9003` | `SystemCode.UNKNOWN_SERVICE` | 未知服务 |

错误码集中维护在 `app/common/codes/`。各枚举共享无成员的 `CodeEnum` 基类，不继承
`CommonCode`。新增枚举必须加入 `ALL_CODE_ENUMS`；应用导入时会校验号段、成员范围和
全局重复码，校验失败将阻止服务启动。

参数校验失败示例：

```json
{
  "code": 1000,
  "msg": "参数 document_id 校验失败：Input should be greater than 0",
  "data": null
}
```

业务路由成功时统一返回 `R.ok(data)`，失败时抛出
`BusinessException(错误码枚举, 可选覆盖文案)`。禁止业务代码直接抛出
`HTTPException` 或返回 `JSONResponse`。

## 账号级数据权限

当前版本不实现角色或管理员权限。用户只能查看和操作自己上传的知识文档及其 Chunk。
服务端以 `knowledge_document.create_by` 判断归属，不能依赖前端隐藏按钮。

删除文档时：

- 文档不存在返回业务码 `3001`：`知识文档不存在`。
- 文档存在但不属于当前账号返回业务码 `3002`：`该文档不是你上传的，无删除权限`。
- 只有 `FAILED` 和 `INDEXED` 状态允许删除。
- `UPLOADED` 和 `PROCESSING` 可能仍有后台任务运行，返回业务码 `3003`。

## 接口清单

### 基础与鉴权

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/health` | PostgreSQL、Redis 健康状态 |
| POST | `/api/auth/login` | 用户名密码登录 |
| GET | `/api/auth/check-login` | 检查 Token 对应的登录状态 |
| POST | `/api/auth/logout` | 删除 Redis Session |
| GET | `/api/dashboard/stats` | 当前账号的知识、审核状态和服务统计 |

### 知识文档

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/knowledge/documents/upload` | 上传 DOCX、PDF、TXT 或图片，并启动后台知识入库 |
| GET | `/api/knowledge/documents/list` | 当前账号的文档列表和审核数量 |
| GET | `/api/knowledge/documents/detail/{document_id}` | 文档、Chunk、Context、图片和状态详情 |
| GET | `/api/knowledge/documents/status/{document_id}` | 文档主状态和处理阶段 |
| GET | `/api/knowledge/documents/parsed/{document_id}` | 文档及完整 Chunk 解析结果 |
| GET | `/api/knowledge/documents/raw-url/{document_id}` | MinIO 原文件临时访问地址 |
| POST | `/api/knowledge/documents/delete` | 永久删除文档及其关联存储 |
| POST | `/api/knowledge/documents/reprocess` | 重新处理当前账号的失败文档 |

上传使用 `multipart/form-data`：

- `file`：DOCX、PDF、TXT、JPEG、PNG、GIF 或 WebP。
- `source_type`、`source_name`、`category`。
- 可选 `strategy_id`。
- `analysis_model`：DOCX/PDF/TXT 只能使用配置的文本模型；图片只能使用 Vision 模型。

TXT 支持 UTF-8 和 GB18030。PDF 会按页面阅读顺序提取文本和内嵌图片；纯扫描 PDF
暂不执行 OCR。独立图片最大 32 MB，这是当前 Base64 Vision 调用方式的限制。

独立图片的原文件保存到 MinIO `raw/image/{year}/{month}/{document_id}/`。Vision 首先生成
可见文字转录和视觉内容说明，随后将以下内容作为可检索知识正文：

```text
[[IMAGE:image_001]]

标题：...
可见文字：
...
视觉内容说明：
...
```

Chunk 的 `image_keys` 指向 MinIO 原图；PostgreSQL 保存上述文字内容，Qdrant 仍只保存向量
和检索 metadata，不保存图片或完整正文。DOCX/PDF 内嵌图片继续保存到
`extracted/images/{document_id}/`，本次不额外调用 Vision。

### DeepSeek 动态模型

`config/config.json` 使用同一个 `base_url`，通过每次 API 请求的 `model` 参数动态选择模型：

```json
{
  "deepseek": {
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-flash",
    "text_models": [
      "deepseek-v4-flash",
      "deepseek-v4-pro"
    ],
    "vision_model": "deepseek-v4-flash-vision-exp"
  }
}
```

- `model` 是默认文本模型，也用于普通知识问答。
- `text_models` 是 DOCX/PDF/TXT 上传页允许选择的模型列表。
- `vision_model` 是独立图片唯一允许使用的模型。
- 上传选择结果保存在 `knowledge_document.metadata.analysis_model`，文档级分析、Chunk
  批量分析和 Context 压缩均沿用该模型。
- 环境变量可分别使用 `DEEPSEEK_MODEL`、逗号分隔的 `DEEPSEEK_TEXT_MODELS` 和
  `DEEPSEEK_VISION_MODEL` 覆盖。

删除请求：

```json
{
  "document_id": "352750836159352832"
}
```

重新处理请求：

```json
{
  "document_id": 353482950567792640
}
```

仅 `FAILED` 文档允许重新处理。接口会原子地将文档占用为 `PROCESSING`，防止重复点击
产生并发任务。后端依据 `knowledge_document.metadata.error_stage` 选择恢复方式：

- `EMBEDDING_FAILED`、`EMBEDDING_MODEL_PREPARE_FAILED`、
  `EMBEDDING_ENCODE_FAILED` 和 `QDRANT_UPSERT_FAILED` 复用 PostgreSQL 已有 Chunk，
  只重新执行 BGE-M3 和 Qdrant，不重复调用 DeepSeek。
- `CHUNK_ANALYSIS_FAILED` 和 `DATABASE_SAVE_FAILED` 从 MinIO 重新解析原文件，但复用
  `metadata.document_analysis_checkpoint`，不重复调用文档级 DeepSeek；如果旧数据没有检查点，
  自动回退为完整处理。
- 其他失败阶段从 MinIO 读取原文件，重新执行完整入库流程，不重复上传原文件。
- 原文件不存在时拒绝完整重处理，并提示重新上传。

失败阶段包括 `PARSE_FAILED`、`EXTRACTED_IMAGE_SAVE_FAILED`、
`DOCUMENT_ANALYSIS_FAILED`、`CHUNK_BUILD_FAILED`、`CHUNK_ANALYSIS_FAILED`、
`DATABASE_SAVE_FAILED`、`EMBEDDING_MODEL_PREPARE_FAILED`、
`EMBEDDING_ENCODE_FAILED` 和 `QDRANT_UPSERT_FAILED`。

删除顺序为：校验账号归属和文档状态、删除 Qdrant point、删除 MinIO 原文件、删除
`extracted/images/{document_id}/` 下的提取图片，最后删除 PostgreSQL 文档。PostgreSQL 外键自动
级联删除 `knowledge_chunk` 和 `chunk_tag` 关联记录。

删除成功响应：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "success": true,
    "document_id": "352750836159352832"
  }
}
```

### Chunk 操作

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/knowledge/chunks/update-content-context` | 修改正文或 Context 并重新向量化 |
| POST | `/api/knowledge/chunks/update-summary` | 只更新 PostgreSQL Summary |
| POST | `/api/knowledge/chunks/update-metadata` | 修改标题、类型、Strategy、Tags 并同步 Qdrant payload |
| POST | `/api/knowledge/chunks/regenerate-context` | 使用 Skill 重新生成 Context 并重新向量化 |
| POST | `/api/knowledge/chunks/mark-reviewed` | 标记 Chunk 已审核并同步 Qdrant payload |
| POST | `/api/knowledge/chunks/enable-retrieval` | 恢复 Chunk 检索 |
| POST | `/api/knowledge/chunks/disable-retrieval` | 禁用 Chunk 检索 |
| POST | `/api/knowledge/chunks/reindex` | 重建同一个 Qdrant point |

所有 Chunk 操作请求都在 JSON Body 中传入字符串形式的 `chunk_id`。其他字段按操作附加，例如：

```json
{
  "chunk_id": "352750836159352833",
  "content": "正文",
  "context": "检索背景"
}
```

### 检索、策略、标签与系统

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/knowledge/search` | BGE-M3 Hybrid Retrieval 和 PostgreSQL 回查 |
| POST | `/api/knowledge/ask` | Hybrid Retrieval、Neighbor 扩展和 DeepSeek RAG |
| GET | `/api/strategies/list` | 策略列表 |
| GET | `/api/tags/list` | 当前账号可见标签列表 |
| GET | `/api/system/config` | 返回不含密钥的公开配置 |
| POST | `/api/system/services/test` | 测试指定基础服务 |

服务测试请求：

```json
{
  "service_name": "qdrant"
}
```

## 文档状态

文档主状态为 `UPLOADED/PROCESSING/INDEXED/FAILED`：

- `UPLOADED`：原文件已保存，后台任务等待开始。
- `PROCESSING`：正在解析、分析、保存 Chunk 或向量化。
- `INDEXED`：Chunk 和向量已完成，可以检索。
- `FAILED`：后台入库已经终止。

详细阶段位于 `metadata.processing_stage`，失败信息位于
`metadata.error_stage/error_message/error_detail`。DeepSeek Structured Output 失败时，
`error_detail` 记录错误类型、调用阶段、模型、尝试次数、响应 ID、结束原因、响应长度以及
JSON 解析位置；完整原始响应不写入 PostgreSQL，后端日志仅记录最多 1000 字符的失败响应片段。

## 检索边界

服务端根据当前登录用户强制设置 `knowledge_base_id`，并过滤
`retrieval_status=active`，客户端不能绕过。Qdrant 不保存完整正文；后端根据 `chunk_id`
批量读取 PostgreSQL 后再响应。

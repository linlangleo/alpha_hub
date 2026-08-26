# AlphaHub API

默认地址：`http://127.0.0.1:8000`，Swagger：`/docs`。除登录和健康检查外，接口均需：

```http
Authorization: Bearer <access_token>
```

## 核心接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/health` | PostgreSQL、Redis 健康状态 |
| POST | `/api/auth/login` | 用户名密码登录 |
| POST | `/api/auth/logout` | 删除 Redis 会话 |
| GET | `/api/dashboard/stats` | 知识、审核状态和基础服务统计 |
| POST | `/api/knowledge/documents` | 上传 DOCX 并后台执行两阶段知识入库 |
| GET | `/api/knowledge/documents` | 文档列表及 reviewed 数量 |
| GET | `/api/knowledge/documents/{id}` | 文档、Chunk、Context、图片和状态详情 |
| GET | `/api/knowledge/documents/{id}/status` | 主状态和 processing_stage |
| GET | `/api/knowledge/documents/{id}/raw-url` | MinIO 原文件临时 URL |
| POST | `/api/knowledge/search` | BGE-M3 Hybrid Retrieval，PostgreSQL 回查 |
| POST | `/api/knowledge/ask` | Hybrid Retrieval + Neighbor + DeepSeek RAG |
| PATCH | `/api/knowledge/chunks/{id}/content-context` | 修改正文/Context并重新向量化 |
| PATCH | `/api/knowledge/chunks/{id}/summary` | 只更新 PostgreSQL Summary |
| PATCH | `/api/knowledge/chunks/{id}/metadata` | 修改标题、类型、Strategy、Tags并同步 payload |
| POST | `/api/knowledge/chunks/{id}/regenerate-context` | 只加载 chunk_context Skill 后重新向量化 |
| POST | `/api/knowledge/chunks/{id}/review` | 标记 Chunk 已审核并同步 payload |
| PATCH | `/api/knowledge/chunks/{id}/retrieval-status` | 禁用或恢复普通检索 |
| POST | `/api/knowledge/chunks/{id}/reindex` | 重建同一个 Qdrant Point |

## 上传

`POST /api/knowledge/documents` 使用 `multipart/form-data`：`file`、`source_type`、
`source_name`、`category`、可选 `strategy_id`。当前只接受 DOCX。

文档主状态为 `UPLOADED/PROCESSING/INDEXED/FAILED`；详细阶段位于
`metadata.processing_stage`。失败信息位于 `metadata.error_stage/error_message`。

## 检索边界

服务端根据当前登录用户强制设置 `knowledge_base_id`，同时过滤
`retrieval_status=active`，客户端不能绕过。Qdrant 不返回完整正文；后端根据 `chunk_id`
批量读取 PostgreSQL 后再响应。

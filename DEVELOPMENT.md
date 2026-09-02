# AlphaHub 开发指南

AlphaHub 使用 FastAPI、PostgreSQL、Redis、MinIO、Qdrant、DeepSeek 和 BGE-M3。

> 基础服务使用独立 `docker run` 命令。已有同名容器时直接执行 `docker start <容器名>`，
> 不要重复创建。

本地没有对应镜像时，Docker 会在首次创建容器时自动拉取。

## 环境与入口

| 组件 | 版本或方案 |
|---|---|
| Python | 3.12 |
| PostgreSQL | 16 |
| Redis | 7 |
| Qdrant | latest |
| MinIO | latest |
| LLM | DeepSeek |
| Embedding | BAAI/bge-m3，dense + sparse |

安装并启动：

```powershell
python -m pip install -r requirements.txt
python main.py
```

| 用途 | URL |
|---|---|
| 登录 | `http://127.0.0.1:8000/login.html` |
| Dashboard | `http://127.0.0.1:8000/dashboard.html` |
| 健康检查 | `http://127.0.0.1:8000/api/health` |
| Swagger | `http://127.0.0.1:8000/docs` |
| Qdrant Dashboard | `http://127.0.0.1:6333/dashboard` |
| MinIO Console | `http://127.0.0.1:9001` |

开发账号由 `database/init_db.sql` 创建。

## 配置

`config/config.json` 提供开发默认值，系统环境变量或根目录 `.env` 可以覆盖：

```text
系统环境变量 → .env → config/config.json
```

真实 API Key 和正式环境密码不要提交。DeepSeek Key 推荐放在本地 `.env`：

```dotenv
DEEPSEEK_API_KEY=填写本地DeepSeekKey
```

如使用根目录 `.env`，不要保留空配置值，否则空值会覆盖 `config/config.json` 的默认配置。

## PostgreSQL

PostgreSQL 保存文档、完整 Chunk、Context、Summary、标签、策略和审核状态。

| 配置项 | 开发值 | 说明 |
|---|---|---|
| 镜像 | `postgres:16-alpine` | PostgreSQL 16 的 Alpine 镜像 |
| 容器 | `local-postgres` | 本地开发容器名 |
| 端口 | `5432` | 与 `database.port` 保持一致 |
| 数据库 | `alpha_hub` | 与 `database.database` 保持一致 |
| 用户名 | `postgres` | 与 `database.user` 保持一致 |
| 开发密码 | `postgres_dev` | 仅用于本地开发，与 `database.password` 保持一致 |
| 数据卷 | `postgres_data` | Docker Named Volume，可用 `docker volume ls` 或 `docker volume inspect postgres_data` 查看 |

首次创建：

```shell
docker run -d --name local-postgres -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres_dev -e POSTGRES_DB=alpha_hub -p 5432:5432 -v postgres_data:/var/lib/postgresql/data -v "D:/data/project/alpha_hub/database/init_db.sql:/docker-entrypoint-initdb.d/001_init_db.sql:ro" postgres:16-alpine
```

空数据卷首次启动时会自动执行 `database/init_db.sql`。

### 完整重建数据库

以下操作会删除 `alpha_hub` 的全部数据：

```shell
docker exec local-postgres psql -v ON_ERROR_STOP=1 -U postgres -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'alpha_hub' AND pid <> pg_backend_pid();"
docker exec local-postgres psql -v ON_ERROR_STOP=1 -U postgres -d postgres -c "DROP DATABASE IF EXISTS alpha_hub;"
docker exec local-postgres psql -v ON_ERROR_STOP=1 -U postgres -d postgres -c "CREATE DATABASE alpha_hub;"
docker exec local-postgres psql -v ON_ERROR_STOP=1 -U postgres -d alpha_hub -f /docker-entrypoint-initdb.d/001_init_db.sql
```

当前开发阶段只维护完整初始化脚本，不提供旧结构增量 Migration。

### 常用命令

```shell
docker logs -f local-postgres
docker stop local-postgres
docker start local-postgres
docker exec -it local-postgres psql -U postgres -d alpha_hub
docker volume inspect postgres_data
```

数据约定：

- 主键使用 `BIGINT`，由后端生成雪花 ID。
- 业务表包含 `create_time/update_time/create_by/update_by`。
- 审计字段由后端维护，不使用数据库 Trigger。
- 密码只保存哈希，SQL 必须参数化。
- 文档主状态为 `UPLOADED/PROCESSING/INDEXED/FAILED`。
- 详细阶段保存在 `knowledge_document.metadata.processing_stage`。

## Redis

Redis 保存登录会话，Key 前缀为 `alpha_hub:session:`。

| 配置项 | 开发值 | 说明 |
|---|---|---|
| 镜像 | `redis:7` | Redis 7 镜像 |
| 容器 | `local-redis` | 本地开发容器名 |
| 端口 | `6379` | 与 `redis.port` 保持一致 |
| DB | `0` | 与 `redis.db` 保持一致 |
| 密码 | `<REDIS_PASSWORD>` | 启动前替换，并与 `redis.password` 保持一致；不要把真实密码写入文档 |
| Key 前缀 | `alpha_hub:session:` | AlphaHub 登录会话命名空间 |
| 数据卷 | `redis_data` | Docker Named Volume，用于保存 AOF 数据 |
| 持久化 | AOF | 通过 `--appendonly yes` 开启 |

将占位符替换为与项目配置一致的密码：

```shell
docker run -d --name local-redis -p 6379:6379 -v redis_data:/data redis:7 redis-server --requirepass "<REDIS_PASSWORD>" --appendonly yes
```

常用命令：

```shell
docker logs -f local-redis
docker stop local-redis
docker start local-redis
docker exec -it local-redis redis-cli
```

进入 `redis-cli` 后测试：

```text
AUTH <REDIS_PASSWORD>
PING
```

正常返回 `PONG`。

## Qdrant

Qdrant 只保存向量和轻量检索 Metadata，完整知识从 PostgreSQL 回查。

| 配置项 | 开发值 | 说明 |
|---|---|---|
| 镜像 | `qdrant/qdrant:latest` | Qdrant 最新镜像 |
| 容器 | `local-qdrant` | 本地开发容器名 |
| REST API 端口 | `6333` | 与 `qdrant.url` 保持一致，也是 Dashboard 使用的端口 |
| gRPC 端口 | `6334` | Qdrant gRPC 服务端口 |
| Collection | `alpha_knowledge` | 与 `qdrant.collection` 保持一致 |
| 数据卷 | `qdrant_data` | Docker Named Volume，保存 Segment、索引和 WAL |

Qdrant 的底层文件由数据库自行维护，不要直接修改 `qdrant_data` 中的内容。

首次创建：

```shell
docker run -d --name local-qdrant -p 6333:6333 -p 6334:6334 -v qdrant_data:/qdrant/storage qdrant/qdrant:latest
```

创建或重建 Collection：

```powershell
python -c "from app.services.container import get_vector_service; get_vector_service().recreate_collection()"
```

Collection 包含：

- named dense vector：`dense`，1024 维。
- named sparse vector：`sparse`。
- Hybrid Retrieval：Qdrant RRF Fusion。

Payload：

```text
knowledge_base_id
chunk_id
document_id
chunk_index
title
context
strategy_id
strategy_code
chunk_type
document_name
source_type
source_name
tags
analysis_status
retrieval_status
embedding_model
```

Qdrant 不保存 `content/summary/image_keys/document_summary`。所有检索携带
`knowledge_base_id` 和 `retrieval_status=active` 过滤条件。

常用命令：

```shell
docker logs -f local-qdrant
docker stop local-qdrant
docker start local-qdrant
docker volume inspect qdrant_data
```

## MinIO

MinIO 保存原始文件和解析产生的图片。PostgreSQL 只保存 Bucket、Object Key 和文件 Metadata。

| 配置项 | 开发值 | 说明 |
|---|---|---|
| 镜像 | `minio/minio` | MinIO 镜像，未指定标签时使用默认标签 |
| 容器 | `local-minio` | 本地开发容器名 |
| API 端口 | `9000` | 与 `minio.endpoint` 保持一致，供后端访问 |
| Console 端口 | `9001` | MinIO 管理页面端口 |
| Root 用户 | `minio` | 与 `minio.access_key` 保持一致 |
| 开发密码 | `minio_dev` | 仅用于本地开发，与 `minio.secret_key` 保持一致 |
| Bucket | `alpha-hub` | 与 `minio.bucket` 保持一致，保持私有访问 |
| 宿主机目录 | `D:\software\Docker Desktop\bind mount\minio` | Windows Bind Mount，便于定位和备份原始文件 |
| 容器目录 | `/data` | MinIO 容器内部数据目录 |

MinIO 使用 Windows Bind Mount，不使用 Docker Named Volume。

首次创建：

```shell
mkdir "D:\software\Docker Desktop\bind mount\minio"
docker run -d --name local-minio -p 9000:9000 -p 9001:9001 -e MINIO_ROOT_USER=minio -e MINIO_ROOT_PASSWORD=minio_dev -v "D:\software\Docker Desktop\bind mount\minio:/data" minio/minio server /data --console-address ":9001"
```

首次进入 Console 后创建私有 Bucket `alpha-hub`。后端上传时也会自动检测并创建。

Object Key：

```text
raw/docx/{yyyy}/{MM}/{document_id}/{filename}
raw/pdf/{yyyy}/{MM}/{document_id}/{filename}
raw/image/{yyyy}/{MM}/{document_id}/{filename}
raw/audio/{yyyy}/{MM}/{document_id}/{filename}
raw/video/{yyyy}/{MM}/{document_id}/{filename}
extracted/images/{document_id}/image_001.png
```

业务代码只能通过 MinIO API 或 `StorageService` 操作对象，不能直接修改 Bind Mount 中的底层文件。

常用命令：

```shell
docker logs -f local-minio
docker stop local-minio
docker start local-minio
```

## DeepSeek

DeepSeek 用于文档分析、Chunk 批量分析、Context 生成和 RAG 回答。

```text
Base URL: https://api.deepseek.com
Model:     config/config.json 的 deepseek.model
```

连接测试：

```powershell
python -c "from app.services.container import get_deepseek_service; print(get_deepseek_service().chat('你是连接测试助手。','只回复 OK'))"
```

修改配置后需要重启后端。

## BGE-M3

Embedding Text：

```text
context.strip() + "\n" + content.strip()
```

Context 为空时只使用 Content；Title、Summary 和 Tags 不参与 Embedding。默认配置为 1024 维、
CPU、Batch Size 4，CPU 首次验收可改为 1。

服务加载 BGE-M3 时先检查 Hugging Face 本地缓存。缓存完整时直接把本地快照路径交给
FlagEmbedding，不请求远端；缓存缺失或不完整时才联网下载。下载时跳过当前推理不使用的
ONNX 权重和示例图片。

`config/config.json` 的 `embedding.download_if_missing` 默认为 `true`，可用
`EMBEDDING_DOWNLOAD_IF_MISSING=false` 禁止自动下载。自动下载完成后，后续启动继续
使用本地缓存。

下载并预热：

```powershell
python -c "from app.services.container import get_embedding_service; v=get_embedding_service().encode_query('AlphaHub 模型预热'); print('Dense:',len(v.dense),'Sparse:',len(v.sparse.indices))"
```

已有旧缓存可能同时包含 PyTorch 和 ONNX 两套权重，总量约 4.57GB；当前自动下载会跳过
ONNX。也可以手工只下载 PyTorch：

```powershell
python -c "from huggingface_hub import snapshot_download; print(snapshot_download('BAAI/bge-m3', local_dir=r'D:\data\models\bge-m3', ignore_patterns=['onnx/*','imgs/*']))"
```

下载后可将 `embedding.model` 改为本地目录；保留 `BAAI/bge-m3` 时也会优先解析本地缓存。

## 知识入库流程

```text
DOCX → MinIO → 顺序 Blocks
→ DeepSeek 文档分析与 Chunk 边界
→ 程序重建无重叠 Chunk
→ DeepSeek 批量生成 Context 和 Metadata
→ PostgreSQL 保存完整知识
→ BGE-M3 dense+sparse
→ Qdrant RRF Hybrid
→ PostgreSQL 回查
→ document_id + chunk_index 邻居扩展
→ DeepSeek 回答
```

存储边界：

- MinIO：原始文件和提取图片。
- PostgreSQL：文档和完整知识内容。
- Qdrant：向量和轻量检索 Metadata。
- Redis：登录会话。

## 检查与测试

页面“系统设置”可以测试全部服务。命令行检查：

```powershell
python -c "from app.core.database import check_database; from app.core.redis_client import check_redis; from app.services.container import check_storage,check_vector_store; print('PostgreSQL:',check_database()); print('Redis:',check_redis()); print('MinIO:',check_storage()); print('Qdrant:',check_vector_store())"
python -m pytest -q
python -m compileall -q app tests
```

启动测试服务后，结束前必须停止进程并确认端口 8000 已释放。

## 当前限制

- 支持 DOCX、PDF、TXT 和独立图片；扫描型 PDF 暂不执行 OCR 或 Vision。
- 后台任务使用 FastAPI `BackgroundTasks`，进程重启不会自动续跑，可在失败后手动重新处理。
- BGE-M3 在 CPU 上推理较慢。
- 尚无持久化入库时间线、LLM 调用审计和问答历史。

# 接入第三方网盘：能力要求与对接步骤

本文说明将 Knowledge Nexus 的文件处理能力接入任意第三方网盘（非 Cloudreve）所需的 API 能力和实施步骤。

---

## 一、对方必须提供的能力

### 必选（缺一不可）

| 能力 | 用途 | 对应 Cloudreve 接口 |
|---|---|---|
| **目录列举** | 递归扫描文件树，发现所有待处理文件 | `GET /api/v4/file?uri=...` |
| **文件下载** | 获取文件原始字节，送入解析器 | `POST /api/v4/file/url` → `GET <signed-url>` |
| **身份认证** | 带凭据调用上述接口 | OAuth2 Bearer Token |

### 可选

| 能力 | 用途 | 说明 |
|---|---|---|
| **文件元信息** | 判断单个文件是否可访问 | 用于权限验证，无则跳过 |

---

## 二、各接口的返回格式要求

### 目录列举

需要能区分文件和目录，并返回每个条目的唯一标识（路径或 ID）：

```json
{
  "items": [
    { "id": "abc123", "name": "report.pdf", "type": "file", "path": "/reports/report.pdf" },
    { "id": "def456", "name": "archive",    "type": "dir",  "path": "/reports/archive" }
  ]
}
```

`type` 字段名和值可以不同，只要能判断是文件还是目录即可（布尔 `is_dir`、数字 `0/1`、字符串 `"file"/"dir"` 均支持适配）。

### 文件下载

两种方式均可：

- **直接返回字节流**：`GET /files/{id}/content` → 响应体为文件字节
- **签名 URL 方式**：先获取临时 URL，再 `GET` 该 URL 取字节（Cloudreve 用此方式）

## 三、权限要求

只需**只读**权限，无需写入 / 删除 / 分享权限：

| 权限 | 是否必须 |
|---|---|
| 列举目录内容 | ✅ 必须 |
| 下载文件内容 | ✅ 必须 |
| 读取文件元信息（大小、类型） | 可选 |
| 创建 / 修改 / 删除文件 | ❌ 不需要 |

---

## 四、对接实施步骤

### 第一步：实现新的 Client 类

参考 `core/cloudreve/client.py`，新建对应的存储 client，实现以下方法：

```python
class YourStorageClient:
    async def list_files(self, path: str) -> list[dict]:
        """列举 path 下的文件和子目录，每项包含 name、path/id、type(file/dir)"""
        ...

    async def get_file_content(self, path: str) -> bytes:
        """下载并返回文件原始字节"""
        ...
```

### 第二步：适配 Scanner 的目录遍历

`core/services/scanner.py` 中的 `_walk()` 方法解析列举结果，当前兼容多种字段名：

```python
# 已支持的 key 变体（scanner.py _walk 方法）
objects = items.get("files") or items.get("objects") or items.get("items") or []

# 已支持的 type 变体
is_dir = raw_type == 1 or raw_type == "dir" or bool(obj.get("is_dir"))

# 文件路径字段
obj_uri = obj.get("path") or obj.get("uri") or ""
```

如果对方返回格式与上述不符，只需在 `_walk()` 中添加一个字段映射分支，不需要修改其他代码。

### 第三步：接入 API 装配

在 API 工厂中把对应 client 注入 `CloudreveScanner` 和抽取管道使用的文件读取逻辑。Scanner 只依赖 `list_files`，抽取管道只依赖 `get_file_content`，不感知底层网盘品牌。

### 第四步：处理认证

在 `.env` 中加入对方的认证凭据（Token / API Key / OAuth 参数），在 Client 的构造函数里读取。无需修改 FastAPI 路由或其他服务。

### 第五步：验证

```bash
# 启动 API
uvicorn apps.api.main:app --reload

# 触发文件发现
curl -X POST http://localhost:8000/api/cloudreve/scan

# 对指定 URI 执行候选抽取
curl -X POST http://localhost:8000/api/admin/candidates/extract \
  -H "Content-Type: application/json" \
  -d '{"uri":"cloudreve://my/report.pdf"}'
```

---

## 五、常见网盘对接参考

| 网盘 | 认证方式 | 列举接口 | 下载接口 | 变更通知 |
|---|---|---|---|---|
| **OneDrive** | OAuth2 (MSAL) | `GET /v1.0/me/drive/items/{id}/children` | `GET /v1.0/me/drive/items/{id}/content` | Webhook (subscription) |
| **Google Drive** | OAuth2 | `files.list` (Drive API v3) | `files.get` + `alt=media` | Push Notification (Webhook) |
| **阿里云盘** | OAuth2 | `POST /adrive/v1.0/openFile/list` | `POST /adrive/v1.0/openFile/getDownloadUrl` | 无官方推送，轮询 |
| **Box** | OAuth2 / JWT | `GET /folders/{id}/items` | `GET /files/{id}/content` | Webhook |
| **S3 兼容** | AK/SK | `ListObjectsV2` | `GetObject` / 预签名 URL | SNS 事件通知 |

> S3 兼容存储（MinIO、七牛、腾讯 COS、阿里 OSS）接口完全一致，用 `boto3` 即可，成本最低。

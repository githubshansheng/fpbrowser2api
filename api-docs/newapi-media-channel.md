# New API 媒体渠道接入

fpbrowser2api 提供 OpenAI 风格的图片与视频接口，可作为 New API 的普通 OpenAI 渠道接入。New API 无需修改生产代码。

## 渠道配置

- 渠道类型：`OpenAI`
- Base URL：fpbrowser2api 的服务根地址，例如 `http://127.0.0.1:8000`，不要重复填写 `/v1`
- Key：fpbrowser2api 配置的 API Key
- 请求体透传（Pass Through Body）：开启
- 模型：按需填写下表中的公开模型名；不要在 New API 中把同步模型映射成异步模型

multipart 上传会先缓存为 fpbrowser2api 的 `/assets/veo_image_cache/` 地址，因此 `config/setting.toml` 中 `[extension_executor].base_url` 必须是指纹浏览器能够访问的 fpbrowser2api 地址。容器、远程主机或反向代理部署时不要填写只在 API 进程自身可见的回环地址。

同步图片模型：

```text
nana-banana-2_sync
nana-banana-pro_sync
nana-banana-2-4k_sync
nana-banana-pro-4k_sync
gpt-image2-1k_sync
gpt-image2-2k_sync
gpt-image2-4k_sync
```

异步视频/媒体模型：

```text
seedance-2
seedance-2-fast
nana-banana-2
nana-banana-pro
nana-banana-2-4k
nana-banana-pro-4k
veo-3-1
veo-omni-flash
veo-omni-flash-video-edit
gpt-image2-1k
gpt-image2-2k
gpt-image2-4k
```

`fpbrowser-use` 仅用于 New API 渠道测试或按次计费，不创建媒体任务。

## 对外接口清单

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/v1/models` | 查询公开模型 |
| `GET` | `/v1/models/{model_id}` | 查询单个模型 |
| `POST` | `/v1/chat/completions` | New API 渠道测试/按次计费探针 |
| `POST` | `/v1/images/generations` | JSON 同步图片生成；继续兼容 Banana 的 `images` JSON 改图 |
| `POST` | `/v1/images/edits` | OpenAI 风格同步图片编辑；支持 JSON 与 multipart |
| `POST` | `/v1/videos` | 创建异步视频/媒体任务 |
| `GET` | `/v1/videos/{task_id}` | 查询异步任务状态 |
| `GET` | `/v1/videos/{task_id}/content` | 获取视频内容；HTTP(S) 结果返回 307，data-video 结果返回二进制 |
| `POST` | `/v1/tasks` | fpbrowser2api 原生通用任务入口 |
| `GET` | `/v1/tasks/{task_id}` | fpbrowser2api 原生通用任务状态 |
| `GET` | `/v1/task-types` | 查询任务类型 |
| `GET` | `/v1/task-types-public` | 查询公开任务类型 |

所有 `/v1/*` 接口使用 `Authorization: Bearer <API_KEY>`。失败响应统一为：

```json
{
  "error": {
    "message": "...",
    "type": "invalid_request_error",
    "param": null,
    "code": "invalid_request"
  }
}
```

## 图片编辑

JSON 方式适合 URL 或 data URL，也保留原 Banana 调用方式：

```bash
curl -X POST https://your-newapi.example/v1/images/edits \
  -H "Authorization: Bearer NEW_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nana-banana-2_sync",
    "prompt": "保留主体，把背景改为夜晚霓虹城市",
    "images": ["https://example.com/source.png"],
    "n": 1,
    "size": "1024x1024"
  }'
```

multipart 方式支持重复的 `image` 文件字段，共 1–7 张；GPT Image 模型还可上传一个 `mask`：

```bash
curl -X POST https://your-newapi.example/v1/images/edits \
  -H "Authorization: Bearer NEW_API_TOKEN" \
  -F "model=gpt-image2-1k_sync" \
  -F "prompt=只修改蒙版区域" \
  -F "image=@source.png" \
  -F "mask=@mask.png" \
  -F "n=1"
```

约束：

- 图片编辑仍使用 `*_sync` 模型，`n` 只能为 `1`。
- Nana Banana 支持参考图编辑，但不支持 mask；传 mask 会返回 400，避免伪装成蒙版编辑。
- GPT Image 支持 mask。上传文件会复用 VEO 输入缓存的 MIME 校验、大小限制、TTL 和总容量清理。
- 原有 `POST /v1/images/generations` + JSON `images` 的 Banana 改图方式保持可用。

## 视频内容

New API 在任务完成后可请求：

```bash
curl -L https://your-newapi.example/v1/videos/{task_id}/content \
  -H "Authorization: Bearer NEW_API_TOKEN" \
  --output result.mp4
```

任务不存在返回 404，未完成返回 409，完成但没有视频结果返回 502。只接受 HTTP(S) URL 或 `data:video/*;base64`，不会跳转到 `file:`、`ftp:` 等任意协议，也不会把图片任务当成视频下载。

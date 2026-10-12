# N 网 API 申请与使用教程

> 面向：这个项目的作者（你自己用）
> 依据：[N 网官方 OpenAPI 规范](https://api.nexusmods.com/openapi.yaml)（我逐条对着它写的，不是凭记忆）

---

## 0. 先说最重要的一件事

**API 解决不了你现在卡住的那一步 ✗。**

我把整份规范翻了一遍：有 `POST /mod-files`（给 mod 加文件 ✓）、有 `PATCH /mods/{id}`（改 mod 信息 ✓）、
但**没有**「创建 mod」这个端点 ✗。

```
POST /mod-files  的请求体要求 mod_id —— 也就是说：mod 页必须已经存在 ✓
```

⇒ **创建 mod 页本身，只能走网页表单** ✗（就是你截图里那个"Upload mod" ✓）。
API 的价值在**之后**：以后发新版本、改简介、同步文件，都能一条命令搞定 ✓。

---

## 1. 申请 API Key（约 30 秒）

**官方地址**（规范里原文写着的那一个 ✓）：

```
https://www.nexusmods.com/settings/api-keys
```

步骤：

1. 确保**已登录**（未登录会被跳走 ✓）。
2. 打开上面这个地址 → 找到 **Personal API Key** 那一段。
3. 点生成 / 复制 ✓ —— 得到一串 `g...` 开头的长字符串。

> 打不开或点了没反应？大概率还是 **Cloudflare Turnstile** 被扩展挡了 ✗ ——
> 换**无痕窗口**再试 ✓（见另一份排障说明）。

---

## 2. 安全规矩（这一节请务必看完）

| 做 | 不做 |
|---|---|
| ✅ 存到**环境变量**里 | ❌ **不要发给任何人**——包括我 ✗ |
| ✅ 需要时在同一个页面**吊销重发** ✓ | ❌ 不要粘进聊天窗口 / 不要截图发出 ✗ |
| ✅ 只放在本机 ✓ | ❌ 不要提交到 git ✗（仓库 `.gitignore` 已挡住 `.env` / `*.key` ✓）|

**为什么我不收**：这个 key 等于你的账号权限 ✗（能改你的 mod、传文件 ✓）。
我写的脚本**从环境变量读** ✓，全程不打印明文 ✓、不写进日志 ✓ —— 你自己跑就行 ✓。

---

## 3. API 能做什么

| 能做的事 | 端点 |
|---|---|
| 上传文件（先建上传会话） | `POST /uploads` |
| 查上传状态 | `GET /uploads/{id}` |
| **给已有 mod 加一个新文件** | `POST /mod-files`（需要 `mod_id` ✓）|
| 给已有文件发新版本 | `POST /mod-files/{id}/versions` |
| 查某个 mod 的文件列表 | `GET /mods/{id}/files` |
| 改 mod 信息（简介、名称…） | `PATCH /mods/{id}` |
| 查 mod 详情 | `GET /games/{game_domain}/mods/{game_scoped_id}` |
| **创建 mod 页** | **没有这个端点** ✗ |

**鉴权**：请求头 `apikey: <你的 key>` ✓（规范里的 `ApiKeyAuth` ✓）

---

## 4. 上传的完整流程（四步）

```
① POST /uploads
   body: {"size_bytes": 16526580, "filename": "ConvergenceClassItemRandomizer_v1.0.0.exe"}
   → 返回 { id: "上传会话id", presigned_url: "https://...." }

② PUT <presigned_url>
   body: 文件的二进制内容（不要带任何额外头）
   → S3 返回 200

③ GET /uploads/{id}
   → 重复直到 state == "available"（通常几秒）

④ POST /mod-files
   body: {"upload_id": "...", "mod_id": "你的mod数字id", "name": "Convergence Class Item Randomizer",
          "version": "1.0.0", "description": "...", "file_category": "main"}
   → 文件出现在 mod 页的 Files 标签下
```

> 大文件会走**分片上传**（返回里给 `part_size_bytes` / `part_presigned_urls` / `complete_presigned_url`）✓。
> 你这个 exe 只有 **15.7 MB** ✓，走**单段**即可 ✓（脚本按单段写 ✓，遇到分片会明确告诉你 ✓）。

---

## 5. 怎么用（脚本已写好）

脚本：`investigation/apply/_nexus_upload.py` ✓（只读你的环境变量 ✓，不落盘 key ✓）

**第一步 · 设置环境变量**（当前窗口有效）

```bat
:: CMD
set NEXUS_API_KEY=你的key

:: PowerShell
$env:NEXUS_API_KEY="你的key"

:: 想永久设置（新开窗口也有效）
setx NEXUS_API_KEY "你的key"
```

**第二步 · 跑**

```bat
:: 先只查一下（不传任何东西）
python investigation\apply\_nexus_upload.py --check

:: 正式上传到 mod 的文件区
python investigation\apply\_nexus_upload.py ^
  --mod-id 1234567 ^
  --file ConvergenceClassItemRandomizer_v1.0.0.exe ^
  --name "Convergence Class Item Randomizer" ^
  --version 1.0.0 ^
  --desc "Chinese-localized build only. See description." ^
  --category main
```

`--mod-id` 从哪来？就是 mod 页地址里的数字 ✓：

```
https://www.nexusmods.com/eldenring/mods/1234567
                                        ^^^^^^^ 这个
```

---

## 6. 申请之后顺手能做的事

- **发新版本**：改一下 `--version` 再跑一遍 ✓，不用再碰那个老出错的网页表单 ✓
- **同步简介**：用 `PATCH /mods/{id}` 把 `NEXUS_发布文案.md` 的内容推上去 ✓（要的话我再写个小脚本 ✓）
- **发 GitHub 版时自动同步 N 网**：N 网有官方的 [GitHub Action](https://github.com/marketplace/actions/upload-to-nexus-mods) ✓ ——
  推到 GitHub 就自动发 N 网 ✓（那个 Action 要的是 **key + 两个会话 cookie** ✗，cookie 的权限更大 ✗，
  所以我**不推荐**你走那条路 ✓，除非你确实想全自动 ✓）

---

## 7. 常见报错

| 报错 | 原因 |
|---|---|
| `401` / `403` | key 不对、或没带 `apikey` 头 ✓ |
| `422` | 请求体字段不对（比如 `mod_id` 不是数字 ✓ / 少了 `file_category` ✓）|
| `上传会话一直不是 available` | 第 ② 步的 PUT 没成功（常见：presigned URL 过期 ✓ 或文件被代理截断 ✓）→ 重新跑一次 ✓ |
| `mod_id 无效` | 那个数字是 **mod 页**的 id ✓，不是文件 id ✓ |

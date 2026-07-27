# frisobabyaidemo

美素佳儿四个子品牌大型物料 AI 审核 POC。已实现：

- 单张图片审核：独立识别品牌和物料类型，再与上传分组比对；
- Excel 批量审核：读取“品牌 / 物料类型 / 图片链接”，保留原字段并追加结果；
- 低置信度人工复核、画质预警、识别证据与失败关闭；
- 220 张样本的固定 176/44 分层划分及 90% 联合准确率门禁脚本；
- 图片标注筛选器：本地目录逐张标注品牌与物料类型，自动保存、筛选、导出，并可回写数据清单（见下）。

> 当前仓库不内置模型密钥，也不伪造 90% 结果。支持 Chat Completions 与 Responses 两种 OpenAI-compatible 协议；必须配置一个支持图片输入的视觉模型，再运行固定测试集评测。原始数据没有负样本且缺少“店内海报”，因此当前数据不能证明真实通过/驳回准确率。详见 [`docs/requirements.md`](docs/requirements.md)。

## 快速启动

要求 Python 3.11+。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

设置环境变量（或通过部署平台注入）：

```bash
export VISION_API_KEY="..."
export VISION_MODEL="your-vision-model"
export VISION_BASE_URL="https://your-openai-compatible-endpoint/v1"
export VISION_API_STYLE="auto"  # auto / chat_completions / responses
export VISION_REFERENCE_MANIFEST="data/dataset_manifest.csv"
export VISION_EXAMPLES_PER_LABEL="1"
```

启动：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

打开 <http://localhost:8000>。接口文档位于 <http://localhost:8000/docs>。

未配置模型时页面仍可打开，`/api/health` 返回 `degraded`，审核接口返回 503，不会默认通过。

## Excel 批处理

下载 `GET /api/batch/template` 模板，填写：

| 品牌 | 物料类型 | 图片链接 |
|---|---|---|
| 皇家 | 灯箱 | https://static.51dh.com.cn/...jpg |

上传到 `POST /api/batch`。为防止 SSRF，图片域名必须位于 `ALLOWED_IMAGE_HOSTS` 白名单；默认只允许 `static.51dh.com.cn`。

## 数据划分与评测

从客户 Excel 重新生成完全一致的划分：

```bash
python scripts/prepare_dataset.py "/path/to/大型品牌物料审核.xlsx"
```

默认 seed 为 `20260724`，总样本 220，训练 176，测试 44。固定清单已提交到 `data/dataset_manifest.csv`。

配置视觉模型后执行验收：

```bash
python scripts/evaluate.py
```

如果使用本机方舟配置，可直接读取 TOML；文件内容和密钥不会进入报告或仓库：

```bash
python scripts/evaluate.py --ark-config /path/to/personal_config.toml
```

评测会从 176 张训练集中按已有“品牌×类型”联合标签各抽取 1 张人工标注原型，作为多模态上下文校准，再对 44 张测试集逐张判断；测试标签不会进入提示词。报告写入 `artifacts/evaluation_report.json`。联合准确率小于 90% 时脚本退出码为 2，可直接作为 CI/CD 门禁。联合准确率要求品牌和类型同时正确；44 张中至少 40 张正确才通过。

2026-07-24 使用 `doubao-seed-2.0-lite` 和固定测试集实测为：联合准确率 34/44（77.3%）、品牌准确率 43/44（97.7%）、物料类型准确率 35/44（79.5%），未通过 90% 门禁。主要混淆是“灯箱”被判为“橱窗单透/墙贴”或“店招/外立面广告”。详见 [`docs/evaluation-2026-07-24.md`](docs/evaluation-2026-07-24.md)。

## 图片标注筛选器

启动服务后打开 <http://localhost:8000/labeler>（首页右上角也有入口），用于对本机图片目录逐张打品牌与物料标签，形成“选择目录—逐张标注—筛选复查—持久化恢复—导出”的闭环。

- **选择目录**：macOS 本机运行时，点击“选择目录并扫描”会打开系统原生目录选择器，选择后自动填写绝对路径并载入图片；无需手工补全路径。无图形界面或其他系统可直接粘贴目录绝对路径。服务在本机读取该目录（递归扫描，忽略非图片），因此适合本地/内网使用。
- **标注**：每张图片可选择一个或多个品牌，以及一个或多个物料类型。
  - 品牌预置：皇家美素（皇家、旺玥、源悦、尊悦）、常见品牌（爱他美、飞鹤、金领冠、启赋、a2、雀巢、美赞臣、君乐宝、合生元）、辅助（其他、无法判断）。
  - 物料类型严格采用审核标准六类：灯箱、橱窗单透/墙贴、店内海报（非货架）、店招/外立面广告、吊旗、包柱画面。
- **自动保存**：至少选择一个品牌和一个物料后即视为已标注并自动保存，另保留“保存并下一张”；界面显示保存中 / 已保存 / 失败可重试。
- **筛选与进度**：支持全部、未标注、已标注、按品牌、按物料类型筛选，并实时显示标注进度。
- **持久化**：标注写入独立数据目录（默认 `data/labeling/`，按目录绝对路径哈希分文件），刷新与重启不丢失；**绝不修改或覆盖原始图片**。跨子目录的同名文件用相对路径区分并在扫描结果中提示。
- **导出**：支持 CSV（默认，UTF-8 BOM 便于 Excel）与 JSON，按当前筛选条件导出。
- **异常处理**：空目录、目录不存在/不可读、非图片、损坏图片、同名文件、非法路径（`../` 逃逸、绝对路径、空字符）均已处理并给出明确错误。

### 与现有 POC 数据流程的联动

现有 POC 的训练/评测通过 `app.training.load_training_examples` 与 `scripts/evaluate.py` 读取 `data/dataset_manifest.csv`（列 `sample_id,brand,material_type,image_url,split`）。标注筛选器提供一个清晰、可测试的更新入口 `app/manifest_sync.py`：

- 在标注时可为图片填写“关联数据清单链接”（即清单里的 `image_url`）；
- 点击“同步进数据清单”后，`POST /api/labeler/sync-manifest` 会按 `image_url` **精确匹配**已有行，只更新品牌与物料两列，不改动 `split`，不新增行（除非显式 `append_missing`）；
- 只有**恰好一个皇家子品牌 + 恰好一个六类物料 + 已完成**的标注才会写回，因为现有训练清单是单标签结构；多品牌/多物料、竞品、其他、无法判断、未标完的图片会分别跳过并计数，不会被错误压缩成单标签；
- 同步后，现有训练/评测流程再次读取相关图片时即使用最新标签。冲突规则：同一 `image_url` 以最新标注为准覆盖清单原值；同名但不同子目录的本地文件通过相对路径区分，互不影响；未匹配到清单的链接会在返回结果中列出，不会静默追加。

可配置项：`LABELING_DATA_DIR`（默认 `data/labeling`）、`LABELING_MANIFEST`（默认 `data/dataset_manifest.csv`）。

## 测试

```bash
pytest
```

测试使用确定性假模型，不调用外部视觉服务，覆盖通过、驳回、人工复核、单图 API 和 Excel 输出；图片标注筛选器另有独立测试，覆盖目录扫描、保存/更新/恢复、筛选、导出、非法路径拦截、同名文件与数据清单联动。

## 关键配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `VISION_PROVIDER` | `openai_compatible` | 当前支持的识别供应商适配器 |
| `VISION_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible API 根地址 |
| `VISION_API_STYLE` | `auto` | `auto`、`chat_completions` 或 `responses` |
| `VISION_API_KEY` | 空 | API 密钥 |
| `VISION_MODEL` | 空 | 支持图像输入的模型名 |
| `VISION_REFERENCE_MANIFEST` | 空 | 可选训练清单；生产 POC 建议设为 `data/dataset_manifest.csv` |
| `VISION_EXAMPLES_PER_LABEL` | `1` | 每个已有联合标签提供给模型的训练原型数 |
| `MIN_CONFIDENCE` | `0.70` | 低于该值转人工复核 |
| `ALLOWED_IMAGE_HOSTS` | `static.51dh.com.cn` | 批量图片域名白名单，逗号分隔 |
| `BATCH_MAX_ROWS` | `200` | 单批最大行数 |
| `BATCH_CONCURRENCY` | `4` | 批量并发数 |
| `MAX_IMAGE_BYTES` | `15728640` | 单图最大字节数 |

## 目录

```text
app/                 FastAPI 服务、规则、供应商适配器和 Web UI
data/                固定 80/20 数据清单（仅 URL 与标签，不提交图片）
docs/requirements.md 客户需求、四品牌特性、数据缺口与验收口径
scripts/             数据划分与模型评测
tests/               离线自动化测试
```

# frisobabyaidemo

美素佳儿四个子品牌大型物料 AI 审核 POC。已实现：

- 单张图片审核：独立识别品牌和物料类型，再与上传分组比对；
- Excel 批量审核：读取“品牌 / 物料类型 / 图片链接”，保留原字段并追加结果；
- 低置信度人工复核、画质预警、识别证据与失败关闭；
- 220 张样本的固定 176/44 分层划分及 90% 联合准确率门禁脚本。

> 当前仓库不内置模型密钥，也不伪造 90% 结果。必须配置一个支持图片输入的 OpenAI-compatible 视觉模型，再运行固定测试集评测。原始数据没有负样本且缺少“店内海报”，因此当前数据不能证明真实通过/驳回准确率。详见 [`docs/requirements.md`](docs/requirements.md)。

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

评测报告写入 `artifacts/evaluation_report.json`。联合准确率小于 90% 时脚本退出码为 2，可直接作为 CI/CD 门禁。联合准确率要求品牌和类型同时正确；44 张中至少 40 张正确才通过。

## 测试

```bash
pytest
```

测试使用确定性假模型，不调用外部视觉服务，覆盖通过、驳回、人工复核、单图 API 和 Excel 输出。

## 关键配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `VISION_PROVIDER` | `openai_compatible` | 当前支持的识别供应商适配器 |
| `VISION_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible API 根地址 |
| `VISION_API_KEY` | 空 | API 密钥 |
| `VISION_MODEL` | 空 | 支持图像输入的模型名 |
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


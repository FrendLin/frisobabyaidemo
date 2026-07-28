const tabs = document.querySelectorAll(".tab");
const panels = document.querySelectorAll(".tab-panel");
const singleForm = document.getElementById("singleForm");
const imageInput = document.getElementById("imageInput");
const imagePreview = document.getElementById("imagePreview");
const dropZone = document.getElementById("dropZone");
const resultCard = document.getElementById("resultCard");
const reviewButton = document.getElementById("reviewButton");
const healthPill = document.getElementById("healthPill");
const healthText = document.getElementById("healthText");
const batchForm = document.getElementById("batchForm");
const batchInput = document.getElementById("batchInput");
const batchButton = document.getElementById("batchButton");
const batchStatus = document.getElementById("batchStatus");
const batchFileName = document.getElementById("batchFileName");
const batchQualityCheck = document.getElementById("batchQualityCheck");

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    tabs.forEach((item) => item.classList.toggle("active", item === tab));
    panels.forEach((panel) => {
      panel.classList.toggle("active", panel.id === `panel-${tab.dataset.tab}`);
    });
  });
});

function previewFile(file) {
  if (!file) return;
  imagePreview.src = URL.createObjectURL(file);
  imagePreview.alt = `待审核图片：${file.name}`;
  dropZone.classList.add("has-image");
}

imageInput.addEventListener("change", () => previewFile(imageInput.files[0]));
["dragenter", "dragover"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  });
});
["dragleave", "drop"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
  });
});
dropZone.addEventListener("drop", (event) => {
  if (!event.dataTransfer.files.length) return;
  imageInput.files = event.dataTransfer.files;
  previewFile(imageInput.files[0]);
});

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function confirmationItem(label, expected, detected) {
  const available = Boolean(detected);
  const matched = available && expected === detected;
  const judgement = !available ? "无法确认" : matched ? "确认一致" : "确认不一致";
  const tone = !available ? "unknown" : matched ? "matched" : "mismatched";
  return `
    <li class="confirmation-item">
      <div>
        <small>${escapeHtml(label)}确认</small>
        <strong>期望 ${escapeHtml(expected)} · 识别 ${escapeHtml(detected || "无法判断")}</strong>
      </div>
      <span class="confirmation-badge ${tone}">${judgement}</span>
    </li>`;
}

function metricValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return number;
}

function formatScore(value, digits = 2) {
  const score = metricValue(value);
  if (score === null) return "--";
  return score.toFixed(digits).replace(/\.?0+$/, "");
}

function blurJudgement(value) {
  const score = metricValue(value);
  if (score === null) return "未返回";
  return score > 55 ? "模糊" : "正常";
}

function brightnessJudgement(value) {
  const score = metricValue(value);
  if (score === null) return "未返回";
  if (score <= 0.35) return "昏暗";
  if (score >= 0.7) return "过曝";
  return "正常";
}

function qualityHtml(qualityCheck) {
  if (!qualityCheck) return "";
  const blurDescription =
    qualityCheck.blur_description || blurJudgement(qualityCheck.blur);
  const brightnessDescription =
    qualityCheck.brightness_description || brightnessJudgement(qualityCheck.brightness);
  return `
    <section class="quality-result" aria-label="图片质量检查结果">
      <div class="quality-heading">
        <div>
          <small>IMAGE QUALITY</small>
          <h4>图片质量检查</h4>
        </div>
        <span class="quality-state ${qualityCheck.acceptable ? "acceptable" : "attention"}">
          ${qualityCheck.acceptable ? "质量可用" : "建议复核"}
        </span>
      </div>
      <div class="quality-metrics">
        <article>
          <span>模糊程度</span>
          <strong>${formatScore(qualityCheck.blur)}</strong>
          <small>判断：${escapeHtml(blurDescription)}</small>
        </article>
        <article>
          <span>明亮度</span>
          <strong>${formatScore(qualityCheck.brightness, 3)}</strong>
          <small>判断：${escapeHtml(brightnessDescription)}</small>
        </article>
      </div>
      <p>判定口径：模糊度 &gt; 55 为模糊；明亮度 ≤ 0.35 为昏暗，≥ 0.7 为过曝。</p>
    </section>`;
}

function renderResult(result) {
  const labels = {
    passed: ["审核通过", "图片与上传分组一致"],
    rejected: ["审核驳回", "图片中的品牌或物料类型与上传分组不一致"],
    manual_review: ["转人工复核", "品牌或物料类型仍需人工确认"],
  };
  const [title, summary] = labels[result.status];
  const qualityCheck = result.quality_check;
  resultCard.innerHTML = `
    <div class="result-view">
      <div class="result-kicker">
        <span class="status-badge ${escapeHtml(result.status)}">${escapeHtml(title)}</span>
      </div>
      <h3>${escapeHtml(title)}</h3>
      <p class="result-summary">${escapeHtml(summary)}</p>
      <div class="comparison">
        <div class="comparison-card">
          <small>期望分组</small>
          <strong>${escapeHtml(result.expected_brand)} · ${escapeHtml(result.expected_material_type)}</strong>
        </div>
        <span class="comparison-arrow">→</span>
        <div class="comparison-card">
          <small>AI 识别</small>
          <strong>${escapeHtml(result.detected_brand || "无法判断")} · ${escapeHtml(result.detected_material_type || "无法判断")}</strong>
        </div>
      </div>
      <div class="result-list">
        <h4>审核原因</h4>
        <ul>
          ${confirmationItem("品牌", result.expected_brand, result.detected_brand)}
          ${confirmationItem("类型", result.expected_material_type, result.detected_material_type)}
        </ul>
      </div>
      ${qualityHtml(qualityCheck)}
    </div>`;
}

function renderError(message) {
  resultCard.innerHTML = `
    <div class="empty-result">
      <span class="result-orbit" aria-hidden="true"></span>
      <h3>暂时无法审核</h3>
      <p>${escapeHtml(message)}</p>
    </div>`;
}

singleForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  reviewButton.disabled = true;
  reviewButton.firstElementChild.textContent = "识别中…";
  try {
    const response = await fetch("/api/review", { method: "POST", body: new FormData(singleForm) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "审核请求失败");
    renderResult(payload);
  } catch (error) {
    renderError(error.message);
  } finally {
    reviewButton.disabled = false;
    reviewButton.firstElementChild.textContent = "开始审核";
  }
});

batchInput.addEventListener("change", () => {
  batchFileName.textContent = batchInput.files[0]?.name || "选择待审核 Excel";
});

batchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  batchButton.disabled = true;
  batchButton.firstElementChild.textContent = "批量处理中…";
  batchStatus.textContent = "正在下载图片并逐行审核，请勿关闭页面。";
  const formData = new FormData();
  formData.append("workbook", batchInput.files[0]);
  formData.append("quality_check", batchQualityCheck.checked ? "true" : "false");
  try {
    const response = await fetch("/api/batch", { method: "POST", body: formData });
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail || "批量处理失败");
    }
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "material_review_results.xlsx";
    link.click();
    URL.revokeObjectURL(link.href);
    batchStatus.textContent = "处理完成，结果文件已下载。";
  } catch (error) {
    batchStatus.textContent = error.message;
  } finally {
    batchButton.disabled = false;
    batchButton.firstElementChild.textContent = "上传并处理";
  }
});

fetch("/api/health")
  .then((response) => response.json())
  .then((health) => {
    const ready = health.status === "ok";
    healthPill.classList.add(ready ? "ready" : "degraded");
    healthText.textContent = ready ? "识别服务已就绪" : "待配置识别模型";
  })
  .catch(() => {
    healthPill.classList.add("degraded");
    healthText.textContent = "健康检查失败";
  });

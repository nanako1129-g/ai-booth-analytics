function getOrCreateKpiValue(id, label) {
  const existing = document.querySelector(`#${id}`);
  if (existing) return existing;

  const article = document.createElement("article");
  article.className = "rate-kpi";
  const caption = document.createElement("span");
  caption.textContent = label;
  const value = document.createElement("strong");
  value.id = id;
  value.textContent = "—";
  article.append(caption, value);
  document.querySelector(".kpis").append(article);
  return value;
}

const people = document.querySelector("#people");
const fps = document.querySelector("#fps");
const passages = document.querySelector("#passages");
const stops = document.querySelector("#stops");
const stopRate = getOrCreateKpiValue("stop-rate", "立ち止まり率");
const visitors = document.querySelector("#visitors");
const visitRate = getOrCreateKpiValue("visit-rate", "来訪率");
const averageDwell = document.querySelector("#average-dwell");
const leftRight = document.querySelector("#left-right");
const rightLeft = document.querySelector("#right-left");
const status = document.querySelector("#status");
const dot = document.querySelector("#dot");
const trackList = document.querySelector("#track-list");
const resetCounts = document.querySelector("#reset-counts");

function formatRate(numerator, denominator) {
  if (denominator <= 0) return "—";
  return `${((numerator / denominator) * 100).toFixed(1)}%`;
}

function renderTracks(tracks) {
  trackList.replaceChildren();
  if (!tracks.length) {
    const empty = document.createElement("span");
    empty.className = "empty";
    empty.textContent = "人物なし";
    trackList.append(empty);
    return;
  }

  for (const track of tracks) {
    const item = document.createElement("span");
    item.className = "track";
    const attention = track.in_attention_zone
      ? ` · 注目 ${track.attention_seconds.toFixed(1)}秒`
      : "";
    const stopped = track.stopped ? " · 立ち止まり" : "";
    const booth = track.in_booth_zone
      ? track.visitor
        ? ` · ブース ${track.booth_seconds.toFixed(1)}秒`
        : " · ブース内（入場前未確認）"
      : "";
    item.textContent = `${track.id} · ${Math.round(track.confidence * 100)}%${attention}${stopped}${booth}`;
    trackList.append(item);
  }
}

async function refresh() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    const data = await response.json();
    people.textContent = data.people_visible;
    fps.textContent = data.fps.toFixed(1);
    passages.textContent = data.line_counter.passages.toLocaleString("ja-JP");
    stops.textContent = data.attention.stops.toLocaleString("ja-JP");
    visitors.textContent = data.booth.visitors.toLocaleString("ja-JP");
    averageDwell.textContent = data.booth.average_dwell_seconds.toFixed(1);
    stopRate.textContent = formatRate(
      data.attention.stops,
      data.line_counter.passages,
    );
    visitRate.textContent = formatRate(
      data.booth.visitors,
      data.line_counter.passages,
    );
    leftRight.textContent = data.line_counter.left_to_right.toLocaleString("ja-JP");
    rightLeft.textContent = data.line_counter.right_to_left.toLocaleString("ja-JP");
    renderTracks(data.tracks);

    if (data.connected && data.model_ready) {
      dot.className = "dot online";
      status.textContent = data.error || "人物解析中";
    } else {
      dot.className = "dot error";
      status.textContent = data.error || "接続待機中";
    }
  } catch {
    dot.className = "dot error";
    status.textContent = "解析サーバーへ接続できません";
  }
}

resetCounts.addEventListener("click", async () => {
  resetCounts.disabled = true;
  try {
    await fetch("/api/reset-counts", { method: "POST" });
    await refresh();
  } finally {
    resetCounts.disabled = false;
  }
});

refresh();
setInterval(refresh, 1000);

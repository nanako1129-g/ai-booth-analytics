const form = document.querySelector("#connection-form");
const hostInput = document.querySelector("#host");
const stream = document.querySelector("#stream");
const placeholder = document.querySelector("#placeholder");
const statusDot = document.querySelector("#status-dot");
const statusText = document.querySelector("#status-text");
const directLink = document.querySelector("#direct-link");

const savedHost = localStorage.getItem("stackchanCameraHost");
if (savedHost) hostInput.value = savedHost;

function normalizeHost(value) {
  return value.trim().replace(/^https?:\/\//, "").replace(/\/$/, "");
}

function setStatus(kind, message) {
  statusDot.className = `status-dot is-${kind}`;
  statusText.textContent = message;
}

function connect(hostValue) {
  const host = normalizeHost(hostValue);
  if (!host) {
    setStatus("error", "IPアドレスを入力してください");
    return;
  }

  localStorage.setItem("stackchanCameraHost", host);
  const baseUrl = `http://${host}`;
  directLink.href = `${baseUrl}/`;
  setStatus("connecting", `${host} へ接続中…`);
  stream.classList.remove("is-visible");
  placeholder.classList.remove("is-hidden");

  stream.onload = () => {
    setStatus("online", `接続中 — ${host}`);
    stream.classList.add("is-visible");
    placeholder.classList.add("is-hidden");
  };

  stream.onerror = () => {
    setStatus("error", "接続できません。IP・Wi-Fi・CoreS3の画面を確認してください");
    stream.classList.remove("is-visible");
    placeholder.classList.remove("is-hidden");
  };

  stream.src = `${baseUrl}/stream?cache=${Date.now()}`;
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  connect(hostInput.value);
});

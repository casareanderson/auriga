const BASE = "http://127.0.0.1:8765";

const $ = (id) => document.getElementById(id);

function append(entry) {
  const empty = $("empty");
  if (empty) empty.remove();
  const div = document.createElement("div");
  div.className = "log-entry " + (entry.who || "result");
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = entry.who === "user" ? "you" : "agent";
  const line = document.createElement("div");
  line.className = "line";
  line.textContent = entry.text;
  div.append(who, line);
  $("log").append(div);
  div.scrollIntoView({ block: "end" });
}

function setStatus(state, text) {
  $("dot").className = "dot " + state;
  $("status").textContent = text;
}

async function refresh() {
  try {
    const r = await (await fetch(BASE + "/health")).json();
    setStatus(r.extension === "connected" ? "ok" : "warn", r.extension === "connected" ? "bridge + extension connected" : "bridge up, extension not polling");
  } catch (e) {
    setStatus("bad", "bridge not running");
  }
}

function headers() {
  const h = { "Content-Type": "application/json" };
  const t = $("token").value.trim();
  if (t) h["X-Auth-Token"] = t;
  return h;
}

function isJSONCommand(text) {
  const t = text.trim();
  return t.startsWith("{") || t.startsWith("[");
}

// Poll /chat/result and append text as the reply arrives.
async function streamChat(id) {
  append({ who: "stream", text: "working…" });
  for (let i = 0; i < 150; i++) {
    let r;
    try {
      r = await (await fetch(BASE + "/chat/result?id=" + id, { headers: headers() })).json();
    } catch (e) {
      append({ who: "error", text: "(bridge unreachable during chat result poll)" });
      return;
    }
    if (r.text) {
      append({ who: "stream", text: r.text });
      return;
    }
    await new Promise((res) => setTimeout(res, 2000));
  }
  append({ who: "error", text: "(no reply in 5 min — is the extension connected?)" });
}

$("send").onclick = async () => {
  const raw = $("input").value;
  const text = raw.trim();
  if (!text) return;
  $("input").value = "";
  append({ who: "user", text });

  // A JSON body ({"action": …, ...params}) is a plain /command round-trip.
  if (isJSONCommand(text)) {
    let body;
    try {
      body = JSON.parse(text);
    } catch (e) {
      append({ who: "error", text: "(invalid JSON — check the braces/quotes)" });
      return;
    }
    if (!("action" in body)) {
      append({ who: "error", text: '(JSON must include an "action" key, e.g. {"action":"eval","expr":"1+1"})' });
      return;
    }
    $("send").disabled = true;
    try {
      const r = await (await fetch(BASE + "/command", { method: "POST", headers: headers(), body: JSON.stringify(body) })).json();
      if (r.ok) append({ who: "result", text: typeof r.result === "string" ? r.result : JSON.stringify(r.result, null, 2) });
      else append({ who: "error", text: r.error || "(command failed)" });
    } catch (e) {
      append({ who: "error", text: "(bridge not reachable — start it with `./auriga start`)" });
    } finally {
      $("send").disabled = false;
    }
    return;
  }

  // Free-text goal: stream via /chat + poll /chat/result.
  try {
    const r = await (await fetch(BASE + "/chat", { method: "POST", headers: headers(), body: JSON.stringify({ goal: text }) })).json();
    streamChat(r.id);
  } catch (e) {
    append({ who: "error", text: "(bridge not reachable — start it with `./auriga start`)" });
  }
};

$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("send").click();
});

$("token").addEventListener("change", () => {
  chrome.storage.local.set({ aurigaPanelToken: $("token").value });
});

(async () => {
  const { aurigaPanelToken = "" } = await chrome.storage.local.get("aurigaPanelToken");
  $("token").value = aurigaPanelToken;
  refresh();
  setInterval(refresh, 5000);
})();

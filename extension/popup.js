const BASE = "http://127.0.0.1:8765";

function $(id) { return document.getElementById(id); }

async function refresh() {
  try {
    const r = await (await fetch(BASE + "/health")).json();
    if (r.extension === "connected") { $("dot").className = "dot ok"; $("status").textContent = "connected"; }
    else { $("dot").className = "dot ok"; $("status").textContent = "bridge up, extension off"; }
  } catch (e) {
    $("dot").className = "dot bad"; $("status").textContent = "bridge not running";
  }
}

function appendLine(text, who) {
  const t = $("transcript");
  t.value += (who === "you" ? "> " : "") + text + "\n\n";
  t.scrollTop = t.scrollHeight;
}

$("send").onclick = async () => {
  const goal = $("goal").value.trim();
  if (!goal) return;
  appendLine(goal, "you");
  $("goal").value = "";
  try {
    const r = await (await fetch(BASE + "/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goal }) })).json();
    pollResult(r.id);
  } catch (e) {
    appendLine("(bridge not reachable — start it with `./auriga start`)");
  }
};

$("clear").onclick = () => { $("transcript").value = ""; };

$("goal").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("send").click();
});

async function pollResult(id) {
  for (let i = 0; i < 150; i++) {
    const r = await (await fetch(BASE + "/chat/result?id=" + id)).json();
    if (r.text) { appendLine(r.text); return; }
    await new Promise((res) => setTimeout(res, 2000));
  }
  appendLine("(no reply after 5 min — is the agent connected?)");
}

async function loadPerms() {
  const { aurigaAllowed = [], aurigaPending = [] } = await chrome.storage.local.get(["aurigaAllowed", "aurigaPending"]);
  const pend = $("pending");
  pend.innerHTML = "";
  if (!aurigaPending.length) pend.innerHTML = '<div class="muted">no pending approvals</div>';
  for (const o of aurigaPending) {
    const row = document.createElement("div"); row.className = "permrow";
    const u = document.createElement("span"); u.className = "url"; u.textContent = o;
    const b = document.createElement("button"); b.textContent = "Allow"; b.className = "ghost";
    b.onclick = async () => {
      const s = await chrome.storage.local.get(["aurigaAllowed", "aurigaPending"]);
      await chrome.storage.local.set({
        aurigaAllowed: s.aurigaAllowed.includes(o) ? s.aurigaAllowed : [...s.aurigaAllowed, o],
        aurigaPending: s.aurigaPending.filter((x) => x !== o),
      });
      loadPerms();
    };
    row.append(u, b); pend.append(row);
  }
  const al = $("allowed");
  al.innerHTML = "";
  if (!aurigaAllowed.length) al.innerHTML = '<div class="muted">no sites approved yet</div>';
  for (const o of aurigaAllowed) {
    const row = document.createElement("div"); row.className = "permrow";
    const u = document.createElement("span"); u.className = "url"; u.textContent = o;
    const b = document.createElement("button"); b.textContent = "Revoke"; b.className = "ghost";
    b.onclick = async () => {
      const s = await chrome.storage.local.get("aurigaAllowed");
      await chrome.storage.local.set({ aurigaAllowed: s.aurigaAllowed.filter((x) => x !== o) });
      loadPerms();
    };
    row.append(u, b); al.append(row);
  }
}

refresh(); loadPerms();
setInterval(refresh, 5000);

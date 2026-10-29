const BASE = "http://127.0.0.1:8765";
let polling = false;

async function pollLoop() {
  if (polling) return;
  polling = true;
  while (true) {
    let cmd = null;
    try {
      cmd = await (await fetch(BASE + "/poll")).json();
    } catch (e) {
      await new Promise((r) => setTimeout(r, 2000));
      continue;
    }
    if (cmd && cmd.id) {
      let resp;
      try {
        resp = { ok: true, result: await run(cmd) };
      } catch (e) {
        resp = { ok: false, error: String((e && e.message) || e) };
      }
      try {
        await fetch(BASE + "/result", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: cmd.id, ...resp }),
        });
      } catch (e) {}
    }
  }
}

async function activeTab() {
  const [t] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!t) throw new Error("no active tab");
  return t;
}

const GATED = ["click", "type", "read", "eval", "clickText", "find", "fileinputs", "screenshot", "upload", "frameeval", "snapshot", "clickRef", "clickXY", "hover", "capture"];

function toOrigin(u) {
  try { return new URL(u).origin; } catch (e) { return u; }
}

async function originAllowed(url) {
  try {
    const origin = new URL(url).origin;
    const { aurigaAllowed } = await chrome.storage.local.get("aurigaAllowed");
    return (aurigaAllowed || []).includes(origin) || (aurigaAllowed || []).includes("*");
  } catch (e) {
    return false;
  }
}

async function requireUrlApproval(url) {
  if (await originAllowed(url)) return;
  const origin = new URL(url).origin;
  const { aurigaPending } = await chrome.storage.local.get("aurigaPending");
  const pending = aurigaPending || [];
  if (!pending.includes(origin)) {
    pending.push(origin);
    await chrome.storage.local.set({ aurigaPending: pending });
  }
  throw new Error("site not approved: " + origin + " — approve it in the Auriga popup");
}

async function requireApproval(tab) {
  return requireUrlApproval(tab.url);
}

async function run(msg) {
  if (msg.action === "tabs") {
    const tabs = await chrome.tabs.query({});
    return tabs.map((t) => ({ id: t.id, title: t.title, url: t.url, active: t.active }));
  }

  if (msg.action === "extensions") {
    const AUTOMATION = /claude|playwright|puppeteer|browser.?mcp|agent|automation|selenium|devtools|relay|browser.?harness|open.?browser/i;
    const exts = await chrome.management.getAll();
    return exts.map((e) => ({
      name: e.name,
      id: e.id,
      enabled: e.enabled,
      type: e.type,
      automation: AUTOMATION.test((e.name || "") + " " + (e.id || "")),
      perms: (e.permissions || []).filter((p) => /debugger|webRequest|tabs|management|nativeMessaging|cookies/.test(p)),
    }));
  }

  if (msg.action === "approve" || msg.action === "revoke") {
    const origin = toOrigin(msg.url);
    const s = await chrome.storage.local.get(["aurigaAllowed", "aurigaPending"]);
    const allowed = s.aurigaAllowed || [];
    const pending = s.aurigaPending || [];
    if (msg.action === "approve") {
      await chrome.storage.local.set({
        aurigaAllowed: allowed.includes(origin) ? allowed : [...allowed, origin],
        aurigaPending: pending.filter((x) => x !== origin),
      });
      return { approved: origin };
    }
    await chrome.storage.local.set({ aurigaAllowed: allowed.filter((x) => x !== origin) });
    return { revoked: origin };
  }

  if (msg.action === "cookies" || msg.action === "getCookie" || msg.action === "setCookie" || msg.action === "removeCookie") {
    const url = msg.url || (await activeTab()).url;
    await requireUrlApproval(url);
    if (msg.action === "cookies") {
      const cookies = await chrome.cookies.getAll({ url });
      return cookies.map((c) => ({ name: c.name, value: c.value, domain: c.domain, path: c.path,
        secure: c.secure, httpOnly: c.httpOnly, sameSite: c.sameSite, expirationDate: c.expirationDate }));
    }
    if (msg.action === "getCookie") {
      const c = await chrome.cookies.get({ url, name: msg.name });
      return c ? { name: c.name, value: c.value, domain: c.domain, path: c.path, secure: c.secure, httpOnly: c.httpOnly } : null;
    }
    if (msg.action === "setCookie") {
      const [name, value] = String(msg.cookie || "").split("=", 2);
      if (!name || value === undefined) throw new Error("setCookie needs cookie='name=value'");
      const c = await chrome.cookies.set({ url, name, value, path: msg.path || "/" });
      return { set: !!c, name, domain: c && c.domain };
    }
    if (msg.action === "removeCookie") {
      await chrome.cookies.remove({ url, name: msg.name });
      return { removed: true };
    }
  }

  const tab = msg.tabId != null ? await chrome.tabs.get(msg.tabId) : await activeTab();

  if (GATED.includes(msg.action)) {
    await requireApproval(tab);
  }

  if (msg.action === "navigate") {
    await chrome.tabs.update(tab.id, { url: msg.url });
    return { ok: true };
  }
  if (msg.action === "screenshot") {
    const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
    return { dataUrl };
  }
  if (msg.action === "upload") {
    return await uploadFile(tab.id, msg.path, msg.selector);
  }
  if (msg.action === "frameeval") {
    return await frameEval(tab.id, msg.match, msg.js);
  }
  if (msg.action === "snapshot") {
    return await snapshot(tab.id);
  }
  if (msg.action === "clickRef") {
    return await clickRef(tab.id, msg.ref);
  }
  if (msg.action === "clickXY") {
    return await mouse(tab.id, "click", Number(msg.x), Number(msg.y));
  }
  if (msg.action === "hover") {
    return await mouse(tab.id, "hover", Number(msg.x), Number(msg.y));
  }
  if (msg.action === "capture") {
    return await captureDebug(tab.id, msg.duration, msg.what || "both");
  }
  return await sendToTab(tab.id, msg);
}

function sendDebug(tabId, method, params) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand({ tabId }, method, params || {}, (result) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(result);
    });
  });
}

function attach(tabId) {
  return new Promise((res, rej) => chrome.debugger.attach({ tabId }, "1.3", () => {
    if (chrome.runtime.lastError) rej(new Error(chrome.runtime.lastError.message)); else res();
  }));
}

function detach(tabId) {
  return new Promise((res) => chrome.debugger.detach({ tabId }, res));
}

async function frameEval(tabId, urlMatch, js) {
  await attach(tabId);
  try {
    const { frameTree } = await sendDebug(tabId, "Page.getFrameTree", {});
    const urls = [];
    let target = null;
    (function walk(f) { urls.push(f.frame.url || ""); if ((f.frame.url || "").includes(urlMatch)) target = f.frame; (f.childFrames || []).forEach(walk); })(frameTree);
    if (!target) return { found: false, frames: urls };
    const world = await sendDebug(tabId, "Page.createIsolatedWorld", { frameId: target.id, worldName: "auriga" });
    const res = await sendDebug(tabId, "Runtime.evaluate", {
      expression: js, contextId: world.executionContextId, returnByValue: true, awaitPromise: true,
    });
    return { found: true, url: target.url, value: res.result ? res.result.value : undefined };
  } finally {
    await detach(tabId);
  }
}

async function uploadFile(tabId, filePath, selector) {
  if (!filePath) throw new Error("upload needs path=<local file path>");
  const sel = selector || 'input[type="file"]';
  await attach(tabId);
  try {
    const { frameTree } = await sendDebug(tabId, "Page.getFrameTree", {});
    const frames = [];
    (function walk(f) { frames.push(f.frame); (f.childFrames || []).forEach(walk); })(frameTree);
    let nodeId = null, ctxId = null;
    for (const fr of frames) {
      if (nodeId) break;
      try {
        const world = await sendDebug(tabId, "Page.createIsolatedWorld", { frameId: fr.id, worldName: "auriga_upload" });
        const ev = await sendDebug(tabId, "Runtime.evaluate", {
          expression: "document.querySelector(" + JSON.stringify(sel) + ")",
          contextId: world.executionContextId, returnByValue: false,
        });
        if (ev.result && ev.result.subtype === "node" && ev.result.objectId) {
          const rn = await sendDebug(tabId, "DOM.requestNode", { objectId: ev.result.objectId });
          nodeId = rn.nodeId;
          ctxId = world.executionContextId;
        }
      } catch (e) {}
    }
    if (!nodeId) throw new Error("no file input found: " + sel);
    await sendDebug(tabId, "DOM.setFileInputFiles", { nodeId, files: [filePath] });
    if (ctxId) {  // fire a change event so the page (e.g. Uppy) notices the file
      await sendDebug(tabId, "Runtime.evaluate", {
        expression: "document.querySelector(" + JSON.stringify(sel) + ").dispatchEvent(new Event('change',{bubbles:true}))",
        contextId: ctxId, returnByValue: true,
      });
    }
    return { uploaded: true, path: filePath, selector: sel };
  } finally {
    await detach(tabId);
  }
}

async function snapshot(tabId) {
  await attach(tabId);
  try {
    const { nodes } = await sendDebug(tabId, "Accessibility.getFullAXTree", {});
    const interactive = new Set(["button", "link", "textbox", "combobox", "checkbox", "radio", "menuitem",
      "option", "tab", "searchbox", "spinbutton", "listbox", "heading", "switch"]);
    const out = [];
    for (const n of nodes || []) {
      const role = n.role && n.role.value;
      if (!interactive.has(role)) continue;
      const name = (n.name && n.name.value) || "";
      if (!n.backendDOMNodeId) continue;
      out.push({ ref: n.backendDOMNodeId, role, name: name.slice(0, 70) });
    }
    return out;
  } finally {
    await detach(tabId);
  }
}

async function clickRef(tabId, ref) {
  await attach(tabId);
  try {
    const { object } = await sendDebug(tabId, "DOM.resolveNode", { backendNodeId: Number(ref) });
    if (!object || !object.objectId) throw new Error("ref not found: " + ref);
    await sendDebug(tabId, "Runtime.callFunctionOn", {
      objectId: object.objectId,
      functionDeclaration: "function(){this.scrollIntoView({block:'center'});this.click();}",
      returnByValue: true,
    });
    return { clicked: true, ref };
  } finally {
    await detach(tabId);
  }
}

async function mouse(tabId, type, x, y) {
  await attach(tabId);
  try {
    if (type === "hover") {
      await sendDebug(tabId, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
      return { hovered: true, x, y };
    }
    await sendDebug(tabId, "Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
    await sendDebug(tabId, "Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
    return { clicked: true, x, y };
  } finally {
    await detach(tabId);
  }
}

function collectDebugEvents(tabId, duration, kinds) {
  return new Promise((resolve) => {
    const events = [];
    const listener = (source, method, params) => {
      if (source.tabId !== tabId) return;
      if (kinds.includes("network") && method === "Network.responseReceived") {
        events.push({ type: "network", status: params.response.status, url: params.response.url.slice(0, 300) });
      } else if (kinds.includes("network") && method === "Network.loadingFailed") {
        events.push({ type: "network", status: "failed", url: (params.blockedReason || params.errorText || "") });
      } else if (kinds.includes("console") && method === "Runtime.consoleAPICalled") {
        events.push({ type: "console", level: params.type, text: (params.args || []).map((a) => (a.value !== undefined ? a.value : a.description || "")).join(" ").slice(0, 300) });
      } else if (kinds.includes("error") && method === "Runtime.exceptionThrown") {
        events.push({ type: "error", text: (params.exceptionDetails && params.exceptionDetails.text || "").slice(0, 300) });
      }
    };
    chrome.debugger.onEvent.addListener(listener);
    setTimeout(() => { chrome.debugger.onEvent.removeListener(listener); resolve(events); }, (duration || 3) * 1000);
  });
}

async function captureDebug(tabId, duration, what) {
  await attach(tabId);
  try {
    if (what === "console" || what === "both") await sendDebug(tabId, "Runtime.enable", {});
    if (what === "network" || what === "both") await sendDebug(tabId, "Network.enable", {});
    const kinds = what === "both" ? ["network", "console", "error"] : [what];
    const events = await collectDebugEvents(tabId, duration, kinds);
    return { captured: events.length, events };
  } finally {
    await detach(tabId);
  }
}

async function sendToTab(tabId, msg) {
  let resp;
  try {
    resp = await chrome.tabs.sendMessage(tabId, msg);
  } catch (e) {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
    resp = await chrome.tabs.sendMessage(tabId, msg);
  }
  if (resp && resp.ok === false) throw new Error(resp.error);
  return resp && typeof resp === "object" && "result" in resp ? resp.result : resp;
}

pollLoop();
chrome.alarms.create("auriga-keepalive", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(() => { if (!polling) pollLoop(); });

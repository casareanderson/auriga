if (!window.__browserCtl) {
  window.__browserCtl = true;

  function el(selector) {
    const n = document.querySelector(selector);
    if (!n) throw new Error("no element for selector: " + selector);
    return n;
  }

  async function handle(msg) {
    switch (msg.action) {
      case "read": {
        return {
          url: location.href,
          title: document.title,
          text: msg.selector ? el(msg.selector).innerText : document.body.innerText,
        };
      }
      case "click": {
        const n = el(msg.selector);
        n.scrollIntoView({ block: "center" });
        n.click();
        return { clicked: true };
      }
      case "clickText": {
        const txt = String(msg.text || "").trim().toLowerCase();
        const els = [...document.querySelectorAll("a,button,[role=button],[role=link],input[type=submit],input[type=button],span,div")];
        const n = els.find((e) => (e.textContent || e.value || "").trim().toLowerCase() === txt)
          || els.find((e) => (e.textContent || e.value || "").trim().toLowerCase().includes(txt));
        if (!n) throw new Error("no element with text: " + msg.text);
        n.scrollIntoView({ block: "center" });
        n.click();
        return { clicked: true, text: (n.textContent || n.value || "").trim().slice(0, 50) };
      }
      case "find": {
        const txt = String(msg.text || "").toLowerCase();
        const els = [...document.querySelectorAll("a,button,[role=button],[role=link],input,select,textarea,[contenteditable]")];
        return els.filter((e) => (e.textContent || e.value || "").toLowerCase().includes(txt))
          .slice(0, 40)
          .map((e) => ({
            tag: e.tagName,
            text: (e.textContent || e.value || "").trim().replace(/\s+/g, " ").slice(0, 60),
            id: e.id || "",
            cls: (typeof e.className === "string" ? e.className : "").slice(0, 80),
            href: (e.getAttribute && e.getAttribute("href")) || "",
          }));
      }
      case "fileinputs": {
        return {
          files: [...document.querySelectorAll('input[type="file"]')].map((e) => ({
            id: e.id || "", name: e.name || "", cls: (typeof e.className === "string" ? e.className : "").slice(0, 60),
            multiple: !!e.multiple, accept: e.accept || "",
          })),
          iframes: [...document.querySelectorAll("iframe")].map((e) => ({ id: e.id || "", src: (e.src || "").slice(0, 90) })),
        };
      }
      case "type": {
        const n = el(msg.selector);
        n.focus();
        const value = msg.text || "";
        if (n.isContentEditable) {
          n.textContent = value;
        } else if ("value" in n) {
          const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(n), "value")?.set;
          if (setter) setter.call(n, value); else n.value = value;
        }
        n.dispatchEvent(new Event("input", { bubbles: true }));
        n.dispatchEvent(new Event("change", { bubbles: true }));
        return { typed: true };
      }
      case "eval": {
        const r = (0, eval)(msg.js);
        return { result: JSON.parse(JSON.stringify(r ?? null)) };
      }
      default:
        throw new Error("unknown action: " + msg.action);
    }
  }

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    handle(msg)
      .then((result) => sendResponse({ ok: true, result }))
      .catch((e) => sendResponse({ ok: false, error: String((e && e.message) || e) }));
    return true;
  });
}

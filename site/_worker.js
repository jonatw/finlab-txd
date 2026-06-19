// Cloudflare Pages advanced mode。_headers / _redirects 在 advanced mode 會被忽略 → header 全在這裡設。
// env.ASSETS.fetch() 的 headers 是 immutable → 必須重建 Response 才能加 header。
// 政策:① pages.dev → 正式網域 301;② 無狀態 MCP 端點 /mcp(read-only 代理靜態 JSON);
//       ③ 擋 AI 訓練爬蟲(best-effort);④ HTML 加 noindex;⑤ /data 等 API 開 CORS。
// MCP:目標 stable spec 2025-06-18(Streamable HTTP / JSON-RPC 2.0),stateless(不發 session id)→ 適合單一 Pages worker。
//      2026-07-28 的 stateless RC 尚未定案(今日 < 該日),故沿用 2025-06-18。

const TRAIN_BOTS_403 = [
  "GPTBot", "ClaudeBot", "CCBot", "Meta-ExternalAgent", "Amazonbot", "Bytespider",
];
function isTrainBot(request) {
  const u = (request.headers.get("user-agent") || "").toLowerCase();
  return TRAIN_BOTS_403.some((t) => u.includes(t.toLowerCase()));
}

// ── MCP ───────────────────────────────────────────────────────────────────
const MCP_PROTOCOL = "2025-06-18";
const MCP_TOOLS = [
  { name: "get_signal", description: "今日 TXD 台指期目標槓桿訊號:target_exposure(0/.33/.67/1/2)、spine、MOVE、DTP、freshness、changed。研究用,非投資建議。", inputSchema: { type: "object", properties: {} } },
  { name: "get_metrics", description: "滾動窗(全期/2016/OOS/1年)Sharpe / CAGR / MaxDD 時序。注意:全期 Sharpe 被歷史錨住、偵測不到衰退。", inputSchema: { type: "object", properties: {} } },
  { name: "get_health", description: "paper-lane 健康:實單 vs block-bootstrap 期望帶(p5..p95)+ 回撤斷路器(當前 DD vs 歷史 MDD)。", inputSchema: { type: "object", properties: {} } },
  { name: "get_nav", description: "完整 NAV 曲線(1999~)+ 0050/0056/00631L 對照。last_n>0 只回最後 N 個交易日以省 token。", inputSchema: { type: "object", properties: { last_n: { type: "integer", minimum: 0, description: "只取最後 N 天;0 或省略=全部(~393KB)" } } } },
];

async function readJson(env, request, path) {
  const r = await env.ASSETS.fetch(new Request(new URL(path, request.url)));
  return await r.json();
}

async function callTool(env, request, name, args) {
  if (name === "get_signal") return await readJson(env, request, "/data/signal.json");
  if (name === "get_metrics") return await readJson(env, request, "/data/metrics.json");
  if (name === "get_health") return await readJson(env, request, "/data/health.json");
  if (name === "get_nav") {
    const nav = await readJson(env, request, "/data/nav.json");
    const n = (args && args.last_n) | 0;
    if (n > 0 && nav.series) {
      const out = {};
      for (const k in nav.series) {
        out[k] = Array.isArray(nav.series[k]) ? nav.series[k].slice(-n) : nav.series[k];
      }
      return { ...nav, series: out, _note: `last ${n} sessions only` };
    }
    return nav;
  }
  throw new Error("unknown tool: " + name);
}

const rpcResult = (id, result) => ({ jsonrpc: "2.0", id, result });
const rpcError = (id, code, message) => ({ jsonrpc: "2.0", id, error: { code, message } });

async function handleMcp(request, env, cors) {
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
  if (request.method === "GET") {
    return new Response("TXD MCP endpoint — POST JSON-RPC 2.0 here. Stateless (no server→client stream).\n",
      { status: 405, headers: { ...cors, "content-type": "text/plain; charset=utf-8" } });
  }
  if (request.method !== "POST") return new Response(null, { status: 405, headers: cors });

  let body;
  try { body = await request.json(); } catch (e) {
    return mcpJson(rpcError(null, -32700, "parse error"), cors);
  }
  const msgs = Array.isArray(body) ? body : [body];
  const responses = [];
  for (const m of msgs) {
    if (m.method === "initialize") {
      responses.push(rpcResult(m.id, {
        protocolVersion: (m.params && m.params.protocolVersion) || MCP_PROTOCOL,
        capabilities: { tools: {} },
        serverInfo: { name: "txd-dashboard", version: "1.0.0" },
        instructions: "Read-only TXD 台指期擇時策略儀表板。研究用,非投資建議。",
      }));
    } else if (m.method === "tools/list") {
      responses.push(rpcResult(m.id, { tools: MCP_TOOLS }));
    } else if (m.method === "tools/call") {
      try {
        const data = await callTool(env, request, m.params.name, m.params.arguments || {});
        responses.push(rpcResult(m.id, { content: [{ type: "text", text: JSON.stringify(data) }], isError: false }));
      } catch (e) {
        responses.push(rpcResult(m.id, { content: [{ type: "text", text: "error: " + e.message }], isError: true }));
      }
    } else if (m.method === "ping") {
      responses.push(rpcResult(m.id, {}));
    } else if (m.method && m.method.startsWith("notifications/")) {
      // notification → no response
    } else if (m.id !== undefined && m.id !== null) {
      responses.push(rpcError(m.id, -32601, "method not found: " + m.method));
    }
  }
  if (responses.length === 0) return new Response(null, { status: 202, headers: cors });
  return mcpJson(Array.isArray(body) ? responses : responses[0], cors);
}

function mcpJson(obj, cors) {
  return new Response(JSON.stringify(obj), { status: 200, headers: { ...cors, "content-type": "application/json" } });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // ① 預設網域 → 正式網域
    if (url.hostname === "finlab-txd.pages.dev") {
      return Response.redirect("https://txd.av8r.tw" + url.pathname + url.search, 301);
    }

    // ② MCP 端點(放在訓練 bot 擋之前 → 不被 UA 誤擋)
    if (url.pathname === "/mcp") {
      const cors = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Mcp-Session-Id, Mcp-Protocol-Version, Authorization",
        "Access-Control-Expose-Headers": "Mcp-Session-Id",
      };
      return handleMcp(request, env, cors);
    }

    // ③ AI 訓練爬蟲:best-effort 403(robots.txt 也 Disallow;UA 可偽造,非安全邊界)
    if (isTrainBot(request)) {
      return new Response(
        "This dashboard is not available for AI-training crawlers. See /llms.txt and /robots.txt.\n",
        { status: 403, headers: { "content-type": "text/plain; charset=utf-8" } },
      );
    }

    // 取靜態資源,再重建 Response 加 header(immutable headers gotcha)
    const assetResp = await env.ASSETS.fetch(request);
    const headers = new Headers(assetResp.headers);
    const path = url.pathname;

    // ④ noindex 只加在 HTML(不加在 JSON data — 要讓 agent / AI search 自由讀)
    const isHtml =
      path === "/" || path.endsWith(".html") ||
      (headers.get("content-type") || "").includes("text/html");
    if (isHtml) {
      headers.set("X-Robots-Tag", "noindex, nofollow, noai, noimageai");
    }

    // ⑤ data / API 開 CORS
    const isApi =
      path.startsWith("/data/") || path === "/openapi.json" ||
      path.startsWith("/.well-known/") || path === "/feed.json" || path === "/feed.xml";
    if (isApi) {
      headers.set("Access-Control-Allow-Origin", "*");
      headers.set("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
      headers.set("Access-Control-Allow-Headers", "Content-Type, If-None-Match, If-Modified-Since");
      headers.set("Access-Control-Expose-Headers", "ETag, Last-Modified, Content-Type");
      headers.set("Vary", "Origin");
      if (!headers.has("Cache-Control")) {
        headers.set("Cache-Control", "public, max-age=3600, stale-while-revalidate=86400");
      }
      if (request.method === "OPTIONS") {
        return new Response(null, { status: 204, headers });
      }
    }

    // 靜態 vendor / 字型:內容穩定、極少變 → 長快取(改 Chart.js 版或字型時加 ?v= 失效)
    if (path.startsWith("/vendor/") || path.startsWith("/fonts/")) {
      headers.set("Cache-Control", "public, max-age=2592000");
    }

    return new Response(assetResp.body, {
      status: assetResp.status,
      statusText: assetResp.statusText,
      headers,
    });
  },
};

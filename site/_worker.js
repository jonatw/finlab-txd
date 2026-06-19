// Cloudflare Pages advanced mode。_headers / _redirects 在 advanced mode 會被忽略 → header 全在這裡設。
// env.ASSETS.fetch() 的 headers 是 immutable → 必須重建 Response 才能加 header。
// 政策:① pages.dev → 正式網域 301;② 擋 AI 訓練爬蟲(best-effort,UA 可偽造);
//       ③ HTML 加 X-Robots-Tag: noindex(讓 Google/Bing 爬到但不收進 SERP);④ /data 等 API 開 CORS。

const TRAIN_BOTS_403 = [
  "GPTBot", "ClaudeBot", "CCBot", "Meta-ExternalAgent", "Amazonbot", "Bytespider",
];
function isTrainBot(request) {
  const u = (request.headers.get("user-agent") || "").toLowerCase();
  return TRAIN_BOTS_403.some((t) => u.includes(t.toLowerCase()));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // ① 預設網域 → 正式網域
    if (url.hostname === "finlab-txd.pages.dev") {
      return Response.redirect("https://txd.av8r.tw" + url.pathname + url.search, 301);
    }

    // ② AI 訓練爬蟲:best-effort 403(robots.txt 也 Disallow;UA 可偽造,非安全邊界)
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

    // ③ noindex 只加在 HTML(不加在 JSON data — 要讓 agent / AI search 自由讀)
    const isHtml =
      path === "/" || path.endsWith(".html") ||
      (headers.get("content-type") || "").includes("text/html");
    if (isHtml) {
      headers.set("X-Robots-Tag", "noindex, nofollow, noai, noimageai");
    }

    // ④ data / API 開 CORS,讓瀏覽器端 agent 可跨域抓;資料一天一變 → 可快取一小時
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

    return new Response(assetResp.body, {
      status: assetResp.status,
      statusText: assetResp.statusText,
      headers,
    });
  },
};

// Cloudflare Pages advanced mode:把預設的 finlab-txd.pages.dev 301 導到正式網域,
// 其餘(txd.av8r.tw 及 preview hash 子網域)照常由 static assets 服務。
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.hostname === "finlab-txd.pages.dev") {
      return Response.redirect("https://txd.av8r.tw" + url.pathname + url.search, 301);
    }
    return env.ASSETS.fetch(request);
  },
};

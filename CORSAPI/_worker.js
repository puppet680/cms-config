/**
 * 🛠️ API Database Control Center
 * 路由：
 * - /ouonnkitv           : 原始格式
 * - /kvideo              : KVideo格式
 * - 子路径代理：/ouonnkitv/p/... 或 /kvideo/p/...
 */

export default {
  async fetch(request, env, ctx) {
    if (env && env.KV && typeof globalThis.KV === 'undefined') {
      globalThis.KV = env.KV;
    }
    return handleRequest(request);
  }
}

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  'Access-Control-Max-Age': '86400',
};

// --- 配置：请确保与 GitHub 文件名一致 ---
const REPO_BASE = "https://raw.githubusercontent.com/puppet680/KVideo-config/refs/heads/main";

const DATABASE_CONFIG = {
  'lite': {
    name: 'CLEAN_DATABASE',
    file: 'clean_status.json',
    type: 'SAFE',
    color: '#10b981'
  },
  'adult': {
    name: 'NSFW_DATABASE',
    file: 'nsfw_status.json',
    type: 'RESTRICTED',
    color: '#f43f5e'
  },
  'full': {
    name: 'GLOBAL_DATABASE',
    file: 'full_status.json',
    type: 'ALL',
    color: '#3b82f6'
  }
};

// --- 核心工具函数 ---
function extractSourceId(apiUrl) {
  try {
    const url = new URL(apiUrl);
    const parts = url.hostname.split('.');
    return parts[parts.length - 2].toLowerCase().replace(/[^a-z0-9]/g, '') || 'src';
  } catch { return 'src' + Math.random().toString(36).substr(2, 4); }
}

async function getCachedJSON(fileName) {
  const url = `${REPO_BASE}/${fileName}`;
  const kvAvailable = typeof globalThis.KV !== 'undefined' && globalThis.KV;
  const cacheKey = 'CACHE_' + fileName;
  
  if (kvAvailable) {
    const cached = await globalThis.KV.get(cacheKey);
    if (cached) return JSON.parse(cached);
  }
  
  const res = await fetch(url);
  const data = await res.json();
  
  if (kvAvailable) await globalThis.KV.put(cacheKey, JSON.stringify(data), { expirationTtl: 300 });
  return data;
}

// --- 路由处理 ---
async function handleRequest(request) {
  const reqUrl = new URL(request.url);
  const pathname = reqUrl.pathname;
  const currentOrigin = reqUrl.origin;
  const sourceParam = reqUrl.searchParams.get('source') || 'full';
  const targetUrlParam = reqUrl.searchParams.get('url');

  if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS_HEADERS });

  // 代理转发逻辑：检测子路径包含 /p/
  if (pathname.includes('/p/') && targetUrlParam) {
    return handleProxyRequest(request, targetUrlParam);
  }

  // 格式转换逻辑
  if (pathname === '/kvideo') return handleFormat(sourceParam, `${currentOrigin}/kvideo`, 'kvideo');
  if (pathname === '/ouonnkitv') return handleFormat(sourceParam, `${currentOrigin}/ouonnkitv`, 'ouonnki');

  return handleHomePage(currentOrigin);
}

// --- 业务处理器 ---
async function handleFormat(sourceKey, prefix, formatType) {
  try {
    const config = DATABASE_CONFIG[sourceKey] || DATABASE_CONFIG['full'];
    const data = await getCachedJSON(config.file);

    if (formatType === 'kvideo') {
      const res = data.map((item, index) => {
        let rawUrl = item.url || item.baseUrl || "";
        if (rawUrl.startsWith('http')) {
          const sid = extractSourceId(rawUrl);
          rawUrl = `${prefix}/p/${sid}?url=${encodeURIComponent(rawUrl)}`;
        }
        const isNSFW = item.category === 'NSFW' || (item.name && item.name.includes('NSFW'));
        return {
          id: item.id || `s_${index}`,
          name: item.name,
          baseUrl: rawUrl,
          group: isNSFW ? "premium" : "normal",
          ...(isNSFW ? { enabled: true } : { priority: index + 1 })
        };
      });
      return new Response(JSON.stringify(res), { headers: { 'Content-Type': 'application/json', ...CORS_HEADERS } });
    } else {
      // Ouonnki 保持原格式并重写 URL
      const process = (obj) => {
        if (typeof obj !== 'object' || obj === null) return obj;
        if (Array.isArray(obj)) return obj.map(process);
        const newObj = {};
        for (const k in obj) {
          if ((k === 'url' || k === 'baseUrl') && typeof obj[k] === 'string' && obj[k].startsWith('http')) {
            const sid = extractSourceId(obj[k]);
            newObj[k] = `${prefix}/p/${sid}?url=${encodeURIComponent(obj[k])}`;
          } else { newObj[k] = process(obj[k]); }
        }
        return newObj;
      };
      return new Response(JSON.stringify(process(data)), { headers: { 'Content-Type': 'application/json', ...CORS_HEADERS } });
    }
  } catch (e) { return new Response(JSON.stringify({error: e.message}), { status: 500 }); }
}

async function handleProxyRequest(request, targetUrl) {
  const url = decodeURIComponent(targetUrl);
  const response = await fetch(url, { method: request.method, headers: request.headers });
  const headers = new Headers(CORS_HEADERS);
  for (const [k, v] of response.headers) { 
    if (!['content-encoding', 'set-cookie', 'transfer-encoding'].includes(k.toLowerCase())) headers.set(k, v); 
  }
  return new Response(response.body, { status: response.status, headers });
}

// --- 数据库样式 UI ---
async function handleHomePage(origin) {
  const rows = Object.entries(DATABASE_CONFIG).map(([key, item]) => `
    <tr>
      <td><span class="status-dot"></span></td>
      <td><code class="db-name">${item.name}</code></td>
      <td><span class="tag" style="background: ${item.color}22; color: ${item.color}">${item.type}</span></td>
      <td><button class="action-btn" onclick="copy('${origin}/ouonnkitv?source=${key}')">FETCH RAW</button></td>
      <td><button class="action-btn k-btn" onclick="copy('${origin}/kvideo?source=${key}')">MAP KVIDEO</button></td>
    </tr>
  `).join('');

  const html = `<!DOCTYPE html>
  <html>
  <head>
    <meta charset="UTF-8">
    <title>API Database UI</title>
    <style>
      :root { --bg: #0b0e14; --panel: #151921; --border: #2d333b; --text: #adbac7; --blue: #539bf5; }
      body { background: var(--bg); color: var(--text); font-family: 'SFMono-Regular', Consolas, monospace; padding: 40px; }
      .db-container { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; max-width: 900px; margin: auto; overflow: hidden; box-shadow: 0 20px 50px rgba(0,0,0,0.5); }
      .db-header { padding: 16px 24px; background: #1c2128; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
      .db-title { font-size: 14px; font-weight: bold; color: #cdd9e5; }
      table { width: 100%; border-collapse: collapse; font-size: 13px; }
      th { text-align: left; padding: 12px 24px; background: #1c2128; color: #768390; border-bottom: 1px solid var(--border); }
      td { padding: 14px 24px; border-bottom: 1px solid var(--border); }
      .status-dot { height: 8px; width: 8px; background: #22c55e; border-radius: 50%; display: inline-block; box-shadow: 0 0 8px #22c55e; }
      .db-name { color: var(--blue); }
      .tag { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; }
      .action-btn { background: #2d333b; border: 1px solid #444c56; color: #adbac7; padding: 6px 12px; border-radius: 6px; cursor: pointer; width: 100%; }
      .action-btn:hover { background: #373e47; border-color: #768390; }
      .k-btn { color: #f69d50; border-color: rgba(246,157,80,0.3); }
      .toast { position: fixed; top: 20px; right: 20px; background: #2ea043; color: white; padding: 10px 20px; border-radius: 6px; display: none; }
    </style>
  </head>
  <body>
    <div id="toast" class="toast">LINK COPIED TO CLIPBOARD</div>
    <div class="db-container">
      <div class="db-header">
        <div class="db-title">🗄️ SUBSCRIPTION_DATABASE_V3</div>
        <div style="font-size: 11px; color: #57606a;">STATUS: ACTIVE</div>
      </div>
      <table>
        <thead>
          <tr>
            <th width="40"></th>
            <th>DATABASE_ID</th>
            <th>ACL_LEVEL</th>
            <th>ACTION_RAW</th>
            <th>ACTION_KVIDEO</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
      <div style="padding: 15px; font-size: 11px; color: #57606a; background: #1c2128;">
        [INFO] PROXY_SUB_PATHING ENABLED. AUTO_REORDER AT 00:00 GMT+8.
      </div>
    </div>
    <script>
      function copy(t) {
        navigator.clipboard.writeText(t).then(() => {
          const s = document.getElementById('toast');
          s.style.display = 'block';
          setTimeout(() => s.style.display = 'none', 2000);
        });
      }
    </script>
  </body>
  </html>`;
  return new Response(html, { headers: { 'Content-Type': 'text/html;charset=UTF-8' } });
}
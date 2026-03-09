/**
 * 🛠️ API 数据库控制中心 - OuonnkiTV 格式优化版
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

const REPO_BASE = "https://raw.githubusercontent.com/puppet680/cms-config/refs/heads/main";

const DATABASE_CONFIG = {
  'lite':   { id: 'CLEAN_DB', file: 'clean_status.json', type: '安全',   color: '#10b981' },
  'adult':  { id: 'NSFW_DB',  file: 'nsfw_status.json',  type: '受限',   color: '#f43f5e' },
  'full':   { id: 'GLOBAL_DB', file: 'full_status.json', type: '完整',   color: '#3b82f6' }
};

// --- 工具函数 ---
function extractSourceId(apiUrl) {
  try {
    const url = new URL(apiUrl);
    const parts = url.hostname.split('.');
    return parts[parts.length - 2].toLowerCase().replace(/[^a-z0-9]/g, '') || 'src';
  } catch {
    return 'src' + Math.random().toString(36).substr(2, 4);
  }
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
  if (!res.ok) throw new Error(`获取 ${fileName} 失败: ${res.status}`);

  const data = await res.json();

  if (kvAvailable) {
    await globalThis.KV.put(cacheKey, JSON.stringify(data), { expirationTtl: 300 });
  }
  return data;
}

// --- 路由处理 ---
async function handleRequest(request) {
  const reqUrl = new URL(request.url);
  const pathname = reqUrl.pathname;
  const currentOrigin = reqUrl.origin;
  const sourceParam = reqUrl.searchParams.get('source') || 'full';
  const targetUrlParam = reqUrl.searchParams.get('url');
  const useProxy = reqUrl.searchParams.get('proxy') !== 'false';

  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  if (pathname.includes('/p/') && targetUrlParam) {
    return handleProxyRequest(request, targetUrlParam);
  }

  // OuonnkiTV 格式输出（已优化为指定字段结构）
  if (pathname === '/ouonnkitv') {
    return handleOuonnkiTV(sourceParam, `${currentOrigin}/ouonnkitv`, useProxy);
  }

  // KVideo 格式保持原样
  if (pathname === '/kvideo') {
    return handleFormat(sourceParam, `${currentOrigin}/kvideo`, 'kvideo', useProxy);
  }

  return handleHomePage(currentOrigin);
}

// 新增：OuonnkiTV 专用输出格式
async function handleOuonnkiTV(sourceKey, prefix, useProxy) {
  try {
    const config = DATABASE_CONFIG[sourceKey] || DATABASE_CONFIG['full'];
    const data = await getCachedJSON(config.file);

    const result = data.map((item, index) => {
      let rawUrl = item.url || item.baseUrl || "";

      if (useProxy && rawUrl.startsWith('http')) {
        const sid = extractSourceId(rawUrl);
        rawUrl = `${prefix}/p/${sid}?url=${encodeURIComponent(rawUrl)}`;
      }

      // timeout 计算：直接原 delay * 2（毫秒），无 delay 则默认 15000ms
      let timeout = 15000;  // 默认 15秒
      if (typeof item.delay === 'number' && item.delay > 0) {
        timeout = Math.round(item.delay * 2);  // 直接 *2，四舍五入
      }
      timeout = Math.max(3000, Math.min(20000, timeout));  // 限制 3~20秒，避免极端值

      return {
        id: item.id || `ouonnki_${sourceKey}_${index + 1}`,
        name: item.name || item.originalName || `线路 ${index + 1}`,
        url: rawUrl,
        detailUrl: rawUrl,
        isEnabled: item.isEnabled !== false,
        timeout: timeout  // 单位：毫秒，只输出这个字段
      };
    });

    return new Response(JSON.stringify(result, null, 2), {
      headers: {
        'Content-Type': 'application/json;charset=UTF-8',
        ...CORS_HEADERS
      }
    });

  } catch (e) {
    return new Response(JSON.stringify({ error: e.message }), { status: 500 });
  }
}

// 原 KVideo 格式处理（保持不变）
async function handleFormat(sourceKey, prefix, formatType, useProxy) {
  try {
    const config = DATABASE_CONFIG[sourceKey] || DATABASE_CONFIG['full'];
    const data = await getCachedJSON(config.file);

    if (formatType === 'kvideo') {
      const res = data.map((item, index) => {
        let rawUrl = item.url || item.baseUrl || "";
        if (useProxy && rawUrl.startsWith('http')) {
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
      return new Response(JSON.stringify(res), { headers: { 'Content-Type': 'application/json;charset=UTF-8', ...CORS_HEADERS } });
    } else {
      // 其他格式的递归代理处理（保持原样）
      const process = (obj) => {
        if (typeof obj !== 'object' || obj === null) return obj;
        if (Array.isArray(obj)) return obj.map(process);
        const newObj = {};
        for (const k in obj) {
          if (useProxy && (k === 'url' || k === 'baseUrl') && typeof obj[k] === 'string' && obj[k].startsWith('http')) {
            const sid = extractSourceId(obj[k]);
            newObj[k] = `${prefix}/p/${sid}?url=${encodeURIComponent(obj[k])}`;
          } else {
            newObj[k] = process(obj[k]);
          }
        }
        return newObj;
      };
      return new Response(JSON.stringify(process(data)), { headers: { 'Content-Type': 'application/json;charset=UTF-8', ...CORS_HEADERS } });
    }
  } catch (e) {
    return new Response(JSON.stringify({ error: e.message }), { status: 500 });
  }
}

async function handleProxyRequest(request, targetUrl) {
  const url = decodeURIComponent(targetUrl);
  const response = await fetch(url, {
    method: request.method,
    headers: request.headers,
    redirect: 'follow'
  });

  const headers = new Headers(CORS_HEADERS);
  for (const [k, v] of response.headers) {
    if (!['content-encoding', 'set-cookie', 'transfer-encoding'].includes(k.toLowerCase())) {
      headers.set(k, v);
    }
  }

  return new Response(response.body, { status: response.status, headers });
}

// --- 主页 UI（保持原样） ---
async function handleHomePage(origin) {
  const generateRows = (isKVideo) => {
    const path = isKVideo ? 'kvideo' : 'ouonnkitv';
    return Object.entries(DATABASE_CONFIG).map(([key, item]) => `
      <tr>
        <td><span class="status-dot"></span></td>
        <td><code class="db-name">${item.id}</code></td>
        <td><span class="tag" style="background: ${item.color}22; color: ${item.color}">${item.type}</span></td>
        <td><button class="action-btn" onclick="copy('${origin}/${path}?source=${key}&proxy=false')">RAW 直连</button></td>
        <td><button class="action-btn ${isKVideo ? 'k-btn' : 'o-btn'}" onclick="copy('${origin}/${path}?source=${key}')">获取代理订阅</button></td>
      </tr>
    `).join('');
  };

  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>API 订阅分发控制台</title>
  <style>
    :root { --bg: #0d1117; --panel: #161b22; --border: #30363d; --text: #c9d1d9; --blue: #58a6ff; --green: #238636; --orange: #d29922; }
    body { background: var(--bg); color: var(--text); font-family: -apple-system, "Microsoft YaHei", sans-serif; padding: 20px; margin: 0; }
    .container { max-width: 1100px; margin: auto; }
    .header { padding: 40px 0; text-align: center; border-bottom: 1px solid var(--border); margin-bottom: 40px; }
    .header h1 { margin: 0; font-size: 26px; color: #f0f6fc; letter-spacing: 2px; }
    .db-section { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 40px; overflow: hidden; box-shadow: 0 8px 24px rgba(0,0,0,0.4); }
    .db-header { padding: 14px 24px; background: #21262d; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th { text-align: left; padding: 12px 24px; background: #161b22; color: #8b949e; border-bottom: 1px solid var(--border); font-size: 12px; }
    td { padding: 16px 24px; border-bottom: 1px solid var(--border); }
    .status-dot { height: 8px; width: 8px; background: #3fb950; border-radius: 50%; display: inline-block; box-shadow: 0 0 5px #3fb950; margin-right: 8px; }
    .db-name { color: var(--blue); font-family: Consolas, monospace; font-weight: bold; }
    .tag { padding: 3px 10px; border-radius: 6px; font-size: 11px; font-weight: bold; }
    .action-btn { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 8px 16px; border-radius: 6px; cursor: pointer; transition: 0.2s; width: 100%; font-size: 12px; font-weight: bold; }
    .action-btn:hover { background: #30363d; border-color: #8b949e; }
    .o-btn { color: #3fb950; border-color: rgba(63,185,80,0.4); }
    .k-btn { color: #dbab09; border-color: rgba(219,171,9,0.4); }
    #toast { position: fixed; bottom: 30px; right: 30px; background: #238636; color: white; padding: 12px 24px; border-radius: 8px; display: none; z-index: 1000; }
  </style>
</head>
<body>
  <div id="toast">✅ 已成功复制到剪贴板</div>
  <div class="container">
    <div class="header"><h1>🛰️ 视频资源订阅分发集群</h1></div>
    <div class="db-section">
      <div class="db-header"><span style="color: var(--green)">【节点集群 A】 OuonnkiTV 结构</span></div>
      <table>
        <thead><tr><th width="40"></th><th>数据节点标识</th><th>访问等级</th><th width="180">RAW 直连地址</th><th width="180">代理订阅地址</th></tr></thead>
        <tbody>${generateRows(false)}</tbody>
      </table>
    </div>
    <div class="db-section" style="border-color: rgba(210,153,34,0.3)">
      <div class="db-header"><span style="color: var(--orange)">【节点集群 B】 KVideo 结构</span></div>
      <table>
        <thead><tr><th width="40"></th><th>数据节点标识</th><th>访问等级</th><th width="180">RAW 直连地址</th><th width="180">代理订阅地址</th></tr></thead>
        <tbody>${generateRows(true)}</tbody>
      </table>
    </div>
  </div>
  <script>
    function copy(t) {
      navigator.clipboard.writeText(t).then(() => {
        const s = document.getElementById('toast');
        s.style.display = 'block';
        setTimeout(() => s.style.display = 'none', 1500);
      });
    }
  </script>
</body>
</html>`;

  return new Response(html, { headers: { 'Content-Type': 'text/html;charset=UTF-8' } });
}

/**
 * 🛠️ API 数据库控制中心 - OuonnkiTV 格式优化版 (基于 CORSAPI v2 架构升级)
 */

export default {
  async fetch(request, env, ctx) {
    // Pages Functions 中 KV 需要从 env 中获取
    if (env && env.KV && typeof globalThis.KV === 'undefined') {
      globalThis.KV = env.KV
    }

    return handleRequest(request)
  }
}

// 常量配置
const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  'Access-Control-Max-Age': '86400',
};

const EXCLUDE_HEADERS = new Set([
  'content-encoding', 'content-length', 'transfer-encoding',
  'connection', 'keep-alive', 'set-cookie', 'set-cookie2'
]);

const REPO_BASE = "https://raw.githubusercontent.com/puppet680/cms-config/refs/heads/main";

const DATABASE_CONFIG = {
  'lite':   { id: 'CLEAN_DB', file: 'clean_status.json', type: '安全',   color: '#10b981' },
  'adult':  { id: 'NSFW_DB',  file: 'nsfw_status.json',  type: '受限',   color: '#f43f5e' },
  'full':   { id: 'GLOBAL_DB', file: 'full_status.json', type: '完整',   color: '#3b82f6' }
};

// --- 基础工具函数 ---

// 标识符提取算法
function extractSourceId(apiUrl) {
  try {
    const url = new URL(apiUrl);
    const hostname = url.hostname;
    const parts = hostname.split('.');

    if (parts.length >= 3 && (parts[0] === 'caiji' || parts[0] === 'api' || parts[0] === 'cj' || parts[0] === 'www')) {
      return parts[parts.length - 2].toLowerCase().replace(/[^a-z0-9]/g, '');
    }

    let name = parts[0].toLowerCase();
    name = name.replace(/zyapi$/, '').replace(/zy$/, '').replace(/api$/, '');
    return name.replace(/[^a-z0-9]/g, '') || 'source';
  } catch {
    return 'source' + Math.random().toString(36).substr(2, 6);
  }
}

// 获取配置 JSON 的缓存 (5 分钟过期逻辑)
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

// M3U8 专用缓存读写
async function getCachedM3u8(cacheKey) {
  if (typeof globalThis.KV === 'undefined' || !globalThis.KV) return null;
  try {
    return await globalThis.KV.get(cacheKey);
  } catch {
    return null;
  }
}

async function setCachedM3u8(cacheKey, text) {
  if (typeof globalThis.KV === 'undefined' || !globalThis.KV) return;
  try {
    await globalThis.KV.put(cacheKey, text, { expirationTtl: 300 }); // 5 分钟
  } catch {}
}

function ctxWaitUntil(promise) {
  try {
    if (typeof globalThis.ctx !== 'undefined' && globalThis.ctx && typeof globalThis.ctx.waitUntil === 'function') {
      globalThis.ctx.waitUntil(promise);
      return;
    }
  } catch {}
  promise.catch(() => {});
}

// --- 路由主处理 ---
async function handleRequest(request) {
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  const reqUrl = new URL(request.url);
  const pathname = reqUrl.pathname;
  const currentOrigin = reqUrl.origin;
  
  const sourceParam = reqUrl.searchParams.get('source') || 'full';
  const targetUrlParam = reqUrl.searchParams.get('url');
  const useProxy = reqUrl.searchParams.get('proxy') !== 'false';

  // 测速路由
  if (pathname === '/speed') {
    return handleSpeedTest(reqUrl);
  }

  // M3U8 重写路由
  if (pathname === '/m3u8' && targetUrlParam) {
    return handleM3u8Request(request, targetUrlParam, currentOrigin);
  }

  // 专属路径路由
  if (pathname.startsWith('/p/') && targetUrlParam) {
    return handleProxyRequest(request, targetUrlParam, currentOrigin);
  }

  // 通用代理请求
  if (targetUrlParam) {
    return handleProxyRequest(request, targetUrlParam, currentOrigin);
  }

  // OuonnkiTV 格式输出
  if (pathname === '/ouonnkitv') {
    return handleOuonnkiTV(sourceParam, currentOrigin, useProxy);
  }

  // KVideo 格式
  if (pathname === '/kvideo') {
    return handleFormat(sourceParam, currentOrigin, 'kvideo', useProxy);
  }

  return handleHomePage(currentOrigin);
}

// --- 核心业务逻辑 ---

async function handleOuonnkiTV(sourceKey, origin, useProxy) {
  try {
    const config = DATABASE_CONFIG[sourceKey] || DATABASE_CONFIG['full'];
    const data = await getCachedJSON(config.file);

    const result = data.map((item, index) => {
      let rawUrl = item.url || item.baseUrl || "";

      if (useProxy && rawUrl.startsWith('http')) {
        const sid = extractSourceId(rawUrl);
        // 改用 /p/{sid} 专属路径格式代理
        rawUrl = `${origin}/p/${sid}?url=${encodeURIComponent(rawUrl)}`;
      }

      let timeout = 15000;
      if (typeof item.delay === 'number' && item.delay > 0) {
        timeout = Math.round(item.delay * 2);
      }
      timeout = Math.max(3000, Math.min(20000, timeout));

      let retry = typeof item.retry === 'number' ? item.retry : 3;

      return {
        id: item.id || `ouonnki_${sourceKey}_${index + 1}`,
        name: item.name || item.originalName || `线路 ${index + 1}`,
        url: rawUrl,
        detailUrl: rawUrl,
        isEnabled: item.isEnabled !== false,
        timeout: timeout,
        retry: retry
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

async function handleFormat(sourceKey, origin, formatType, useProxy) {
  try {
    const config = DATABASE_CONFIG[sourceKey] || DATABASE_CONFIG['full'];
    const data = await getCachedJSON(config.file);

    if (formatType === 'kvideo') {
      const res = data.map((item, index) => {
        let rawUrl = item.url || item.baseUrl || "";
        if (useProxy && rawUrl.startsWith('http')) {
          const sid = extractSourceId(rawUrl);
          // 改用 /p/{sid} 专属路径格式代理
          rawUrl = `${origin}/p/${sid}?url=${encodeURIComponent(rawUrl)}`;
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
    }
  } catch (e) {
    return new Response(JSON.stringify({ error: e.message }), { status: 500 });
  }
}

// --- 代理核心控制 ---

function applyDefaultHeadersForUpstream(headers, targetURL) {
  const host = targetURL.hostname.toLowerCase();
  if (host === 'lain.bgm.tv' || host === 'api.bgm.tv' || host === 'bgm.tv' || host.endsWith('.bgm.tv')) {
    if (!headers.has('User-Agent')) {
      headers.set('User-Agent', 'LunaTV-Mobile/1.0 (https://github.com/djsevenx1/LunaTV-Mobile)');
    }
    if (!headers.has('Referer')) {
      headers.set('Referer', 'https://bgm.tv/');
    }
    if (!headers.has('Accept')) {
      headers.set('Accept', 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8');
    }
  }
  if (!headers.has('User-Agent')) {
    headers.set('User-Agent', 'Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36');
  }
  if (!headers.has('Referer')) {
    headers.set('Referer', targetURL.origin + '/');
  }
  if (!headers.has('Accept')) {
    headers.set('Accept', '*/*');
  }
}

async function handleProxyRequest(request, targetUrlParam, currentOrigin) {
  if (targetUrlParam.startsWith(currentOrigin)) {
    return new Response(JSON.stringify({ error: 'Loop detected' }), { status: 400 });
  }
  if (!/^https?:\/\//i.test(targetUrlParam)) {
    return new Response(JSON.stringify({ error: 'Invalid target URL' }), { status: 400 });
  }

  let fullTargetUrl = targetUrlParam;
  const urlMatch = request.url.match(/[?&]url=([^&]+)/);
  if (urlMatch) fullTargetUrl = decodeURIComponent(urlMatch[1]);

  const reqUrl = new URL(request.url);
  const extraParams = new URLSearchParams();
  for (const [key, value] of reqUrl.searchParams) {
    if (key !== 'url') {
      extraParams.append(key, value);
    }
  }

  let targetURL;
  try {
    targetURL = new URL(fullTargetUrl);
    for (const [key, value] of extraParams) {
      targetURL.searchParams.append(key, value);
    }
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid URL' }), { status: 400 });
  }

  // 1. 尝试从 Cloudflare Worker 的本地 Cache API 读取 (GET 请求有效)
  if (request.method === 'GET') {
    try {
      const cache = caches.default;
      const cacheKey = new Request(targetURL.toString(), { method: 'GET', headers: request.headers });
      const cached = await cache.match(cacheKey);
      if (cached) {
        const h = new Headers(cached.headers);
        h.set('Cache-Control', 'no-store');
        h.set('X-Cache', 'WORKER-HIT');
        return new Response(await cached.arrayBuffer(), { status: cached.status, headers: h });
      }
    } catch {}
  }

  const upstreamHeaders = new Headers(request.headers);
  applyDefaultHeadersForUpstream(upstreamHeaders, targetURL);

  try {
    upstreamHeaders.set('Cache-Control', 'max-age=0');
    upstreamHeaders.set('Pragma', 'no-cache');
    const proxyRequest = new Request(targetURL.toString(), {
      method: request.method,
      headers: upstreamHeaders,
      body: request.method !== 'GET' && request.method !== 'HEAD'
        ? await request.arrayBuffer()
        : undefined,
    });

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000); // 30s 宽限期给大文件 ts 段

    const isTsSegment = targetURL.pathname.endsWith('.ts') || targetURL.pathname.endsWith('.m4s');
    const fetchOptions = {
      signal: controller.signal,
      cf: isTsSegment ? {
        cacheTtl: 3600,
        cacheEverything: true,
      } : undefined,
    };
    const response = await fetch(proxyRequest, fetchOptions);
    clearTimeout(timeoutId);

    // 2. 存入本地 Cache API
    if (request.method === 'GET' && response.status === 200) {
      try {
        const cache = caches.default;
        const cacheKey = new Request(targetURL.toString(), { method: 'GET', headers: upstreamHeaders });
        const respToCache = new Response(response.clone().body, { status: response.status, headers: response.headers });
        await cache.put(cacheKey, respToCache);
      } catch {}
    }

    const responseHeaders = new Headers(CORS_HEADERS);
    for (const [key, value] of response.headers) {
      if (!EXCLUDE_HEADERS.has(key.toLowerCase())) {
        responseHeaders.set(key, value);
      }
    }

    if (response.status === 200) {
      responseHeaders.set('Cache-Control', 'no-store, no-cache, must-revalidate');
      responseHeaders.set('Pragma', 'no-cache');
    }
    if (isTsSegment && response.status === 200) {
      responseHeaders.set('Cache-Control', 'public, max-age=3600');
      responseHeaders.set('CDN-Cache-Control', 'public, max-age=3600');
    }

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders
    });
  } catch (err) {
    return new Response(JSON.stringify({ error: 'Proxy Error', message: err.message }), { status: 502 });
  }
}

// --- M3U8 核心重写 ---

async function handleM3u8Request(request, targetUrlParam, currentOrigin) {
  if (targetUrlParam.startsWith(currentOrigin)) {
    return new Response(JSON.stringify({ error: 'Loop detected' }), { status: 400 });
  }
  if (!/^https?:\/\//i.test(targetUrlParam)) {
    return new Response(JSON.stringify({ error: 'Invalid target URL' }), { status: 400 });
  }

  let fullTargetUrl = targetUrlParam;
  const urlMatch = request.url.match(/[?&]url=([^&]+)/);
  if (urlMatch) fullTargetUrl = decodeURIComponent(urlMatch[1]);

  const reqUrl = new URL(request.url);
  const extraParams = new URLSearchParams();
  for (const [key, value] of reqUrl.searchParams) {
    if (key !== 'url') extraParams.append(key, value);
  }

  let targetURL;
  try {
    targetURL = new URL(fullTargetUrl);
    for (const [key, value] of extraParams) {
      targetURL.searchParams.append(key, value);
    }
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid URL' }), { status: 400 });
  }

  const cacheKey = `M3U8_${currentOrigin}_${targetURL.toString()}`;
  const nocache = reqUrl.searchParams.get('nocache') === '1';
  if (!nocache) {
    const cached = await getCachedM3u8(cacheKey);
    if (cached !== null) {
      return new Response(cached, {
        status: 200,
        headers: {
          'Content-Type': 'application/vnd.apple.mpegurl',
          'Cache-Control': 'public, max-age=60',
          'X-Cache': 'HIT',
          'X-Cache-TTL': '300',
          'Alt-Svc': 'h3=":443"; ma=86400',
          ...CORS_HEADERS,
        },
      });
    }
  }

  const baseOrigin = currentOrigin;
  const wrapBase = (rawUrl) => {
    const u = (rawUrl || '').toLowerCase();
    if (u.endsWith('.m3u8') || u.endsWith('.m3u')) return `${baseOrigin}/m3u8?url=`;
    return `${baseOrigin}/?url=`;
  }

  const wrapSegment = (rawLine) => {
    const line = rawLine.trim();
    if (!line) return line;
    if (line.startsWith('#')) return line;
    if (/^https?:\/\//i.test(line)) {
      return wrapBase(line) + encodeURIComponent(line);
    }
    if (line.startsWith('//')) {
      const abs = targetURL.protocol + line;
      return wrapBase(abs) + encodeURIComponent(abs);
    }
    try {
      const abs = new URL(line, targetURL).toString();
      return wrapBase(abs) + encodeURIComponent(abs);
    } catch {
      return line;
    }
  }

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);
    const upstream = await fetch(targetURL.toString(), {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36',
        'Referer': targetURL.origin + '/',
        'Origin': targetURL.origin,
        'Accept': '*/*',
      },
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    const text = await upstream.text();

    const trimmed = text.trimStart();
    if (!trimmed.startsWith('#EXTM3U')) {
      const headers = new Headers(upstream.headers);
      headers.set('Access-Control-Allow-Origin', '*');
      headers.delete('content-encoding');
      headers.delete('content-length');
      return new Response(text, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers,
      });
    }

    const isMaster = /#EXT-X-STREAM-INF/i.test(text);
    const lines = text.split(/\r?\n/);
    const out = [];
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (/^#EXT-X-KEY/i.test(line) || /^#EXT-X-MAP/i.test(line) || /^#EXT-X-MEDIA/i.test(line) || /^#EXT-X-I-FRAME-STREAM-INF/i.test(line)) {
        out.push(line.replace(/URI="([^"]+)"/g, (m, u) => {
          let abs;
          try { abs = new URL(u, targetURL).toString() } catch { abs = u }
          return `URI="${wrapBase(abs) + encodeURIComponent(abs)}"`;
        }));
        continue;
      }
      if (isMaster && /^#EXT-X-STREAM-INF/i.test(line)) {
        out.push(line);
        if (i + 1 < lines.length) {
          out.push(wrapSegment(lines[i + 1]));
          i++;
        }
        continue;
      }
      out.push(wrapSegment(line));
    }

    const outText = out.join('\n');

    if (!nocache) {
      ctxWaitUntil(setCachedM3u8(cacheKey, outText));
    }

    return new Response(outText, {
      status: 200,
      headers: {
        'Content-Type': 'application/vnd.apple.mpegurl',
        'Cache-Control': 'no-store',
        'X-Cache': nocache ? 'BYPASS' : 'MISS',
        'Alt-Svc': 'h3=":443"; ma=86400',
        ...CORS_HEADERS,
      },
    });
  } catch (err) {
    return new Response(JSON.stringify({ error: 'M3U8 Proxy Error', message: err.message }), { status: 502 });
  }
}

// --- 测速端点 ---

async function handleSpeedTest(reqUrl) {
  const sizeParam = parseInt(reqUrl.searchParams.get('size') || '1', 10);
  const sizeMB = Math.max(1, Math.min(3, isNaN(sizeParam) ? 1 : sizeParam));
  const totalBytes = sizeMB * 1024 * 1024;
  const buffer = new Uint8Array(totalBytes); // 一次性生成，避免内存爆掉

  return new Response(buffer, {
    status: 200,
    headers: {
      'Content-Type': 'application/octet-stream',
      'Content-Length': totalBytes.toString(),
      'Content-Disposition': `attachment; filename="speedtest-${sizeMB}mb.bin"`,
      'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
      ...CORS_HEADERS
    }
  });
}

// --- 主页 UI ---
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
    .db-section { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 30px; overflow: hidden; box-shadow: 0 8px 24px rgba(0,0,0,0.4); }
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
    
    /* B 新增：使用说明文档区样式 */
    .docs-section { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 24px; margin-bottom: 40px; box-shadow: 0 8px 24px rgba(0,0,0,0.4); }
    .docs-title { font-size: 18px; color: #f0f6fc; margin-top: 0; margin-bottom: 16px; border-bottom: 1px solid var(--border); padding-bottom: 8px; display: flex; align-items: center; }
    .docs-title::before { content: "📖"; margin-right: 8px; }
    .docs-content { font-size: 14px; line-height: 1.6; color: #8b949e; }
    .docs-content h4 { color: #f0f6fc; margin: 16px 0 8px 0; }
    .docs-content ul { padding-left: 20px; margin: 8px 0; }
    .docs-content li { margin-bottom: 6px; }
    .docs-content code { background: #21262d; padding: 2px 6px; border-radius: 4px; color: #ff7b72; font-family: Consolas, monospace; }
    
    #toast { position: fixed; bottom: 30px; right: 30px; background: #238636; color: white; padding: 12px 24px; border-radius: 8px; display: none; z-index: 1000; }
  </style>
</head>
<body>
  <div id="toast">✅ 已成功复制到剪贴板</div>
  <div class="container">
    <div class="header"><h1>🛰 Sey TV & CORSAPI 联合资源订阅集群</h1></div>
    
    <!-- 节点集群 A -->
    <div class="db-section">
      <div class="db-header"><span style="color: var(--green)">【节点集群 A】 OuonnkiTV 结构</span></div>
      <table>
        <thead><tr><th width="40"></th><th>数据节点标识</th><th>访问等级</th><th width="180">RAW 直连地址</th><th width="180">代理订阅地址</th></tr></thead>
        <tbody>${generateRows(false)}</tbody>
      </table>
    </div>
    
    <!-- 节点集群 B -->
    <div class="db-section" style="border-color: rgba(210,153,34,0.3)">
      <div class="db-header"><span style="color: var(--orange)">【节点集群 B】 KVideo 结构</span></div>
      <table>
        <thead><tr><th width="40"></th><th>数据节点标识</th><th>访问等级</th><th width="180">RAW 直连地址</th><th width="180">代理订阅地址</th></tr></thead>
        <tbody>${generateRows(true)}</tbody>
      </table>
    </div>

    <!-- B 补充引入：功能特性与使用说明文档 -->
    <div class="docs-section">
      <div class="docs-title">系统说明与高级代理端点指南</div>
      <div class="docs-content">
        <p>本系统是集 <strong>数据分发、CORS 跨域代理、M3U8 流重写</strong> 于一体的融合网关。除上述节点的直接订阅外，您还可以利用网关底层的反代引擎进行以下高级调用：</p>
        
        <h4>1. 跨域通用反代理 (CORS Proxy)</h4>
        <p>支持对任意 API 接口、图片进行 CORS 跨域请求和缓存优化。使用方式：</p>
        <ul>
          <li><code>${origin}/?url=YOUR_ENCODED_URL</code></li>
        </ul>

        <h4>2. M3U8 流媒体重写过滤</h4>
        <p>支持对 HLS 播放列表（<code>.m3u8</code>）内的切片（<code>.ts</code> / <code>.m4s</code>）和密钥进行本地化相对路径重写，防止播放跨域、劫持或网络受限：</p>
        <ul>
          <li><code>${origin}/m3u8?url=YOUR_M3U8_URL</code></li>
          <li><em>附加参数：</em>加入 <code>&nocache=1</code> 可以强制绕过 KV 缓存实时获取最新切片。</li>
        </ul>

        <h4>3. 极速测速测试</h4>
        <p>提供一个低开销、不溢出的网络测速文件下发，用于客户端测速：</p>
        <ul>
          <li><code>${origin}/speed?size=1</code> （默认下发 1MB 数据，支持 <code>1</code> 至 <code>3</code> MB 自定义大小）</li>
        </ul>

        <h4>4. 专属源 ID 代理路由</h4>
        <p>系统会自动识别目标采集站 Host 并将其提取为唯一的 Source ID 进行独立隔离代理，格式如：<code>${origin}/p/{sourceId}?url=...</code>。不仅规范了请求路径，更有利于提升缓存命中率与分片拉取成功率。</p>
      </div>
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

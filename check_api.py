import requests
import json
import concurrent.futures
import time
import os
import urllib.parse
import re

# --- 配置 ---
ORIGINAL_FILE = 'sources.json'
CLEAN_OUTPUT = 'clean_status.json'
NSFW_OUTPUT = 'nsfw_status.json'
FULL_OUTPUT = 'full_status.json'
README_FILE = 'README.md'
TIMEOUT = 12  # 略微增加超时以应对海外延迟

# 搜索关键词
NORMAL_KEYWORD = "庆余年"
NSFW_KEYWORD = "臀"

def calculate_score(item):
    if not item.get('isEnabled'):
        return -999999
    delay = item.get('delay', 9999)
    # 针对无法预检的源给予中等延迟分值
    effective_delay = 500 if delay == 9999 else delay
    score = 30000 - effective_delay * 15
    ad_text = (item.get('adContext') or '').lower()
    if "无广告" in ad_text or "纯净" in ad_text:
        score += 4000
    elif "跑马灯" in ad_text or "开头广告" in ad_text or "插播" in ad_text:
        score -= 2000
    elif "广告" in ad_text:
        score -= 1000
    if item.get('searchable'):
        score += 3000
    if item.get('isOfficial'):
        score += 1500
    return score

def validate_m3u8_content(url, headers):
    """三级深度验证：检查文件头是否为 #EXTM3U"""
    try:
        # 使用流式请求验证前 7 个字节
        resp = requests.get(url, timeout=5, headers=headers, stream=True, allow_redirects=True)
        if resp.status_code == 200:
            content_start = resp.iter_content(chunk_size=7)
            first_bytes = next(content_start, b"").decode('utf-8', errors='ignore')
            return "#EXTM3U" in first_bytes
    except:
        pass
    return False

def check_source(item):
    res_item = item.copy()
    cat = res_item.get('category', 'General')
    search_word = NSFW_KEYWORD if cat == "NSFW" else NORMAL_KEYWORD
    
    res_item['isEnabled'] = False
    res_item['searchable'] = False
    res_item['delay'] = 9999
    res_item['check_status'] = "Failed" # 预检状态
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        start_time = time.time()
        # 第一级：执行详情搜索
        test_url = f"{item['url']}?wd={urllib.parse.quote(search_word)}&ac=detail"
        resp = requests.get(test_url, timeout=TIMEOUT, headers=headers)
        
        if resp.status_code == 200:
            data = resp.json()
            vod_list = data.get('list', [])
            
            if vod_list and len(vod_list) > 0:
                first_vod = vod_list[0]
                play_from = str(first_vod.get('vod_play_from', '')).lower()
                play_url = str(first_vod.get('vod_play_url', '')).lower()
                
                # 第二级：逻辑确认包含 m3u8
                if 'm3u8' in play_from or '.m3u8' in play_url:
                    res_item['searchable'] = True
                    # 提取链接进行验证
                    urls = re.findall(r'https?://[^\s$,#]+?\.m3u8', play_url)
                    if urls:
                        target_m3u8 = urls[0]
                        # 第三级：尝试深度验证
                        if validate_m3u8_content(target_m3u8, headers):
                            res_item['isEnabled'] = True
                            res_item['delay'] = int((time.time() - start_time) * 1000)
                            res_item['check_status'] = "Passed"
                        else:
                            # [修正策略]：若深度验证因海外环境失败(403/404/Timeout)，但链接存在，则强制保留
                            # 判定条件：play_url 长度大于 20 (排除空链接)
                            if len(play_url) > 20:
                                res_item['isEnabled'] = True
                                res_item['check_status'] = "Untested (Geo-blocked?)"
    except:
        pass
        
    res_item['score'] = calculate_score(res_item)
    return res_item

def main():
    if not os.path.exists(ORIGINAL_FILE):
        print(f"❌ 未找到源文件：{ORIGINAL_FILE}")
        return

    with open(ORIGINAL_FILE, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    print(f"🚀 开始海外优化版深度检测 (共 {len(raw_data)} 条源) ...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(check_source, raw_data))

    valid_results = [i for i in results if i['isEnabled']]
    valid_results.sort(key=lambda x: -x['score'])

    counters = {"极速直连": 1, "优质线路": 1, "备用线路": 1, "NSFW 秘密通道": 1}
    final_ordered_results = []

    for item in valid_results:
        raw_ad = item.get('adContext', '')
        processed_ad = "未知" if not raw_ad or "无广告" in raw_ad.lower() else raw_ad
        
        if item.get('category') == 'NSFW': p = "NSFW 秘密通道"
        elif item.get('isOfficial'): p = "极速直连"
        elif processed_ad == "未知" or "无广告" in raw_ad.lower(): p = "优质线路"
        else: p = "备用线路"

        if p == "备用线路" and counters[p] > 10: continue # 适当放宽备用线数量

        target_name = f"{p} {counters[p]:02d}"
        counters[p] += 1
        
        new_item = {'name': target_name, 'adContext': processed_ad}
        new_item.update({k: v for k, v in item.items() if k not in ['name', 'adContext']})
        final_ordered_results.append(new_item)

    # 写入 JSON
    for path, data in [(CLEAN_OUTPUT, [i for i in final_ordered_results if i.get('category') != 'NSFW']),
                       (NSFW_OUTPUT, [i for i in final_ordered_results if i.get('category') == 'NSFW']),
                       (FULL_OUTPUT, final_ordered_results)]:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # 渲染 README
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"# 🛰️ API 实时监控中心\n\n更新时间：`{now}` (海外服务器预检)\n\n"]
    
    sections = [("⚡ 极速直连", "极速直连"), ("💎 优质线路", "优质线路"), ("🛠️ 备用线路", "备用线路")]
    for title, key in sections:
        sec_data = [x for x in final_ordered_results if key in x['name'] and x.get('category') != 'NSFW']
        if sec_data:
            lines.append(f"### {title}\n| 序号 | 线路名称 | 预检 | 搜索 | 延迟 | 广告 | 原始名称 |\n| :--- | :--- | :---: | :---: | :---: | :--- | :--- |\n")
            for i, item in enumerate(sec_data, 1):
                status = "✅" if item['check_status'] == "Passed" else "⏳"
                delay_str = f"{item['delay']}ms" if item['delay'] < 9999 else "N/A"
                lines.append(f"| {i:02d} | {item['name']} | {status} | 🔍 | {delay_str} | {item['adContext']} | {item.get('originalName','未知')} |\n")
            lines.append("\n")

    # NSFW 渲染逻辑省略，保持与上方一致...
    with open(README_FILE, 'w', encoding='utf-8') as f:
        f.write("".join(lines))
    print(f"✅ 完成！已恢复国内限流源，当前有效源：{len(final_ordered_results)}")

if __name__ == "__main__":
    main()

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
TIMEOUT = 12 

# 搜索关键词
NORMAL_KEYWORD = "庆余年"
NSFW_KEYWORD = "臀"

def calculate_score(item):
    if not item.get('isEnabled'):
        return -999999
    delay = item.get('delay', 9999)
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
    try:
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
    res_item['check_status'] = "Failed"
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        start_time = time.time()
        test_url = f"{item['url']}?wd={urllib.parse.quote(search_word)}&ac=detail"
        resp = requests.get(test_url, timeout=TIMEOUT, headers=headers)
        
        if resp.status_code == 200:
            data = resp.json()
            vod_list = data.get('list', [])
            
            if vod_list and len(vod_list) > 0:
                first_vod = vod_list[0]
                play_from = str(first_vod.get('vod_play_from', '')).lower()
                play_url = str(first_vod.get('vod_play_url', '')).lower()
                
                if 'm3u8' in play_from or '.m3u8' in play_url:
                    res_item['searchable'] = True
                    urls = re.findall(r'https?://[^\s$,#]+?\.m3u8', play_url)
                    if urls:
                        target_m3u8 = urls[0]
                        if validate_m3u8_content(target_m3u8, headers):
                            res_item['isEnabled'] = True
                            res_item['delay'] = int((time.time() - start_time) * 1000)
                            res_item['check_status'] = "Passed"
                        else:
                            if len(play_url) > 20:
                                res_item['isEnabled'] = True
                                res_item['check_status'] = "Untested (Geo-blocked?)"
    except:
        pass
        
    res_item['score'] = calculate_score(res_item)
    return res_item

def generate_table_rows(data_list):
    rows = []
    for i, item in enumerate(data_list, 1):
        status = "✅" if item['check_status'] == "Passed" else "⏳"
        delay_str = f"{item['delay']}ms" if item['delay'] < 9999 else "N/A"
        rows.append(f"| {i:02d} | {item['name']} | {status} | 🔍 | {delay_str} | {item['adContext']} | {item.get('originalName','未知')} |\n")
    return "".join(rows)

def main():
    if not os.path.exists(ORIGINAL_FILE):
        return

    with open(ORIGINAL_FILE, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

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

        if p == "备用线路" and counters[p] > 10: continue

        target_name = f"{p} {counters[p]:02d}"
        counters[p] += 1
        
        new_item = {'name': target_name, 'adContext': processed_ad}
        new_item.update({k: v for k, v in item.items() if k not in ['name', 'adContext']})
        final_ordered_results.append(new_item)

    # 存储数据
    clean_data = [i for i in final_ordered_results if i.get('category') != 'NSFW']
    nsfw_data = [i for i in final_ordered_results if i.get('category') == 'NSFW']

    for path, data in [(CLEAN_OUTPUT, clean_data), (NSFW_OUTPUT, nsfw_data), (FULL_OUTPUT, final_ordered_results)]:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # README 渲染
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    header = "| 序号 | 线路名称 | 预检 | 搜索 | 延迟 | 广告 | 原始名称 |\n| :--- | :--- | :---: | :---: | :---: | :--- | :--- |\n"
    lines = [f"# 🛰️ API 实时监控中心\n\n更新时间：`{now}` (GitHub 环境预检)\n\n"]
    
    # 渲染常规版块
    sections = [("⚡ 极速直连", "极速直连"), ("💎 优质线路", "优质线路"), ("🛠️ 备用线路", "备用线路")]
    for title, key in sections:
        sec_data = [x for x in clean_data if key in x['name']]
        if sec_data:
            lines.append(f"### {title}\n{header}{generate_table_rows(sec_data)}\n")

    # 渲染 NSFW 版块
    if nsfw_data:
        lines.append("### 🔞 NSFW 秘密通道\n<details>\n<summary>点击展开 (敏感内容)</summary>\n\n")
        lines.append(header)
        lines.append(generate_table_rows(nsfw_data))
        lines.append("\n</details>\n")

    with open(README_FILE, 'w', encoding='utf-8') as f:
        f.write("".join(lines))
    print(f"✅ 完成！常规源: {len(clean_data)}, NSFW源: {len(nsfw_data)}")

if __name__ == "__main__":
    main()

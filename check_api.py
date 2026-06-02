import requests
import json
import concurrent.futures
import time
import os
import urllib.parse
import re

# --- 配置 ---
ORIGINAL_FILE = 'sources.json'
HISTORY_FILE = 'history_30days.json'  # 新增：用于在 GitHub Actions 中持久化 30 天状态
CLEAN_OUTPUT = 'clean_status.json'
NSFW_OUTPUT = 'nsfw_status.json'
FULL_OUTPUT = 'full_status.json'
MIHOMO_OUTPUT = 'mihomo_rules.yaml'
README_FILE = 'README.md'
TIMEOUT = 12 

# 搜索关键词
NORMAL_KEYWORD = "庆余年"
NSFW_KEYWORD = "臀"

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
    
    res_item['searchable'] = False
    res_item['check_status'] = "Failed"
    res_item['detected_domains'] = []
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        test_url = f"{item['url']}?wd={urllib.parse.quote(search_word)}&ac=videolist"
        resp = requests.get(test_url, timeout=TIMEOUT, headers=headers)
        
        if resp.status_code == 200:
            data = resp.json()
            vod_list = data.get('list', [])
            
            if vod_list and len(vod_list) > 0:
                first_vod = vod_list[0]
                play_url = str(first_vod.get('vod_play_url', ''))
                
                clean_url_pool = play_url.replace('\\', '')
                urls = re.findall(r'https?://[^\"\$#\s]+\.(?:m3u8|mp4)[^\"\$#\s]*', clean_url_pool)
                
                if urls:
                    res_item['searchable'] = True
                    target_m3u8 = urls[0]
                    
                    if validate_m3u8_content(target_m3u8, headers):
                        res_item['check_status'] = "Passed"
                        
                        extracted_domains = []
                        for u in [item['url'], target_m3u8]:
                            match = re.search(r'https?://([^/]+)', u)
                            if match:
                                extracted_domains.append(match.group(1))
                        res_item['detected_domains'] = extracted_domains
                    else:
                        if len(play_url) > 20:
                            res_item['check_status'] = "Untested (Geo-blocked?)"
    except:
        pass
        
    return res_item

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def update_history_and_calculate_priority(current_results, history):
    updated_history = {}
    processed_results = []

    for item in current_results:
        url = item['url']
        is_passed = (item['check_status'] == "Passed")
        
        # 读取历史数据，没有则初始化
        hist = history.get(url, {
            "priority": 100,
            "consecutive_success": 0,
            "total_checks": 0,
            "success_checks": 0
        })
        
        hist["total_checks"] += 1
        
        if is_passed:
            hist["success_checks"] += 1
            hist["consecutive_success"] += 1
            # 成功则平稳递增，连续成功加权奖励，上限 150
            bonus = 5 + min(hist["consecutive_success"] // 3, 5)
            hist["priority"] = min(hist["priority"] + bonus, 150)
            item['isEnabled'] = True
        else:
            hist["consecutive_success"] = 0
            # 失败采取重罚，让其迅速下沉
            hist["priority"] = hist["priority"] - 20
            item['isEnabled'] = False

        # 计算稳定率
        stability_rate = (hist["success_checks"] / hist["total_checks"]) * 100
        item['stability'] = f"{stability_rate:.1f}%"
        item['priority'] = hist["priority"]
        
        # 广告标签加分/扣分（转换为对 priority 的修正）
        ad_text = (item.get('adContext') or '').lower()
        if "无广告" in ad_text or "纯净" in ad_text:
            item['priority'] += 10
        elif "广告" in ad_text:
            item['priority'] -= 10

        # 老化淘汰机制：如果分数跌破 20分（连续失联数天），彻底从列表中除名
        if hist["priority"] > 20:
            updated_history[url] = hist
            processed_results.append(item)
            
    # 保存更新后的历史状态文件（供下次 GitHub Actions 读取）
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(updated_history, f, ensure_ascii=False, indent=2)
        
    return processed_results

def generate_table_rows(data_list):
    rows = []
    for i, item in enumerate(data_list, 1):
        status = "✅" if item['check_status'] == "Passed" else "⏳"
        rows.append(f"| {i:02d} | {item['name']} | {status} | 🔍 | {item['stability']} | {item['adContext']} | {item.get('originalName','未知')} |\n")
    return "".join(rows)

def domain_to_mihomo_regex(domain):
    escaped = domain.replace('.', r'\.').replace('-', r'\-')
    regex_str = re.sub(r'\d+', r'\\d+', escaped)
    return f'  - DOMAIN-REGEX,"^{regex_str}$",DIRECT'

def main():
    if not os.path.exists(ORIGINAL_FILE):
        print(f"❌ 错误：找不到原文件 {ORIGINAL_FILE}")
        return

    with open(ORIGINAL_FILE, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    print(f"🚀 开始多线程体检...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(check_source, raw_data))

    # 载入 30 天历史数据
    history = load_history()
    
    # 结合历史计算 Priority
    scored_results = update_history_and_calculate_priority(results, history)

    # 筛选可用源并基于 priority 降序排序（稳定源自然置顶，波动源迅速下沉）
    valid_results = [i for i in scored_results if i['isEnabled']]
    valid_results.sort(key=lambda x: -x['priority'])

    counters = {"极速直连": 1, "优质线路": 1, "备用线路": 1, "NSFW 秘密通道": 1}
    final_ordered_results = []
    active_domains = set()

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
        
        if item['check_status'] == "Passed" and 'detected_domains' in item:
            active_domains.update(item['detected_domains'])
        
        new_item = {'name': target_name, 'adContext': processed_ad}
        new_item.update({k: v for k, v in item.items() if k not in ['name', 'adContext', 'detected_domains']})
        final_ordered_results.append(new_item)

    clean_data = [i for i in final_ordered_results if i.get('category') != 'NSFW']
    nsfw_data = [i for i in final_ordered_results if i.get('category') == 'NSFW']

    for path, data in [(CLEAN_OUTPUT, clean_data), (NSFW_OUTPUT, nsfw_data), (FULL_OUTPUT, final_ordered_results)]:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # 导出 Mihomo 规则
    mihomo_rules = [
        "# >>>>> Mihomo (Clash Meta) 苹果CMS正则直连规则 START <<<<<",
        f"# 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    ]
    formatted_regex_rules = sorted(list(set(domain_to_mihomo_regex(d) for d in active_domains)))
    mihomo_rules.extend(formatted_regex_rules)
    mihomo_rules.append("# >>>>> Mihomo (Clash Meta) 苹果CMS正则直连规则 END <<<<<")
    
    with open(MIHOMO_OUTPUT, 'w', encoding='utf-8') as f:
        f.write("\n".join(mihomo_rules) + "\n")

    # README 渲染（原“延迟”列升级为“稳定率”列）
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    header = "| 序号 | 线路名称 | 预检 | 搜索 | 30天稳定率 | 广告 | 原始名称 |\n| :--- | :--- | :---: | :---: | :---: | :--- | :--- |\n"
    lines = [f"# 🛰️ API 实时监控中心\n\n更新时间：`{now}` (基于历史数据动态置顶)\n\n"]
    
    sections = [("⚡ 极速直连", "极速直连"), ("💎 优质线路", "优质线路"), ("🛠️ 备用线路", "备用线路")]
    for title, key in sections:
        sec_data = [x for x in clean_data if key in x['name']]
        if sec_data:
            lines.append(f"### {title}\n{header}{generate_table_rows(sec_data)}\n")

    if nsfw_data:
        lines.append("### 🔞 NSFW 秘密通道\n<details>\n<summary>点击展开 (敏感内容)</summary>\n\n")
        lines.append(header)
        lines.append(generate_table_rows(nsfw_data))
        lines.append("\n</details>\n")

    with open(README_FILE, 'w', encoding='utf-8') as f:
        f.write("".join(lines))
        
    print(f"✅ 历史数据同步完毕！常规源: {len(clean_data)}, NSFW源: {len(nsfw_data)}")

if __name__ == "__main__":
    main()

import requests
import json
import concurrent.futures
import time
import os
import urllib.parse
import re

# --- 配置 ---
ORIGINAL_FILE = 'sources.json'
HISTORY_FILE = 'history_30days.json'  # 持久化 30 天状态，确保增量排位
CLEAN_OUTPUT = 'clean_status.json'
NSFW_OUTPUT = 'nsfw_status.json'
FULL_OUTPUT = 'full_status.json'
MIHOMO_OUTPUT = 'mihomo_rules.yaml'    # Mihomo 正则直连规则输出
README_FILE = 'README.md'
TIMEOUT = 12 

# 搜索关键词
NORMAL_KEYWORD = "庆余年"
NSFW_KEYWORD = "臀"

def validate_m3u8_content(url, headers):
    """深度预检：确保链接不仅存在，而且是真实的 M3U8 流媒体格式"""
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
    """单节点测试核心逻辑"""
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
                
                # 强效清洗并精确定位 m3u8/mp4 核心线路，彻底无视前面的 .jpg 封面图干扰
                clean_url_pool = play_url.replace('\\', '')
                urls = re.findall(r'https?://[^\"\$#\s]+\.(?:m3u8|mp4)[^\"\$#\s]*', clean_url_pool)
                
                if urls:
                    res_item['searchable'] = True
                    target_m3u8 = urls[0]
                    
                    if validate_m3u8_content(target_m3u8, headers):
                        res_item['check_status'] = "Passed"
                        
                        # 收集成功节点的【接口域名】与【播放域名】
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
    """核心算法：通过 30 天历史增量计算评分，实现稳定源置顶、波动源下沉"""
    updated_history = {}
    processed_results = []

    for item in current_results:
        url = item['url']
        is_passed = (item['check_status'] == "Passed")
        
        # 读取或初始化历史节点
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
            # 连续成功获得额外分值加权奖励，积分上限 150
            bonus = 5 + min(hist["consecutive_success"] // 3, 5)
            hist["priority"] = min(hist["priority"] + bonus, 150)
            item['isEnabled'] = True
        else:
            hist["consecutive_success"] = 0
            # 出现波动执行重罚（扣 20 分），让其瞬间排名垫底
            hist["priority"] = hist["priority"] - 20
            item['isEnabled'] = False

        # 计算并附加30天稳定率
        stability_rate = (hist["success_checks"] / hist["total_checks"]) * 100
        item['stability'] = f"{stability_rate:.1f}%"
        item['priority'] = hist["priority"]
        
        # 广告偏好修正
        ad_text = (item.get('adContext') or '').lower()
        if "无广告" in ad_text or "纯净" in ad_text:
            item['priority'] += 10
        elif "广告" in ad_text:
            item['priority'] -= 10

        # 老化淘汰阀值：连续多次失联导致分数低于或等于 20 分的死源，直接除名
        if hist["priority"] > 20:
            updated_history[url] = hist
            processed_results.append(item)
            
    # 将增量计算推回历史记录文件
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
    # 1. 统一小写并剥离端口
    domain = domain.strip().lower()
    if ":" in domain:
        domain = domain.split(":")[0]
        
    # 2. 如果是纯 IP，直接返回纯文本 IP，不加双引号
    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', domain):
        return domain

    # 3. 转义点号和横杠，防止正则解析出错
    escaped = domain.replace('.', r'\.').replace('-', r'\-')
    
    # 4. 使用 lambda 避免 re.sub 针对 \d 的后向引用转义报错
    regex_str = re.sub(r'\d+', lambda m: r'\d+', escaped)
    
    # 5. 如果域名开头有 www. 或 api. 等子域名，将其转化为通用前缀匹配 `^.+\.`
    parts = regex_str.split(r'\.')
    if len(parts) > 2:
        # 去掉原本固定的前缀，改用 ^.+\. 开头
        main_body = r"\.".join(parts[-2:])
        return f"^.+\.{main_body}$"
        
    return f"^{regex_str}$"

def main():
    if not os.path.exists(ORIGINAL_FILE):
        print(f"❌ 错误：找不到原文件 {ORIGINAL_FILE}")
        return

    with open(ORIGINAL_FILE, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    print(f"🚀 开始多线程交叉并行体检...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(check_source, raw_data))

    # 载入 30 天持久化历史
    history = load_history()
    
    # 融合历史动态计分
    scored_results = update_history_and_calculate_priority(results, history)

    # 基于 priority 权重值做全局降序排列
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
        
        # 🛡️ 核心打破死循环：无条件将 sources.json 中的源站接口加入直连池，防止因分流失效造成全军覆没
        if 'url' in item:
            match = re.search(r'https?://([^/]+)', item['url'])
            if match:
                active_domains.add(match.group(1))
        
        # 成功通过的节点，额外剥离出其底层视频流播放域名
        if item['check_status'] == "Passed" and 'detected_domains' in item:
            active_domains.update(item['detected_domains'])
        
        new_item = {'name': target_name, 'adContext': processed_ad}
        new_item.update({k: v for k, v in item.items() if k not in ['name', 'adContext', 'detected_domains']})
        final_ordered_results.append(new_item)

    # 归档数据文件
    clean_data = [i for i in final_ordered_results if i.get('category') != 'NSFW']
    nsfw_data = [i for i in final_ordered_results if i.get('category') == 'NSFW']

    for path, data in [(CLEAN_OUTPUT, clean_data), (NSFW_OUTPUT, nsfw_data), (FULL_OUTPUT, final_ordered_results)]:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # 自动生成并固化 Mihomo (Clash Meta) 专属正则直连文件
    mihomo_rules = [
        "# >>>>> Mihomo (Clash Meta) 苹果CMS正则直连规则 START <<<<<",
        f"# 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')} (Beijing Time)"
    ]
    formatted_regex_rules = sorted(list(set(domain_to_mihomo_regex(d) for d in active_domains)))
    mihomo_rules.extend(formatted_regex_rules)
    mihomo_rules.append("# >>>>> Mihomo (Clash Meta) 苹果CMS正则直连规则 END <<<<<")
    
    with open(MIHOMO_OUTPUT, 'w', encoding='utf-8') as f:
        f.write("\n".join(mihomo_rules) + "\n")

    # 全新渲染 README.md 展示报告（原延迟列全面进化为“30天稳定率”）
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    header = "| 序号 | 线路名称 | 预检 | 搜索 | 30天稳定率 | 广告 | 原始名称 |\n| :--- | :--- | :---: | :---: | :---: | :--- | :--- |\n"
    lines = [f"# 🛰️ API 实时监控中心\n\n更新时间：`{now}` (基于历史健康度动态置顶)\n\n"]
    
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
        
    print(f"✅ 历史数据与分流规则同步完毕！常规源: {len(clean_data)}, NSFW源: {len(nsfw_data)}")

if __name__ == "__main__":
    main()

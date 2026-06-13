import requests
import json
import concurrent.futures
import urllib.parse
from urllib.parse import urlparse
import os
import re
import time

# --- 配置 ---
ORIGINAL_FILE = 'sources.json'
CLEAN_OUTPUT = 'clean_status.json'
NSFW_OUTPUT = 'nsfw_status.json'
FULL_OUTPUT = 'full_status.json'
OUTPUT_MIHOMO_FILE = 'mihomo_rules.yaml'
README_FILE = 'README.md'
TIMEOUT = 12

# 搜索关键词
NORMAL_KEYWORD = "庆余年"
NSFW_KEYWORD = "臀"

def extract_domain(url):
    """提取 URL 中的纯域名"""
    try:
        domain = urlparse(url).netloc
        if ":" in domain:
            domain = domain.split(":")[0]
        return domain if domain else None
    except:
        return None

def convert_to_mihomo_regex_rule(domain):
    """
    针对含有数字的轮询集群进行 DOMAIN-REGEX 泛化
    """
    if not domain:
        return None

    match = re.search(r'([a-zA-Z\-_]+)\d+', domain)
    if match:
        keyword = match.group(1).lower()
        if len(keyword) >= 2:
            return f"  - DOMAIN-REGEX,^.*{keyword}\\d+\\..*$"

    parts = domain.split('.')
    if len(parts) >= 2:
        if len(parts) >= 3 and parts[-2] in ['com', 'net', 'org', 'gov', 'edu']:
            suffix = ".".join(parts[-3:])
        else:
            suffix = ".".join(parts[-2:])
        return f"  - DOMAIN-SUFFIX,{suffix.lower()}"
    
    return f"  - DOMAIN-SUFFIX,{domain.lower()}"

def process_source_item(item):
    """单个站点的综合预检与分类（只要能返回 200 就判定为成功）"""
    res_item = item.copy()
    url = item.get('url')
    current_station_rules = set()
    
    raw_trend = item.get('trend', []) if isinstance(item.get('trend'), list) else []
    cleaned_trend = []
    for t in raw_trend:
        if t == "📈": cleaned_trend.append("✅")
        elif t == "📉": cleaned_trend.append("❌")
        else: cleaned_trend.append(t)

    stats = {
        "name": item.get('name', '未命名'),
        "url": url if url else 'N/A',
        "isEnabled": False,
        "searchable": False,
        "success_count": int(item.get('success_count', 0)),
        "fail_count": int(item.get('fail_count', 0)),
        "trend": cleaned_trend
    }

    # 彻底清理掉原有或潜藏的额外字段，确保写入 JSON 时纯净
    for extra_key in ['success_count', 'fail_count', 'success_rate', 'trend', 'm3u8_domains']:
        if extra_key in res_item:
            del res_item[extra_key]

    if not url:
        res_item['isEnabled'] = False
        res_item['searchable'] = False
        stats['fail_count'] += 1
        stats['trend'].append("❌")
        return res_item, current_station_rules, stats

    # 提取自身 API 域名规则
    api_domain = extract_domain(url)
    if api_domain:
        rule_line = convert_to_mihomo_regex_rule(api_domain)
        if rule_line:
            current_station_rules.add(rule_line)

    cat = item.get('category', 'General')
    search_word = NSFW_KEYWORD if cat == "NSFW" else NORMAL_KEYWORD
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        test_url = f"{url}?wd={urllib.parse.quote(search_word)}&ac=detail"
        resp = requests.get(test_url, timeout=TIMEOUT, headers=headers)
        
        # 💡 核心修改点：只要能返回 200 状态码，就算成功
        if resp.status_code == 200:
            res_item['isEnabled'] = True
            res_item['searchable'] = True
            
            stats['isEnabled'] = True
            stats['searchable'] = True
            stats['success_count'] += 1
            stats['trend'].append("✅")
            
            # 尝试解析里面的 m3u8（如果能解析到就提取，解析不到也不影响本次成功判定）
            try:
                data = resp.json()
                vod_list = data.get('list', [])
                if vod_list and len(vod_list) > 0:
                    vod_play_url = str(vod_list[0].get('vod_play_url', ''))
                    groups = vod_play_url.split('$$$')
                    for group in groups:
                        episodes = group.split('#')
                        if episodes:
                            url_candidate = episodes[0].split('$')[-1].strip()
                            if url_candidate.startswith('http') and '.m3u8' in url_candidate.lower():
                                m3u8_domain = extract_domain(url_candidate)
                                if m3u8_domain:
                                    rule_line = convert_to_mihomo_regex_rule(m3u8_domain)
                                    if rule_line:
                                        current_station_rules.add(rule_line)
            except:
                # 即使返回的不是 JSON 或者没有 list 字段，只要状态码是 200，上面已经记录了成功，这里直接略过即可
                pass
        else:
            # 状态码非 200 (如 404, 502, 403 等) 算失败
            res_item['isEnabled'] = False
            res_item['searchable'] = False
            stats['fail_count'] += 1
            stats['trend'].append("❌")
    except:
        # 网络超时、硬报错、DNS 解析失败等 算失败
        res_item['isEnabled'] = False
        res_item['searchable'] = False
        stats['fail_count'] += 1
        stats['trend'].append("❌")
        
    if len(stats['trend']) > 7:
        stats['trend'] = stats['trend'][-7:]
        
    return res_item, current_station_rules, stats

def generate_markdown_table(stats_list):
    """利用内存中的统计数据，动态渲染 README 表格"""
    rows = []
    for item in stats_list:
        status_icon = "✅ 有效" if item['isEnabled'] else "❌ 失效"
        search_icon = "✅" if item['searchable'] else "❌"
        
        s_count = item['success_count']
        f_count = item['fail_count']
        total = s_count + f_count
        s_rate = f"{(s_count / total * 100):.1f}%" if total > 0 else "0.0%"
        trend_str = "".join(item['trend']) if item['trend'] else "无数据"
        
        if len(item['trend']) >= 3 and item['trend'][-3:] == ["❌", "❌", "❌"]:
            status_icon = "🛠️ 维护中"

        rows.append(f"| {status_icon} | {item['name']} | `{item['url']}` | {search_icon} | {s_count} | {f_count} | **{s_rate}** | {trend_str} |\n")
    return "".join(rows)

def main():
    if not os.path.exists(ORIGINAL_FILE):
        print(f"❌ 未找到源文件: {ORIGINAL_FILE}")
        return

    with open(ORIGINAL_FILE, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    all_mihomo_rules = set()
    processed_items = []
    all_stats = []

    print("🚀 正在执行检测（标准已放宽：返回 200 即成功）...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(process_source_item, raw_data)
        for res_item, rules, stats in results:
            processed_items.append(res_item)
            all_mihomo_rules.update(rules)
            all_stats.append(stats)

    clean_status_data = [i for i in processed_items if i.get('category') != 'NSFW']
    nsfw_status_data = [i for i in processed_items if i.get('category') == 'NSFW']

    with open(CLEAN_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(clean_status_data, f, ensure_ascii=False, indent=2)

    with open(NSFW_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(nsfw_status_data, f, ensure_ascii=False, indent=2)

    with open(FULL_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(processed_items, f, ensure_ascii=False, indent=2)

    sorted_rules = sorted(list(all_mihomo_rules))
    mihomo_yaml = [
        "# Mihomo (Clash) Rule-Provider",
        f"# 自动更新时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "payload:"
    ]
    mihomo_yaml.extend(sorted_rules)
    with open(OUTPUT_MIHOMO_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(mihomo_yaml))

    clean_stats = [s for s, orig in zip(all_stats, raw_data) if orig.get('category') != 'NSFW']
    nsfw_stats = [s for s, orig in zip(all_stats, raw_data) if orig.get('category') == 'NSFW']

    now_time = time.strftime("%Y-%m-%d %H:%M:%S")
    table_header = "| 状态 | 资源名称 | 地址 API | 搜索功能 | 成功次数 | 失败次数 | 成功率 | 最近7天趋势 |\n| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |\n"
    
    readme_content = [
        f"# 🛰️ API 实时监控中心 & 规则订阅\n\n",
        f"更新时间：`{now_time}` (基于状态码 200 活跃预检)\n\n",
        f"### ⚡ 常规过滤线路明细\n",
        table_header,
        generate_markdown_table(clean_stats),
        "\n"
    ]

    if nsfw_stats:
        readme_content.extend([
            f"### 🔞 NSFW 秘密通道线路明细\n",
            f"<details>\n<summary>展开敏感统计内容</summary>\n\n",
            table_header,
            generate_markdown_table(nsfw_stats),
            "\n</details>\n"
        ])

    with open(README_FILE, 'w', encoding='utf-8') as f:
        f.write("".join(readme_content))
        
    print(f"\n============================================")
    print(f"✅ 检测完成！")
    print(f"📁 常规 JSON -> {CLEAN_OUTPUT}")
    print(f"📄 数据报表 -> {README_FILE}")
    print(f"============================================")

if __name__ == "__main__":
    main()
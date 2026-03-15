import requests
import json
import concurrent.futures
import time
import os
import urllib.parse

# --- 配置 ---
ORIGINAL_FILE = 'sources.json'
CLEAN_OUTPUT = 'clean_status.json'   # 常规版 (无成人)
NSFW_OUTPUT = 'nsfw_status.json'     # 成人版
FULL_OUTPUT = 'full_status.json'     # 全量版
README_FILE = 'README.md'
TIMEOUT = 10

# 搜索关键词（用热门剧更容易出结果）
NORMAL_KEYWORD = "庆余年"           # 可自行改回 "我的团长我的团"
NSFW_KEYWORD = "臀"

def calculate_score(item):
    if not item.get('isEnabled'):
        return -999_999

    delay = item.get('delay', 9999)
    
    # 延迟得分（非线性，更宽容）
    if delay <= 400:
        delay_score = 10000
    elif delay <= 800:
        delay_score = 8500
    elif delay <= 1500:
        delay_score = 6500
    elif delay <= 3000:
        delay_score = 4000
    else:
        delay_score = 1000 - (delay - 3000) * 2   # 惩罚重

    score = delay_score

    # 广告惩罚/加成（更细分的关键词匹配）
    ad = (item.get('adContext') or '').lower()
    ad_lower = ad

    if any(k in ad_lower for k in ["无广告", "纯净", "无任何广告", "零广告", "净版"]):
        score += 5500
    elif any(k in ad_lower for k in ["极少广告", "广告少", "轻广告"]):
        score += 2200
    elif any(k in ad_lower for k in ["跑马灯", "开头广告", "5-10秒", "插播", "弹窗", "强制跳转"]):
        score -= 2800
    elif "广告" in ad_lower or "推广" in ad_lower:
        score -= 1200
    else:
        score += 800   # 未知 → 小幅加分（比明确有广告好）

    # 可搜索能力（最重要功能之一）
    if item.get('searchable'):
        score += 4800
    else:
        score -= 3000   # 不可搜索基本废源

    # 官方 / 高信誉源加成
    if item.get('isOfficial'):
        score += 3800

    # 额外加分项（可扩展）
    if "秒播" in ad_lower or "秒拖" in ad_lower or "极速" in ad_lower:
        score += 1800
    if "高清" in ad_lower or "蓝光" in ad_lower or "4k" in ad_lower:
        score += 1200
    if "独家" in ad_lower or "自产" in ad_lower:
        score += 900

    # NSFW 源独立通道（可选，根据你的需求）
    if item.get('category') == "NSFW":
        score += 1500          # NSFW 用户更宽容广告
        if "跳转频繁" in ad_lower or "污染搜索" in ad_lower:
            score -= 2200

    # 保底分，避免极端负分把好源排太后
    score = max(score, -5000)

    return round(score)

def check_source(item):
    """简化版检测：只检查接口是否通 + 是否可搜索"""
    res_item = item.copy()
    cat = res_item.get('category', 'General')
    search_word = NSFW_KEYWORD if cat == "NSFW" else NORMAL_KEYWORD

    res_item['isEnabled'] = False
    res_item['searchable'] = False
    res_item['delay'] = 9999

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        start_time = time.time()
        test_url = f"{item['url']}?wd={urllib.parse.quote(search_word)}&ac=detail"
        resp = requests.get(test_url, timeout=TIMEOUT, headers=headers, allow_redirects=True)

        if resp.status_code == 200:
            res_item['isEnabled'] = True
            res_item['delay'] = int((time.time() - start_time) * 1000)
            content = resp.text.strip().lower()

            # 放宽判断：有列表结构或关键词就算可搜索
            if any(k in content for k in ['"list":[{', '"vod_list":', '<list>', '"vod_id"', search_word.lower(), '"total":', '"pagecount":']):
                res_item['searchable'] = True

    except:
        pass

    res_item['score'] = calculate_score(res_item)
    return res_item


def main():
    print("🚀 启动检测（已去除 m3u8 检查）...")
    print(f"搜索关键词：{NORMAL_KEYWORD} (NSFW: {NSFW_KEYWORD})")

    if not os.path.exists(ORIGINAL_FILE):
        print(f"❌ 未找到源文件：{ORIGINAL_FILE}")
        return

    with open(ORIGINAL_FILE, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    print(f"总共检测 {len(raw_data)} 条源...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(check_source, raw_data))

    # 只保留接口通 + 可搜索的源
    valid_results = [i for i in results if i['isEnabled'] and i['searchable']]
    print(f"有效源数量：{len(valid_results)} 条")

    if not valid_results:
        print("警告：没有有效源！可能原因：")
        print("1. 所有源接口超时/403/502")
        print("2. 搜索关键词在这些源中完全搜不到内容")
        print("3. 返回结构不匹配（缺少 list/vod_list 等字段）")
        print("\n前 5 条诊断信息：")
        for item in results[:5]:
            print(f"{item.get('url')} | Enabled: {item['isEnabled']} | Searchable: {item['searchable']} | Delay: {item['delay']}ms")

    valid_results.sort(key=lambda x: -x['score'])

    counters = {"极速直连": 1, "优质线路": 1, "备用线路": 1, "NSFW 秘密通道": 1}
    final_ordered_results = []

    for item in valid_results:
        raw_ad = item.get('adContext', '')
        processed_ad = "未知" if not raw_ad or "无广告" in raw_ad else raw_ad

        if item.get('category') == 'NSFW':
            p = "NSFW 秘密通道"
        elif item.get('isOfficial'):
            p = "极速直连"
        elif processed_ad == "未知" or "无广告" in raw_ad:
            p = "优质线路"
        else:
            p = "备用线路"

        if p == "备用线路" and counters[p] > 5:
            item['isEnabled'] = False

        target_name = f"{p} {counters[p]:02d}"
        counters[p] += 1

        new_item = {}
        inserted = False
        for key, value in item.items():
            if key == 'originalName':
                new_item['name'] = target_name
                inserted = True
            elif key == 'adContext':
                new_item[key] = processed_ad
            else:
                new_item[key] = value

        if not inserted:
            new_item['name'] = target_name

        final_ordered_results.append(new_item)

    # 输出文件
    clean_data = [i for i in final_ordered_results if i.get('category') != 'NSFW']
    nsfw_data = [i for i in final_ordered_results if i.get('category') == 'NSFW']

    with open(CLEAN_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(clean_data, f, ensure_ascii=False, indent=2)

    with open(NSFW_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(nsfw_data, f, ensure_ascii=False, indent=2)

    with open(FULL_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(final_ordered_results, f, ensure_ascii=False, indent=2)

    print("\n✅ 完成！")
    print(f"常规版 (clean_status.json) : {len(clean_data)} 条")
    print(f"成人版 (nsfw_status.json)  : {len(nsfw_data)} 条")
    print(f"全量版 (full_status.json)   : {len(final_ordered_results)} 条")
    generate_readme(clean_data, nsfw_data, final_ordered_results, raw_data)

# ────────────────────────────────────────────────
# 生成 README.md 看板
# ────────────────────────────────────────────────

def generate_readme(clean_data, nsfw_data, full_data, raw_data=None):
    lines = []
    lines.append("# 🎬 影视资源接口可用性检测看板\n")
    lines.append(f"最后更新：{time.strftime('%Y-%m-%d %H:%M:%S')}（HKT）\n")
    lines.append(f"检测关键词：**{NORMAL_KEYWORD}**（NSFW 用 **{NSFW_KEYWORD}**）\n")
    
    # 使用传入的 raw_data，如果没有就用可用总数
    total_detected = len(raw_data) if raw_data is not None else (len(clean_data) + len(nsfw_data))
    lines.append(f"原始检测源：**{total_detected}** 条\n")
    lines.append(f"可用源：**{len(full_data)}** 条（常规 {len(clean_data)} + NSFW {len(nsfw_data)}）\n\n")

    lines.append("## 📊 统计概览\n\n")
    lines.append("| 分类       | 数量 | 说明                     |\n")
    lines.append("|------------|------|--------------------------|\n")
    lines.append(f"| 极速直连   | {sum(1 for x in clean_data if '极速直连' in x.get('name',''))} | 官方/极低延迟/无广告优先 |\n")
    lines.append(f"| 优质线路   | {sum(1 for x in clean_data if '优质线路' in x.get('name',''))} | 无广告或广告极少         |\n")
    lines.append(f"| 备用线路   | {sum(1 for x in clean_data if '备用线路' in x.get('name',''))} | 有广告/稳定性一般        |\n")
    lines.append(f"| NSFW 通道  | {len(nsfw_data)} | 成人内容专用  |\n\n")

    def add_section(title, data_list, emoji=""):
        if not data_list:
            return
        lines.append(f"## {emoji} {title}\n")
        lines.append("| 排名 | 名称 | 延迟(ms) | 广告情况 | 备注 |\n")
        lines.append("|------|------|----------|----------|------|\n")
        
        for i, item in enumerate(data_list[:30], 1):
            name = item.get('name', '未知')
            delay = item.get('delay', '—')
            ad = (item.get('adContext') or '未知')[:35]
            if len(item.get('adContext', '')) > 35:
                ad += "..."
            remark = "官方" if item.get('isOfficial') else ""
            if not item.get('searchable'):
                remark += " 不可搜索"
            lines.append(f"| {i} | {name} | {delay} | {ad} | {remark.strip()} |\n")
        lines.append("\n")

    # 分组
    jisu = [x for x in clean_data if '极速直连' in x.get('name', '')]
    youzhi = [x for x in clean_data if '优质线路' in x.get('name', '')]
    beiyong = [x for x in clean_data if '备用线路' in x.get('name', '')]
    nsfw_list = sorted(nsfw_data, key=lambda x: -x.get('score', 0))

    add_section("极速直连（推荐优先使用）", jisu, "⚡")
    add_section("优质线路（广告少/稳定）", youzhi, "✅")
    add_section("备用线路（有广告/应急）", beiyong, "🛡️")

    # NSFW 使用折叠
    if nsfw_list:
        lines.append("<details>\n")
        lines.append("<summary>🔞 NSFW 秘密通道（点击展开查看）</summary>\n\n")
        lines.append("| 排名 | 名称 | 延迟(ms) | 广告情况 | 备注 |\n")
        lines.append("|------|------|----------|----------|------|\n")
        
        for i, item in enumerate(nsfw_list[:30], 1):
            name = item.get('name', '未知')
            delay = item.get('delay', '—')
            ad = (item.get('adContext') or '未知')[:35]
            if len(item.get('adContext', '')) > 35:
                ad += "..."
            remark = "官方" if item.get('isOfficial') else ""
            if not item.get('searchable'):
                remark += " 不可搜索"
            lines.append(f"| {i} | {name} | {delay} | {ad} | {remark.strip()} |\n")
        
        lines.append("\n</details>\n\n")

    lines.append("## 字段说明\n")
    lines.append("- **name**：自动分类命名\n")
    lines.append("- **delay**：搜索接口响应延迟（毫秒）\n")
    lines.append("- **searchable**：是否能搜到测试关键词\n")
    lines.append("- **adContext**：广告/特点描述（来自 sources.json）\n")
    lines.append("- **score**：内部推荐排序分（越高越优先）\n\n")

    lines.append("**注意事项**：\n")
    lines.append("- 部分源可能因网络环境、地域、时间而表现不同\n")
    lines.append("- NSFW 源请自行判断合法性与安全性\n")
    lines.append("- 建议优先测试「极速直连」前 3 条\n")
    lines.append("- 所有数据仅供学习交流参考\n")

    with open(README_FILE, 'w', encoding='utf-8') as f:
        f.write("".join(lines))

    print(f"已更新 README：{README_FILE}")

if __name__ == "__main__":
    main()

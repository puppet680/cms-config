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

# 搜索关键词
NORMAL_KEYWORD = "庆余年"
NSFW_KEYWORD = "臀"

def calculate_score(item):
    """优化版评分：延迟最重要 + 广告细化 + 可搜索高权重"""
    if not item.get('isEnabled'):
        return -999_999

    delay = item.get('delay', 9999)
    
    # 延迟得分（分段，更人性化）
    if delay <= 400:
        delay_score = 12000
    elif delay <= 800:
        delay_score = 9500
    elif delay <= 1500:
        delay_score = 7000
    elif delay <= 3000:
        delay_score = 4000
    else:
        delay_score = max(500 - (delay - 3000) * 1.5, -2000)

    score = delay_score

    # 广告处理
    ad = (item.get('adContext') or '').lower()
    if any(k in ad for k in ["无广告", "纯净", "零广告", "净版", "无任何广告"]):
        score += 6000
    elif any(k in ad for k in ["极少广告", "广告少", "轻广告"]):
        score += 2500
    elif any(k in ad for k in ["跑马灯", "开头广告", "5-10秒", "插播", "弹窗", "强制跳转"]):
        score -= 3000
    elif "广告" in ad or "推广" in ad:
        score -= 1500
    else:
        score += 1000  # 未知描述 → 小幅加分

    # 可搜索（核心功能）
    if item.get('searchable'):
        score += 5000

    # 官方加成
    if item.get('isOfficial'):
        score += 4000

    # 额外加分
    if any(k in ad for k in ["秒播", "秒拖", "极速", "稳定", "自家CDN"]):
        score += 2000
    if any(k in ad for k in ["高清", "蓝光", "4k", "超清"]):
        score += 1200

    # NSFW 通道容忍度稍高
    if item.get('category') == "NSFW":
        score += 1500
        if "跳转频繁" in ad or "污染搜索" in ad:
            score -= 2500

    return max(round(score), -5000)


def check_source(item):
    """检测接口是否可用 + 是否可搜索"""
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

            if any(k in content for k in ['"list":[{', '"vod_list":', '<list>', '"vod_id"', search_word.lower(), '"total":', '"pagecount":']):
                res_item['searchable'] = True

    except:
        pass

    res_item['score'] = calculate_score(res_item)
    return res_item


def generate_readme(clean_data, nsfw_data, full_data):
    lines = []
    lines.append("# 🎬 影视资源接口可用性检测看板\n")
    lines.append(f"最后更新：{time.strftime('%Y-%m-%d %H:%M:%S')}（HKT）\n")
    lines.append(f"检测关键词：**{NORMAL_KEYWORD}**（NSFW 用 **{NSFW_KEYWORD}**）\n")
    lines.append(f"本次共检测到 **{len(clean_data) + len(nsfw_data)}** 个有效接口\n")
    lines.append(f"其中常规源 {len(clean_data)} 个，NSFW 源 {len(nsfw_data)} 个\n\n")

    lines.append("## 📊 统计概览\n\n")
    lines.append("| 分类       | 数量 | 说明                     |\n")
    lines.append("|------------|------|--------------------------|\n")
    lines.append(f"| 极速直连   | {sum(1 for x in clean_data if '极速直连' in x.get('name',''))} | 延迟最低 / 顶级稳定      |\n")
    lines.append(f"| 优质线路   | {sum(1 for x in clean_data if '优质线路' in x.get('name',''))} | 稳定可靠 / 中低延迟      |\n")
    lines.append(f"| 备用线路   | {sum(1 for x in clean_data if '备用线路' in x.get('name',''))} | 有广告 / 应急使用        |\n")
    lines.append(f"| NSFW 通道  | {len(nsfw_data)} | 成人内容专用（默认折叠）  |\n\n")

    def add_section(title, data_list, emoji=""):
        if not data_list:
            return
        lines.append(f"## {emoji} {title}\n")
        lines.append("| 排名 | 名称 | 延迟(ms) | 备注 |\n")
        lines.append("|------|------|----------|------|\n")
        
        for i, item in enumerate(data_list[:30], 1):
            name = item.get('name', '未知')
            delay = item.get('delay', '—')
            remark = (item.get('adContext') or '未知')[:45]
            if len(item.get('adContext', '')) > 45:
                remark += "..."
            lines.append(f"| {i} | {name} | {delay} | {remark} |\n")
        lines.append("\n")

    # 分组
    jisu = [x for x in clean_data if '极速直连' in x.get('name', '')]
    youzhi = [x for x in clean_data if '优质线路' in x.get('name', '')]
    beiyong = [x for x in clean_data if '备用线路' in x.get('name', '')]
    nsfw_list = sorted(nsfw_data, key=lambda x: -x.get('score', 0))

    add_section("极速直连（延迟最低，推荐首选）", jisu, "⚡")
    add_section("优质线路（稳定可靠）", youzhi, "✅")
    add_section("备用线路", beiyong, "🛡️")

    # NSFW 折叠
    if nsfw_list:
        lines.append("<details>\n")
        lines.append("<summary>🔞 NSFW 秘密通道（点击展开查看）</summary>\n\n")
        lines.append("| 排名 | 名称 | 延迟(ms) | 备注 |\n")
        lines.append("|------|------|----------|------|\n")
        
        for i, item in enumerate(nsfw_list[:30], 1):
            name = item.get('name', '未知')
            delay = item.get('delay', '—')
            remark = (item.get('adContext') or '未知')[:45]
            if len(item.get('adContext', '')) > 45:
                remark += "..."
            lines.append(f"| {i} | {name} | {delay} | {remark} |\n")
        
        lines.append("\n</details>\n\n")

    lines.append("## 字段说明\n")
    lines.append("- **name**：自动分类命名\n")
    lines.append("- **delay**：搜索接口响应延迟（毫秒）\n")
    lines.append("- **备注**：源的特点/广告描述\n")
    lines.append("- 表格按推荐度（score）降序排列\n\n")

    lines.append("**注意**：\n")
    lines.append("- 延迟和可用性受网络、地区、时间影响\n")
    lines.append("- 优先测试「极速直连」和「优质线路」前几条\n")
    lines.append("- NSFW 源请自行判断合法性与安全性\n")

    with open(README_FILE, 'w', encoding='utf-8') as f:
        f.write("".join(lines))

    print(f"已生成 README：{README_FILE}")


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

    valid_results = [i for i in results if i['isEnabled'] and i['searchable']]
    print(f"有效源数量：{len(valid_results)} 条")

    if not valid_results:
        print("警告：没有有效源！可能原因：")
        print("1. 接口超时/403/502")
        print("2. 搜索关键词无结果")
        print("3. 返回格式不匹配")
        print("\n前5条诊断：")
        for item in results[:5]:
            print(f"{item.get('url')} | Enabled: {item['isEnabled']} | Searchable: {item['searchable']} | Delay: {item['delay']}ms")
        return

    valid_results.sort(key=lambda x: -x['score'])

    counters = {"极速直连": 1, "优质线路": 1, "备用线路": 1, "NSFW 秘密通道": 1}
    final_ordered_results = []

    for item in valid_results:
        raw_ad = item.get('adContext', '')
        processed_ad = "未知" if not raw_ad else raw_ad

        delay = item.get('delay', 9999)
        score = item.get('score', -999999)
        is_official = item.get('isOfficial', False)
        ad_lower = raw_ad.lower()

        if item.get('category') == 'NSFW':
            p = "NSFW 秘密通道"

        elif delay <= 800 or (delay <= 1200 and score >= 14000):
            # 真正极速
            p = "极速直连" if is_official else "优质线路"

        elif is_official and delay <= 1800:
            p = "优质线路"

        elif delay <= 1500 or any(k in ad_lower for k in ["稳定", "秒播", "秒拖", "自家cdn", "极快", "高清稳定"]):
            p = "优质线路"

        else:
            p = "备用线路"

        # 限制极速数量（可选，保持精华）
        if p == "极速直连" and counters["极速直连"] > 8:
            p = "优质线路"

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

    generate_readme(clean_data, nsfw_data, final_ordered_results)


if __name__ == "__main__":
    main()
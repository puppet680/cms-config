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
    if not item.get('isEnabled'):
        return -999999
    delay = item.get('delay', 9999)
    score = 30000 - delay * 15
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

def check_source(item):
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
        print("警告：没有有效源！可能原因：1. 接口超时/403/502  2. 搜索无结果  3. 返回结构不匹配")
        print("\n前5条诊断：")
        for item in results[:5]:
            print(f"{item.get('url')} | Enabled: {item['isEnabled']} | Searchable: {item['searchable']} | Delay: {item['delay']}ms")
        return

    valid_results.sort(key=lambda x: -x['score'])

    counters = {"极速直连": 1, "优质线路": 1, "备用线路": 1, "NSFW 秘密通道": 1}
    final_ordered_results = []

    for item in valid_results:
        raw_ad = item.get('adContext', '')
        processed_ad = "未知" if not raw_ad or "无广告" in raw_ad.lower() else raw_ad

        if item.get('category') == 'NSFW':
            p = "NSFW 秘密通道"
        elif item.get('isOfficial'):
            p = "极速直连"
        elif processed_ad == "未知" or "无广告" in raw_ad.lower():
            p = "优质线路"
        else:
            p = "备用线路"

        if p == "备用线路" and counters[p] > 5:
            item['isEnabled'] = False
            continue  # 跳过，不计数、不加入结果

        target_name = f"{p} {counters[p]:02d}"
        counters[p] += 1

        # 最高效方式：先放 name，保证顺序最前
        new_item = {
            'name': target_name,
            'adContext': processed_ad,
        }
        new_item.update(item)  # 展开原始所有字段

        # 如果担心原始 item 有 name 键，强制再放一次（实际你的 sources.json 没有）
        if 'name' in new_item and new_item['name'] != target_name:
            name_value = new_item.pop('name')
            new_item = {'name': target_name, **new_item}

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
    print(f"常规版: {len(clean_data)} 条")
    print(f"成人版: {len(nsfw_data)} 条")
    print(f"全量版: {len(final_ordered_results)} 条")

    # 生成 README（你指定的样式）
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    lines.append("# 🛰️ API 实时监控中心\n\n")
    lines.append(f"更新时间：`{now}`\n\n")

    # 极速直连
    jisu = [x for x in clean_data if '极速直连' in x.get('name', '')]
    if jisu:
        lines.append("### ⚡ 极速直连\n")
        lines.append("| 序号 | 线路名称 | 状态 | 搜索 | 延迟 | 广告 | 原始名称 |\n")
        lines.append("| :--- | :--- | :---: | :---: | :---: | :--- | :--- |\n")
        for i, item in enumerate(jisu, 1):
            status = "✅" if item.get('isEnabled') else "❌"
            search_icon = "🔍" if item.get('searchable') else "✖"
            delay_str = f"{item['delay']}ms" if item.get('delay', 9999) < 9999 else "N/A"
            ad = item.get('adContext', '未知')
            orig = item.get('originalName', '未知')
            lines.append(f"| {i:02d} | {item['name']} | {status} | {search_icon} | {delay_str} | {ad} | {orig} |\n")
        lines.append("\n")

    # 优质线路
    youzhi = [x for x in clean_data if '优质线路' in x.get('name', '')]
    if youzhi:
        lines.append("### 💎 优质线路\n")
        lines.append("| 序号 | 线路名称 | 状态 | 搜索 | 延迟 | 广告 | 原始名称 |\n")
        lines.append("| :--- | :--- | :---: | :---: | :---: | :--- | :--- |\n")
        for i, item in enumerate(youzhi, 1):
            status = "✅" if item.get('isEnabled') else "❌"
            search_icon = "🔍" if item.get('searchable') else "✖"
            delay_str = f"{item['delay']}ms" if item.get('delay', 9999) < 9999 else "N/A"
            ad = item.get('adContext', '未知')
            orig = item.get('originalName', '未知')
            lines.append(f"| {i:02d} | {item['name']} | {status} | {search_icon} | {delay_str} | {ad} | {orig} |\n")
        lines.append("\n")

    # 备用线路
    beiyong = [x for x in clean_data if '备用线路' in x.get('name', '')]
    if beiyong:
        lines.append("### 🛠️ 备用线路\n")
        lines.append("| 序号 | 线路名称 | 状态 | 搜索 | 延迟 | 广告 | 原始名称 |\n")
        lines.append("| :--- | :--- | :---: | :---: | :---: | :--- | :--- |\n")
        for i, item in enumerate(beiyong, 1):
            status = "✅" if item.get('isEnabled') else "❌"
            search_icon = "🔍" if item.get('searchable') else "✖"
            delay_str = f"{item['delay']}ms" if item.get('delay', 9999) < 9999 else "N/A"
            ad = item.get('adContext', '未知')
            orig = item.get('originalName', '未知')
            lines.append(f"| {i:02d} | {item['name']} | {status} | {search_icon} | {delay_str} | {ad} | {orig} |\n")
        lines.append("\n")

    # NSFW 折叠
    if nsfw_data:
        lines.append("### 🔞 NSFW 秘密通道\n")
        lines.append("<details>\n<summary>点击展开</summary>\n\n")
        lines.append("| 序号 | 线路名称 | 状态 | 搜索 | 延迟 | 广告 | 原始名称 |\n")
        lines.append("| :--- | :--- | :---: | :---: | :---: | :--- | :--- |\n")
        for i, item in enumerate(nsfw_data, 1):
            status = "✅" if item.get('isEnabled') else "❌"
            search_icon = "🔍" if item.get('searchable') else "✖"
            delay_str = f"{item['delay']}ms" if item.get('delay', 9999) < 9999 else "N/A"
            ad = item.get('adContext', '未知')
            orig = item.get('originalName', '未知')
            lines.append(f"| {i:02d} | {item['name']} | {status} | {search_icon} | {delay_str} | {ad} | {orig} |\n")
        lines.append("\n</details>\n")

    with open(README_FILE, 'w', encoding='utf-8') as f:
        f.write("".join(lines))

    print(f"README 已生成：{os.path.abspath(README_FILE)}")

if __name__ == "__main__":
    main()
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
    """
    简化分数：延迟最重要 + 无广告加分 + 官方加分 + 可搜索加分
    """
    if not item.get('isEnabled'):
        return -999999

    delay = item.get('delay', 9999)
    score = 30000 - delay * 15          # 延迟权重最高

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


if __name__ == "__main__":
    main()
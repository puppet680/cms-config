import requests
import json
import concurrent.futures
import time
import os
import urllib.parse
from urllib.parse import urlparse

# --- 配置 ---
ORIGINAL_FILE = 'sources.json'
CLEAN_OUTPUT = 'clean_status.json'
NSFW_OUTPUT = 'nsfw_status.json'
FULL_OUTPUT = 'full_status.json'
README_FILE = 'README.md'
TIMEOUT = 10
M3U8_CHECK_TIMEOUT = 6

NORMAL_KEYWORD = "我的团长我的团"
NSFW_KEYWORD = "臀"

def calculate_score(item):
    if not item.get('isEnabled'):
        return -999999

    delay = item.get('delay', 9999)
    score = 30000 - delay * 15

    # m3u8不可达 → 直接重罚（后续会强制关闭）
    if item.get('searchable') and not item.get('m3u8_accessible'):
        score -= 25000  # 几乎不可能排前面

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
    res_item['m3u8_accessible'] = False
    res_item['m3u8_domain'] = ""

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        start_time = time.time()
        test_url = f"{item['url']}?wd={urllib.parse.quote(search_word)}&ac=detail"
        resp = requests.get(test_url, timeout=TIMEOUT, headers=headers, allow_redirects=True)

        if resp.status_code == 200:
            res_item['isEnabled'] = True
            res_item['delay'] = int((time.time() - start_time) * 1000)
            content = resp.text.strip().lower()

            if any(k in content for k in ['"list":[{', '"vod_list":', '<list>', search_word.lower()]):
                res_item['searchable'] = True

                # 提取 m3u8 并检测域名连通性
                try:
                    data = json.loads(resp.text)
                    vod_list = data.get('list', []) or data.get('vod_list', []) or data.get('data', {}).get('list', [])
                    if vod_list:
                        first_vod = vod_list[0]
                        m3u8_url = None

                        candidates = [
                            first_vod.get('url'), first_vod.get('m3u8'),
                            first_vod.get('playurl'), first_vod.get('vod_play_url'),
                            first_vod.get('player')
                        ]

                        for val in candidates:
                            if isinstance(val, str) and ('.m3u8' in val.lower() or 'm3u8' in val.lower()):
                                m3u8_url = val
                                break
                            if isinstance(val, str) and '$' in val:
                                parts = val.split('$')
                                for p in parts:
                                    if p.startswith('http') and '.m3u8' in p:
                                        m3u8_url = p
                                        break
                                if m3u8_url: break

                        if m3u8_url:
                            parsed = urlparse(m3u8_url)
                            domain = parsed.netloc
                            if domain:
                                res_item['m3u8_domain'] = domain
                                test_domain_url = f"{parsed.scheme}://{domain}/"

                                # 检测域名是否可达
                                try:
                                    head_resp = requests.head(test_domain_url, timeout=M3U8_CHECK_TIMEOUT, headers=headers, allow_redirects=True)
                                    if head_resp.status_code < 400:
                                        res_item['m3u8_accessible'] = True
                                except:
                                    try:
                                        get_resp = requests.get(test_domain_url, timeout=M3U8_CHECK_TIMEOUT, headers=headers, stream=True)
                                        if get_resp.status_code < 400:
                                            res_item['m3u8_accessible'] = True
                                    except:
                                        pass
                except:
                    pass

    except:
        pass

    res_item['score'] = calculate_score(res_item)
    return res_item


def main():
    print("🚀 启动检测（m3u8不可达将关闭源）...")

    if not os.path.exists(ORIGINAL_FILE):
        print(f"❌ 未找到 {ORIGINAL_FILE}")
        return

    with open(ORIGINAL_FILE, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(check_source, raw_data))

    # 关键更新：m3u8不可达 → 强制关闭 isEnabled
    for item in results:
        if item.get('searchable') and not item.get('m3u8_accessible'):
            item['isEnabled'] = False
            item['note'] = "m3u8域名不可达，已禁用"  # 可选：加个说明字段

    # 过滤有效源（现在已包含 m3u8 检查）
    valid_results = [i for i in results if i['isEnabled'] and i['searchable']]
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

    # README 可以保留或简化，这里略过更新逻辑（你之前有的话自己加）

    print("\n✅ 完成！")
    print(f" 常规版: {len(clean_data)} 条")
    print(f" 成人版: {len(nsfw_data)} 条")
    print(f" 全量版: {len(final_ordered_results)} 条（已排除 m3u8不可达源）")


if __name__ == "__main__":
    main()
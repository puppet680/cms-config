import requests
import json
import concurrent.futures
import time
import os
import urllib.parse
from urllib.parse import urlparse

# --- 配置 ---
ORIGINAL_FILE = 'sources.json'
CLEAN_OUTPUT = 'clean_status.json'   # 常规版 (无成人)
NSFW_OUTPUT = 'nsfw_status.json'     # 成人版 (仅限成人)
FULL_OUTPUT = 'full_status.json'     # 全量版 (汇总)
README_FILE = 'README.md'
TIMEOUT = 10                         # 接口超时
M3U8_CHECK_TIMEOUT = 6               # m3u8域名检测超时更短

# 搜索关键词（用于验证接口是否可用）
NORMAL_KEYWORD = "我的团长我的团"
NSFW_KEYWORD = "臀"

def calculate_score(item):
    """
    分数逻辑：速度最优先，其次可搜索，再次无广告，m3u8不可达重罚
    """
    if not item.get('isEnabled'):
        return -999999

    delay = item.get('delay', 9999)
    score = 30000 - delay * 15          # 延迟权重拉满，每快1ms多15分

    # m3u8域名不可达 → 大幅惩罚（用户最痛点）
    if item.get('searchable') and not item.get('m3u8_accessible'):
        score -= 18000                  # 直接打到很后面

    ad_text = (item.get('adContext') or '').lower()
    if "无广告" in ad_text or "纯净" in ad_text:
        score += 4000
    elif "跑马灯" in ad_text or "开头广告" in ad_text or "插播" in ad_text:
        score -= 2000                   # 广告扣分但不毁灭性
    elif "广告" in ad_text:
        score -= 1000

    if item.get('searchable'):
        score += 3000

    if item.get('isOfficial'):
        score += 1500                   # 官方稍加分，但不主导

    return score


def check_source(item):
    """单条线路检测 + m3u8域名连通性检测"""
    res_item = item.copy()
    cat = res_item.get('category', 'General')
    search_word = NSFW_KEYWORD if cat == "NSFW" else NORMAL_KEYWORD

    res_item['isEnabled'] = False
    res_item['searchable'] = False
    res_item['delay'] = 9999
    res_item['m3u8_accessible'] = False
    res_item['m3u8_domain'] = ""

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        start_time = time.time()
        test_url = f"{item['url']}?wd={urllib.parse.quote(search_word)}&ac=detail"
        resp = requests.get(test_url, timeout=TIMEOUT, headers=headers, allow_redirects=True)

        if resp.status_code == 200:
            res_item['isEnabled'] = True
            res_item['delay'] = int((time.time() - start_time) * 1000)
            content = resp.text.strip().lower()

            # 粗略判断是否有有效数据
            if any(k in content for k in ['"list":[{', '"vod_list":', '<list>', search_word.lower()]):
                res_item['searchable'] = True

                # 尝试提取一个m3u8地址检测域名连通性
                try:
                    data = json.loads(resp.text)
                    vod_list = data.get('list', []) or data.get('vod_list', []) or data.get('data', {}).get('list', [])
                    if vod_list:
                        first_vod = vod_list[0]
                        m3u8_url = None

                        # 常见播放地址字段（各种接口风格）
                        candidates = [
                            first_vod.get('url'),
                            first_vod.get('m3u8'),
                            first_vod.get('playurl'),
                            first_vod.get('vod_play_url'),
                            first_vod.get('player'),
                        ]

                        for val in candidates:
                            if not val or not isinstance(val, str):
                                continue
                            if '.m3u8' in val.lower() or 'm3u8' in val.lower():
                                m3u8_url = val
                                break
                            # 有些是 多集$http...m3u8 格式
                            if '$' in val:
                                parts = val.split('$')
                                for p in parts:
                                    if p.startswith('http') and '.m3u8' in p:
                                        m3u8_url = p
                                        break
                                if m3u8_url:
                                    break

                        if m3u8_url:
                            parsed = urlparse(m3u8_url)
                            domain = parsed.netloc
                            if domain:
                                res_item['m3u8_domain'] = domain
                                test_url = f"{parsed.scheme}://{domain}/"

                                # 先HEAD试探
                                try:
                                    head_resp = requests.head(test_url, timeout=M3U8_CHECK_TIMEOUT, headers=headers, allow_redirects=True)
                                    if head_resp.status_code < 400:
                                        res_item['m3u8_accessible'] = True
                                except:
                                    # HEAD失败 fallback GET
                                    try:
                                        get_resp = requests.get(test_url, timeout=M3U8_CHECK_TIMEOUT, headers=headers, stream=True)
                                        if get_resp.status_code < 400:
                                            res_item['m3u8_accessible'] = True
                                    except:
                                        pass
                except:
                    pass  # 解析失败就保持 m3u8_accessible=False

    except:
        pass

    res_item['score'] = calculate_score(res_item)
    return res_item


def update_readme(all_results):
    """更新 README，只保留核心信息"""
    current_time = time.strftime("%Y-%m-%d %H:%M:%S")

    content = "# 🛰️ 资源接口实时检测\n\n"
    content += f"更新时间：{current_time}（速度 & m3u8可用性优先）\n\n"

    def build_table(title, data_list):
        if not data_list:
            return ""
        table = f"### {title}\n"
        table += "| 序号 | 线路名称 | 状态 | 搜索 | 延迟 | M3U8 | 广告 |\n"
        table += "|:---:|:--------:|:----:|:----:|:----:|:----:|:----:|\n"
        for idx, item in enumerate(data_list, 1):
            s = "✅" if item['isEnabled'] else "❌"
            q = "✔" if item['searchable'] else "－"
            d = f"{item['delay']}ms" if item['isEnabled'] else "超时"
            m = "✅" if item.get('m3u8_accessible') else ("❌" if item.get('m3u8_domain') else "－")
            ad = item.get('adContext', '未知')
            table += f"| {idx:02d} | {item['name']} | {s} | {q} | {d} | {m} | {ad} |\n"
        return table + "\n"

    official = [i for i in all_results if i.get('isOfficial') and i.get('category') != 'NSFW']
    premium = [i for i in all_results if not i.get('isOfficial') and ("无广告" in i.get('adContext','') or i.get('adContext') == "未知") and i.get('category') != 'NSFW']
    backup = [i for i in all_results if i.get('category') != 'NSFW' and i not in official and i not in premium]
    nsfw = [i for i in all_results if i.get('category') == 'NSFW']

    content += build_table("最快线路（延迟优先）", sorted(official + premium, key=lambda x: -x['score'])[:10])
    content += build_table("优质 & 稳定线路", sorted(premium + official, key=lambda x: -x['score'])[10:20])
    content += build_table("备用线路", backup)
    content += "### 🔞 NSFW 线路\n<details>\n<summary>点击展开</summary>\n\n"
    content += build_table("", nsfw).replace("### ", "")
    content += "\n</details>\n"

    with open(README_FILE, 'w', encoding='utf-8') as f:
        f.write(content)


def main():
    print("🚀 启动全量检测（含m3u8域名连通性）...")

    if not os.path.exists(ORIGINAL_FILE):
        print(f"❌ 未找到源文件 {ORIGINAL_FILE}")
        return

    with open(ORIGINAL_FILE, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(check_source, raw_data))

    # 只保留能连通且可搜索的
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

        # 备用线路超过5条默认禁用
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

    # 输出三份文件
    clean_data = [i for i in final_ordered_results if i.get('category') != 'NSFW']
    nsfw_data = [i for i in final_ordered_results if i.get('category') == 'NSFW']

    with open(CLEAN_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(clean_data, f, ensure_ascii=False, indent=2)

    with open(NSFW_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(nsfw_data, f, ensure_ascii=False, indent=2)

    with open(FULL_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(final_ordered_results, f, ensure_ascii=False, indent=2)

    update_readme(final_ordered_results)

    print("\n✅ 检测完成！")
    print(f" 常规版: {len(clean_data)} 条 → {CLEAN_OUTPUT}")
    print(f" 成人版: {len(nsfw_data)} 条 → {NSFW_OUTPUT}")
    print(f" 全量版: {len(final_ordered_results)} 条 → {FULL_OUTPUT}")
    print(f" README 已更新")


if __name__ == "__main__":
    main()
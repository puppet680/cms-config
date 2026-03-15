import requests
import json
import concurrent.futures
import time
import os
import urllib.parse

# --- 配置 ---
ORIGINAL_FILE = 'sources.json'
CLEAN_OUTPUT = 'clean_status.json'
NSFW_OUTPUT = 'nsfw_status.json'
FULL_OUTPUT = 'full_status.json'
README_FILE = 'README.md'
TIMEOUT = 10

# 搜索关键词
NORMAL_KEYWORD = "庆余年"
NSFW_KEYWORD = "臀"

def calculate_score(item):
    """
    简化分数：延迟最重要 + 官方加分 + 可搜索加分
    """
    if not item.get('isEnabled'):
        return -999999

    delay = item.get('delay', 9999)
    score = 30000 - delay * 15 

    ad_text = (item.get('adContext') or '').lower()
    # 逻辑判定：不含负面词则加分，含则扣分
    if any(word in ad_text for word in ["广告", "跑马灯", "插播", "弹窗", "跳转"]):
        score -= 2000
    else:
        score += 4000

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

            if any(k in content for k in ['"list":[{', '"vod_list":', '<list>', '"vod_id"', search_word.lower()]):
                res_item['searchable'] = True
    except:
        pass

    res_item['score'] = calculate_score(res_item)
    return res_item

def generate_status_readme(clean_data, nsfw_data):
    """【更新】生成看板：增加 NSFW 下拉展开功能"""
    curr_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    
    def build_table(data_list, filter_prefix, limit=12):
        items = [i for i in data_list if filter_prefix in i.get('name', '')]
        if not items: return "*当前分类暂无达标线路*\n"
        
        table = ["| 线路名称 | 延迟 | 广告状态 | 负载状态 |", "| :--- | :--- | :--- | :--- |"]
        for item in items[:limit]:
            delay = item.get('delay', 9999)
            ad = (item.get('adContext') or '')
            
            # 逻辑判定无广告显示为 -
            if not any(word in ad for word in ["广告", "跑马灯"]):
                display_ad = "-"
            else:
                display_ad = ad
            
            status_icon = "🟢 极速" if delay < 500 else "🟡 正常"
            if delay > 2500: status_icon = "🔴 拥堵"
            
            table.append(f"| {item['name']} | `{delay}ms` | {display_ad} | {status_icon} |")
        return "\n".join(table) + "\n"

    # 构建 NSFW 表格内容
    nsfw_table_content = build_table(nsfw_data, "NSFW")

    readme_content = f"""# CMS在线监控看板

> **最后监测时间**: `{curr_time}`  
> **监控策略**: 极速直连按延迟排序，优质路线保持低延迟稳定。

---

## 极速直连 (按延迟排序)
{build_table(clean_data, "极速直连")}

## 优质线路 (长期稳定运行)
{build_table(clean_data, "优质线路")}

---

## 🔞 NSFW 秘密通道
<details>
<summary>点击展开查看成人专属线路 (需注意环境)</summary>
<br>

{nsfw_table_content}

</details>

---
*由自动化检测脚本维护。*
"""
    with open(README_FILE, 'w', encoding='utf-8') as f:
        f.write(readme_content)

def main():
    print("🚀 开始检测并更新看板...")
    if not os.path.exists(ORIGINAL_FILE):
        print(f"❌ 未找到源文件：{ORIGINAL_FILE}")
        return

    with open(ORIGINAL_FILE, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(check_source, raw_data))

    valid_results = [i for i in results if i['isEnabled'] and i['searchable']]
    valid_results.sort(key=lambda x: -x['score'])

    counters = {"极速直连": 1, "优质线路": 1, "备用线路": 1, "NSFW 秘密通道": 1}
    final_ordered_results = []

    for item in valid_results:
        ad_text = item.get('adContext', '')
        # 判定纯净状态
        is_clean = not any(word in ad_text for word in ["广告", "跑马灯"])

        if item.get('category') == 'NSFW':
            p = "NSFW 秘密通道"
        elif item.get('isOfficial'):
            p = "极速直连"
        elif is_clean:
            p = "优质线路"
        else:
            p = "备用线路"

        if p == "备用线路" and counters[p] > 5:
            continue

        target_name = f"{p} {counters[p]:02d}"
        counters[p] += 1

        new_item = item.copy()
        new_item['name'] = target_name
        final_ordered_results.append(new_item)

    # 写入 JSON 数据文件（后端使用）
    clean_data = [i for i in final_ordered_results if i.get('category') != 'NSFW']
    nsfw_data = [i for i in final_ordered_results if i.get('category') == 'NSFW']

    with open(CLEAN_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(clean_data, f, ensure_ascii=False, indent=2)
    with open(NSFW_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(nsfw_data, f, ensure_ascii=False, indent=2)
    with open(FULL_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(final_ordered_results, f, ensure_ascii=False, indent=2)

    # 生成纯看板 README
    generate_status_readme(clean_data, nsfw_data)
    print("\n✅ 完成！README 模块已更新，已移除订阅链接部分。")


if __name__ == "__main__":
    main()
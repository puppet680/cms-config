import requests
import json
import concurrent.futures
import time

# --- 配置 ---
ORIGINAL_FILE = 'sources.json'
CLEAN_OUTPUT = 'clean_status.json'
FULL_OUTPUT = 'full_status.json'
TIMEOUT = 10

# 搜索关键词
NORMAL_KEYWORD = "我的团长我的团"
NSFW_KEYWORD = "臀" 

def calculate_score(item):
    """
    严格权重算法：
    1. 延迟权重最高：1000ms基准，每快1ms加1分
    2. 广告少权重：无广告 +500
    3. 官方直采权重：Official +200
    4. 扣分项：跑马灯 -1000 (确保其排在最后)
    """
    if not item.get('isEnabled'): return -99999
    
    # 基础延迟分
    score = max(0, 1000 - item.get('delay', 1000))
    
    # 广告判定
    ad_text = item.get('adContext', '')
    if "无广告" in ad_text:
        score += 500
    if "跑马灯" in ad_text:
        score -= 1000  # 大幅扣分，优先级降至最低
        
    # 官方直采
    if item.get('isOfficial'):
        score += 200
        
    # 搜索支持
    if item.get('searchable'):
        score += 100
        
    return score

def check_source(item):
    res_item = item.copy()
    cat = res_item.get('category', 'General')
    search_word = NSFW_KEYWORD if cat == "NSFW" else NORMAL_KEYWORD
    
    res_item['isEnabled'] = False
    res_item['searchable'] = False
    res_item['delay'] = 9999
    
    try:
        start_time = time.time()
        test_url = f"{item['url']}?wd={search_word}&ac=detail"
        resp = requests.get(test_url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        
        if resp.status_code == 200:
            res_item['isEnabled'] = True
            res_item['delay'] = int((time.time() - start_time) * 1000)
            content = resp.text
            if any(k in content for k in ['"list":[{', '<list>', search_word]):
                res_item['searchable'] = True
    except:
        pass
    
    res_item['score'] = calculate_score(res_item)
    return res_item

def update_readme(all_results):
    """更新 README：分类清晰，无冗余标注"""
    current_time = time.strftime("%Y-%m-%d %H:%M:%S")
    
    content = "# 🛰️ API 实时监控中心\n\n"
    content += f"更新时间：`{current_time}`\n\n"
    
    def build_table(title, data_list):
        if not data_list: return ""
        table = f"### {title}\n"
        table += "| 序号 | 线路名称 | 状态 | 搜索 | 延迟 | 广告 | 原始名称 |\n"
        table += "| :--- | :--- | :---: | :---: | :---: | :--- | :--- |\n"
        for idx, item in enumerate(data_list, 1):
            s = "✅" if item['isEnabled'] else "❌"
            q = "🔍" if item['searchable'] else "－"
            d = f"{item['delay']}ms" if item['isEnabled'] else "N/A"
            table += f"| {idx:02d} | **{item['name']}** | {s} | {q} | {d} | {item['adContext']} | {item.get('originalName', '-')} |\n"
        return table + "\n"

    # 过滤与分组逻辑
    # 极速直连：Official 且 无跑马灯
    official = [i for i in all_results if i.get('isOfficial') and "跑马灯" not in i.get('adContext','') and i.get('category') != 'NSFW']
    # 优质线路：非Official 且 无广告
    premium = [i for i in all_results if not i.get('isOfficial') and "无广告" in i.get('adContext','') and i.get('category') != 'NSFW']
    # 备用线路：有广告 或 有跑马灯
    backup = [i for i in all_results if ("无广告" not in i.get('adContext','') or "跑马灯" in i.get('adContext','')) and i.get('category') != 'NSFW']
    # NSFW
    nsfw = [i for i in all_results if i.get('category') == 'NSFW']

    content += build_table("⚡ 极速直连", official)
    content += build_table("💎 优质线路", premium)
    content += build_table("🛠️ 备用线路", backup)
    content += "### 🔞 NSFW 秘密通道\n<details>\n<summary>点击展开</summary>\n\n"
    content += build_table("", nsfw).replace("### ","")
    content += "\n</details>\n"

    with open('README.md', 'w', encoding='utf-8') as f:
        f.write(content)

def main():
    print("🚀 启动检测流程...")
    try:
        with open(ORIGINAL_FILE, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
    except:
        print(f"❌ 无法读取 {ORIGINAL_FILE}")
        return

    # 并发检测
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        results = list(executor.map(check_source, raw_data))

    # 全局按分数排序
    results.sort(key=lambda x: -x['score'])

    # 动态重命名逻辑
    counters = {"极速直连": 1, "优质线路": 1, "备用线路": 1, "[NSFW] 秘密通道": 1}
    
    for item in results:
        # 修正 adContext 显示逻辑：无广告或空则设为"未知"
        raw_ad = item.get('adContext', '')
        if "无广告" in raw_ad or not raw_ad:
            item['adContext'] = "未知"

        # 分组命名
        if item.get('category') == 'NSFW':
            p = "[NSFW] 秘密通道"
        elif item.get('isOfficial') and "跑马灯" not in raw_ad:
            p = "极速直连"
        elif item.get('adContext') == "未知": # 此时已统一为未知
            p = "优质线路"
        else:
            p = "备用线路"
        
        item['name'] = f"{p} {counters[p]:02d}"
        counters[p] += 1

    # --- 三档文件输出 ---
    
    # 1. 常规资源 (不含 NSFW)
    clean_data = [i for i in results if i.get('category') != 'NSFW']
    with open(CLEAN_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(clean_data, f, ensure_ascii=False, indent=2)

    # 2. 成人资源 (仅限 NSFW)
    nsfw_data = [i for i in results if i.get('category') == 'NSFW']
    with open('nsfw_status.json', 'w', encoding='utf-8') as f:
        json.dump(nsfw_data, f, ensure_ascii=False, indent=2)

    # 3. 全量资源 (包含所有)
    with open(FULL_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    # 输出 README
    update_readme(results)
    print(f"✅ 任务完成：\n - 常规源: {len(clean_data)} 个\n - 成人源: {len(nsfw_data)} 个\n - 总计: {len(results)} 个")

if __name__ == "__main__":
    main()
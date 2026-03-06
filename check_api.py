import requests
import json
import concurrent.futures
import time
import os

# --- 配置 ---
ORIGINAL_FILE = 'sources.json'
CLEAN_OUTPUT = 'clean_status.json'   # 常规版 (无成人)
NSFW_OUTPUT = 'nsfw_status.json'    # 成人版 (仅限成人)
FULL_OUTPUT = 'full_status.json'     # 全量版 (汇总)
README_FILE = 'README.md'
TIMEOUT = 10

# 搜索关键词（用于验证接口是否可用）
NORMAL_KEYWORD = "我的团长我的团"
NSFW_KEYWORD = "臀" 

def calculate_score(item):
    """
    严格权重算法：
    1. 延迟权重：1000ms基准，每快1ms加1分
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
        score -= 1000  # 大幅扣分
        
    # 官方直采
    if item.get('isOfficial'):
        score += 200
        
    # 搜索支持
    if item.get('searchable'):
        score += 100
        
    return score

def check_source(item):
    """单条线路检测逻辑"""
    res_item = item.copy()
    cat = res_item.get('category', 'General')
    search_word = NSFW_KEYWORD if cat == "NSFW" else NORMAL_KEYWORD
    
    res_item['isEnabled'] = False
    res_item['searchable'] = False
    res_item['delay'] = 9999
    
    try:
        start_time = time.time()
        # 构造检测 URL
        test_url = f"{item['url']}?wd={search_word}&ac=detail"
        resp = requests.get(test_url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        
        if resp.status_code == 200:
            res_item['isEnabled'] = True
            res_item['delay'] = int((time.time() - start_time) * 1000)
            content = resp.text
            # 简单校验返回内容是否包含有效数据结构
            if any(k in content for k in ['"list":[{', '<list>', search_word]):
                res_item['searchable'] = True
    except:
        pass
    
    res_item['score'] = calculate_score(res_item)
    return res_item

def update_readme(all_results):
    """更新 README 列表"""
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
            ad = item.get('adContext', '未知')
            orig = item.get('originalName', '-')
            table += f"| {idx:02d} | {item['name']} | {s} | {q} | {d} | {ad} | {orig} |\n"
        return table + "\n"

    # 分组逻辑
    official = [i for i in all_results if i.get('isOfficial') and "跑马灯" not in i.get('adContext','') and i.get('category') != 'NSFW']
    premium = [i for i in all_results if not i.get('isOfficial') and ("无广告" in i.get('adContext','') or i.get('adContext') == "未知") and i.get('category') != 'NSFW']
    backup = [i for i in all_results if ("无广告" not in i.get('adContext','') and i.get('adContext') != "未知") and i.get('category') != 'NSFW']
    nsfw = [i for i in all_results if i.get('category') == 'NSFW']

    content += build_table("⚡ 极速直连", official)
    content += build_table("💎 优质线路", premium)
    content += build_table("🛠️ 备用线路", backup)
    content += "### 🔞 NSFW 秘密通道\n<details>\n<summary>点击展开</summary>\n\n"
    content += build_table("", nsfw).replace("### ","")
    content += "\n</details>\n"

    with open(README_FILE, 'w', encoding='utf-8') as f:
        f.write(content)

def main():
    print("🚀 启动检测与三档文件分离流程...")
    
    if not os.path.exists(ORIGINAL_FILE):
        print(f"❌ 无法找到源文件 {ORIGINAL_FILE}")
        return

    with open(ORIGINAL_FILE, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        results = list(executor.map(check_source, raw_data))

    # 1. 基础过滤：只有 [能连通] 且 [能搜索] 的才进入后续流程
    # 如果你希望保留不能搜索但能直连的，可以去掉 and i['searchable']
    valid_results = [i for i in results if i['isEnabled'] and i['searchable']]
    
    # 2. 全局按分数排序
    valid_results.sort(key=lambda x: -x['score'])

    counters = {"极速直连": 1, "优质线路": 1, "备用线路": 1, "[NSFW] 秘密通道": 1}
    final_ordered_results = []

    for item in valid_results:
        raw_ad = item.get('adContext', '')
        processed_ad = "未知" if ("无广告" in raw_ad or not raw_ad) else raw_ad
        
        # 分类逻辑
        if item.get('category') == 'NSFW':
            p = "[NSFW] 秘密通道"
        elif item.get('isOfficial') and "跑马灯" not in raw_ad:
            p = "极速直连"
        elif processed_ad == "未知":
            p = "优质线路"
        else:
            p = "备用线路"
        
        # --- 策略修改：备用线路逻辑控制 ---
        # 如果是备用线路，且序号已经排到 5 以后，则强制设为不启用状态（isEnabled = False）
        # 这样订阅里会有这条数据，但客户端默认不会调用它
        if p == "备用线路" and counters[p] > 5:
            item['isEnabled'] = False

        target_name = f"{p} {counters[p]:02d}"
        counters[p] += 1

        # 重新构造字典
        new_item = {}
        item.pop('name', None)
        inserted = False
        for key, value in item.items():
            if key == 'originalName':
                new_item['name'] = target_name
                inserted = True
            if key == 'adContext':
                new_item[key] = processed_ad
            else:
                new_item[key] = value
        
        if not inserted:
            new_item['name'] = target_name
            
        final_ordered_results.append(new_item)

    # --- 写入三档输出文件 ---
    
    # 1. 常规资源 (过滤掉 NSFW)
    clean_data = [i for i in final_ordered_results if i.get('category') != 'NSFW']
    with open(CLEAN_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(clean_data, f, ensure_ascii=False, indent=2)

    # 2. 成人资源 (仅包含 NSFW)
    nsfw_data = [i for i in final_ordered_results if i.get('category') == 'NSFW']
    with open(NSFW_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(nsfw_data, f, ensure_ascii=False, indent=2)

    # 3. 全量资源 (合并所有)
    with open(FULL_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(final_ordered_results, f, ensure_ascii=False, indent=2)
    
    # 更新说明文档
    update_readme(final_ordered_results)
    
    print("\n✅ 任务处理完成！")
    print(f" 📂 {CLEAN_OUTPUT} : {len(clean_data)} 条记录")
    print(f" 📂 {NSFW_OUTPUT}  : {len(nsfw_data)} 条记录")
    print(f" 📂 {FULL_OUTPUT}   : {len(final_ordered_results)} 条记录")
    
if __name__ == "__main__":
    main()

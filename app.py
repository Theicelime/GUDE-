import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random
from datetime import datetime
import os
import json
import re

# --- 配置部分 ---
HISTORY_FILE = "search_history.json"
BASE_URL = "https://www.gooood.cn"

# 模拟浏览器请求头 (模拟 Chrome 120)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive"
}

# --- 辅助函数 ---

def load_history():
    """加载历史记录"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(record):
    """保存历史记录"""
    history = load_history()
    record['saved_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    history.insert(0, record)
    if len(history) > 20: 
        history = history[:20]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=4)

def has_brackets(title):
    """检查标题是否包含括号 (支持中文和英文)"""
    if not title: return False
    # 严格按照你给的参考代码逻辑：有任何一种括号就过滤
    return (re.search(r'（[^）]*）', title) is not None or 
            re.search(r'\([^)]*\)', title) is not None)

def contains_chinese(text):
    """检查是否包含中文"""
    if not text: return False
    return bool(re.search(r'[\u4e00-\u9fff]+', text))

def fetch_detail_and_count(article_url, target_user="false"):
    """
    [严格执行] 进入详情页获取真实数据
    不管列表页说什么，都以这里抓到的为准。
    """
    try:
        # 必须有延时，否则连续请求会被封
        time.sleep(random.uniform(0.5, 1.2))
        
        resp = requests.get(article_url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None, 0, f"Error {resp.status_code}"
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # --- 抓取评论者逻辑 ---
        # 寻找评论主体
        comment_elements = soup.select('.comment-body')
        if not comment_elements:
            # 备用：有些老页面结构不同
            comment_elements = soup.select('li.comment')
            
        authors = []
        for c in comment_elements:
            # 尝试获取作者名，兼容多种 class
            author_tag = c.select_one('.fn') or c.select_one('.comment-author') or c.select_one('.url')
            if author_tag:
                authors.append(author_tag.get_text(strip=True))
        
        real_count = len(authors)
        
        # --- 过滤逻辑 ---
        if real_count == 0:
            return True, 0, "无评论" # 标记为有效访问，但数量为0

        # 检查是否只有 target_user
        unique_authors = set(authors)
        # 转换为小写比较
        target_user_lower = target_user.lower()
        unique_lower = {u.lower() for u in unique_authors}
        
        if len(unique_lower) == 1 and target_user_lower in unique_lower:
            return False, real_count, f"仅含用户 {target_user}"
            
        return True, real_count, "有效"

    except Exception as e:
        return None, 0, f"解析异常: {str(e)}"

def scrape_logic_strict(start_page, end_page, min_comments, target_user_filter):
    """
    [严格模式爬虫]
    逻辑：遍历列表 -> 标题清洗 -> 强制进详情页 -> 统计筛选
    """
    results = []
    
    # 界面元素
    status_text = st.empty()
    progress_bar = st.progress(0)
    log_area = st.empty() # 用于显示实时处理的标题
    
    total_pages = end_page - start_page + 1
    
    # 统计
    stats = {"processed": 0, "hit": 0}
    
    for i, page in enumerate(range(start_page, end_page + 1)):
        # 更新总进度
        progress_percentage = (i) / total_pages
        progress_bar.progress(progress_percentage)
        
        url = f"{BASE_URL}/page/{page}" if page > 1 else BASE_URL
        status_text.markdown(f"**📄 正在处理第 {page} 页...** (已命中: {stats['hit']} 个)")
        
        try:
            # 1. 获取列表页
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                st.warning(f"⚠️ 第 {page} 页访问失败 (Code: {resp.status_code})")
                continue
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            articles = soup.select('.post') 
            
            if not articles:
                st.info(f"第 {page} 页没有找到文章，停止。")
                break

            # 2. 遍历该页的所有文章
            page_articles = []
            # 先把这一页的标题和链接都提取出来，避免在循环里操作 soup 对象出错
            for art in articles:
                t_tag = art.select_one('h2 a') or art.select_one('h1 a') or art.select_one('.entry-title a')
                if t_tag:
                    title = t_tag.get_text(strip=True)
                    link = t_tag['href']
                    page_articles.append((title, link))
            
            # 3. 对提取出的文章逐个进行详情页检查
            for idx, (title, link) in enumerate(page_articles):
                
                # --- A. 标题清洗 (本地快速过滤) ---
                if not contains_chinese(title): 
                    continue # 无中文，跳过
                if has_brackets(title): 
                    continue # 有括号，跳过
                
                # --- B. 强制进入详情页 (网络请求) ---
                stats["processed"] += 1
                log_area.text(f"正在检查 [{stats['processed']}] : {title[:30]}...")
                
                is_valid_user, real_count, note = fetch_detail_and_count(link, target_user_filter)
                
                # --- C. 结果判断 ---
                # is_valid_user=None 表示请求报错
                # is_valid_user=False 表示只有 false 用户
                # is_valid_user=True 表示用户检查通过
                
                if is_valid_user is True:
                    if real_count >= min_comments:
                        # 符合条件！
                        results.append({
                            "页码": page,
                            "标题": title,
                            "链接": link,
                            "评论数": real_count,
                            "状态": note
                        })
                        stats["hit"] += 1
            
        except Exception as e:
            st.error(f"第 {page} 页发生严重错误: {e}")
            
    progress_bar.progress(100)
    status_text.success(f"✅ 抓取完成！共检查 {stats['processed']} 篇，符合条件 {stats['hit']} 篇。")
    log_area.empty()
    return results

# --- Streamlit 界面 ---

st.set_page_config(page_title="Gooood 严格筛选工具", layout="wide", page_icon="🏛️")

st.title("🏛️ Gooood.cn 案例筛选 (严格模式)")
st.markdown("""
**严格模式逻辑**：
1. **标题清洗**：保留含中文且不含括号的标题。
2. **强制检查**：对所有清洗后的标题，**逐一进入详情页**统计真实评论数。
3. **精准过滤**：剔除 `false` 用户，保留评论数 >= N 的案例。
""")

with st.sidebar:
    st.header("🛠️ 参数设置")
    col_p1, col_p2 = st.columns(2)
    start_p = col_p1.number_input("起始页码", min_value=1, value=100, step=1)
    end_p = col_p2.number_input("结束页码", min_value=1, value=102, step=1)
    
    st.caption("⚠️ 注意：因为要进入每个详情页，速度会比粗略扫描慢，但数据绝对准确。建议一次扫描 5-10 页。")
    
    st.markdown("---")
    min_c = st.number_input("最小评论数 (N)", min_value=0, value=1)
    target_user = st.text_input("剔除单一评论用户", value="false")
    st.markdown("---")
    run_btn = st.button("🚀 开始严格抓取", type="primary", use_container_width=True)

tab1, tab2 = st.tabs(["📋 结果列表", "🕒 历史记录"])

with tab1:
    if run_btn:
        if start_p > end_p:
            st.error("❌ 起始页码不能大于结束页码")
        else:
            with st.spinner(f'正在对第 {start_p}-{end_p} 页进行全量检查...'):
                data = scrape_logic_strict(start_p, end_p, min_c, target_user)
            
            if data:
                df = pd.DataFrame(data)
                save_history({
                    "criteria": f"Page: {start_p}-{end_p} | Min: {min_c}",
                    "count": len(data),
                    "data": data
                })
                
                st.success(f"✅ 找到 {len(data)} 个案例！")
                st.data_editor(
                    df,
                    column_config={
                        "链接": st.column_config.LinkColumn("点击查看"),
                        "评论数": st.column_config.NumberColumn("热度", format="%d 💬"),
                    },
                    hide_index=True,
                    use_container_width=True
                )
                csv = df.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 下载结果 (CSV)", csv, "gooood_strict_results.csv", "text/csv")
            else:
                st.warning("⚠️ 在指定范围内未找到满足评论数要求的案例。")

with tab2:
    st.header("历史记录")
    history_data = load_history()
    if not history_data:
        st.caption("暂无历史记录")
    else:
        for i, record in enumerate(history_data):
            with st.expander(f"📅 {record['saved_at']} - {record.get('criteria','')} (结果: {record['count']})"):
                if record['data']:
                    st.dataframe(pd.DataFrame(record['data']), hide_index=True)

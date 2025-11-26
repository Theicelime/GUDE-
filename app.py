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

# 模拟更真实的浏览器请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Referer": "https://www.gooood.cn/",
    "Upgrade-Insecure-Requests": "1"
}

# --- 辅助函数 ---

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(record):
    history = load_history()
    record['saved_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    history.insert(0, record)
    if len(history) > 20: 
        history = history[:20]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=4)

def has_brackets(title):
    if not title: return False
    return (re.search(r'（[^）]*）', title) is not None or 
            re.search(r'\([^)]*\)', title) is not None)

def contains_chinese(text):
    if not text: return False
    return bool(re.search(r'[\u4e00-\u9fff]+', text))

def extract_comment_count_from_header(soup):
    """
    [新增] 直接从页面的标题（如 '11 评论'）中提取数字
    这是最准确的来源，不依赖具体的评论 HTML 结构。
    """
    # 查找所有包含 "评论" 二字的标题标签 (h1-h6, div, span)
    targets = soup.find_all(['h3', 'h2', 'h4', 'div', 'span'], string=re.compile(r'评论|Comments'))
    
    for t in targets:
        text = t.get_text(strip=True)
        # 尝试匹配 "11 评论", "11 Comments", "评论: 11"
        match = re.search(r'(\d+)\s*(条)?(评论|Comments?)', text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        
        # 尝试匹配 "评论 (11)"
        match2 = re.search(r'(评论|Comments?)\s*[:\uff1a\(（]\s*(\d+)', text, re.IGNORECASE)
        if match2:
            return int(match2.group(2))
            
    return 0

def fetch_detail_and_count(article_url, target_user="false"):
    """
    [超级增强版] 进入详情页获取数据
    """
    try:
        time.sleep(random.uniform(0.3, 0.8)) # 随机延时
        
        resp = requests.get(article_url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None, 0, f"Error {resp.status_code}"
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # --- 策略 A: 直接读取标题数字 (权威参考) ---
        header_count = extract_comment_count_from_header(soup)
        
        # --- 策略 B: 抓取作者名 (用于 false 过滤) ---
        # 扩大搜索范围，不仅仅找 comment-body
        authors = []
        
        # 常见的作者容器 class
        author_selectors = [
            '.fn',                 # 标准 WordPress
            '.comment-author',     # 常见
            '.comment-author .fn', 
            '.vcard .fn',
            'cite.fn',
            '.url'                 # 有时候作者名在 href class="url"
        ]
        
        for selector in author_selectors:
            tags = soup.select(selector)
            for tag in tags:
                name = tag.get_text(strip=True)
                if name:
                    authors.append(name)
            if authors: # 如果找到了一种，通常就够了，不用混着找
                break
        
        real_count_from_authors = len(authors)
        
        # --- 决策逻辑 ---
        
        # 1. 优先使用作者数量，因为可以过滤 false
        final_count = max(header_count, real_count_from_authors)
        
        if final_count == 0:
            return True, 0, "无评论"

        # 2. 如果抓到了作者名，执行 false 过滤
        if len(authors) > 0:
            unique_authors = set(authors)
            target_user_lower = target_user.lower()
            unique_lower = {u.lower() for u in unique_authors}
            
            if len(unique_lower) == 1 and target_user_lower in unique_lower:
                return False, final_count, f"仅含用户 {target_user}"
            
            return True, final_count, "有效"
        
        # 3. [兜底] 如果没抓到作者名，但是标题说有评论 (header_count > 0)
        # 这种情况下我们无法判断是不是 false 用户，为了不漏掉，我们默认保留！
        if header_count > 0 and len(authors) == 0:
            return True, header_count, f"显示 {header_count} 条评论 (无法读取详情)"

        return True, final_count, "有效"

    except Exception as e:
        return None, 0, f"解析异常: {str(e)}"

def scrape_logic_strict(start_page, end_page, min_comments, target_user_filter):
    results = []
    status_text = st.empty()
    progress_bar = st.progress(0)
    log_area = st.empty()
    
    total_pages = end_page - start_page + 1
    stats = {"processed": 0, "hit": 0}
    
    for i, page in enumerate(range(start_page, end_page + 1)):
        progress_percentage = (i) / total_pages
        progress_bar.progress(progress_percentage)
        
        url = f"{BASE_URL}/page/{page}" if page > 1 else BASE_URL
        status_text.markdown(f"**📄 正在处理第 {page} 页...** (已命中: {stats['hit']} 个)")
        
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                st.warning(f"⚠️ 第 {page} 页访问失败")
                continue
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            articles = soup.select('.post') 
            
            if not articles:
                # 尝试备用选择器
                articles = soup.select('article')
                
            if not articles:
                st.info(f"第 {page} 页没有找到文章，停止。")
                break

            for art in articles:
                t_tag = art.select_one('h2 a') or art.select_one('h1 a') or art.select_one('.entry-title a')
                if t_tag:
                    title = t_tag.get_text(strip=True)
                    link = t_tag['href']
                    
                    # 标题清洗
                    if not contains_chinese(title): continue
                    if has_brackets(title): continue
                    
                    stats["processed"] += 1
                    log_area.text(f"检查中: {title[:20]}...")
                    
                    # 强制检查详情页
                    is_valid_user, real_count, note = fetch_detail_and_count(link, target_user_filter)
                    
                    if is_valid_user is True:
                        if real_count >= min_comments:
                            results.append({
                                "页码": page,
                                "标题": title,
                                "链接": link,
                                "评论数": real_count,
                                "状态": note
                            })
                            stats["hit"] += 1
            
        except Exception as e:
            st.error(f"第 {page} 页错误: {e}")
            
    progress_bar.progress(100)
    status_text.success(f"✅ 抓取完成！共检查 {stats['processed']} 篇，符合条件 {stats['hit']} 篇。")
    log_area.empty()
    return results

# --- Streamlit 界面 ---

st.set_page_config(page_title="Gooood 终极筛选版", layout="wide", page_icon="🏛️")

st.title("🏛️ Gooood.cn 案例筛选 (终极修复版)")
st.markdown("""
**V3.0 更新**：
1. **权威计数**：优先读取详情页的“XX 评论”大标题，确保不错过。
2. **兜底策略**：如果能看到评论数但抓不到作者（无法判断是否为 false），默认保留，防止误删。
3. **强制检查**：对所有符合标题规范的文章，逐一进入详情页检查。
""")

with st.sidebar:
    st.header("🛠️ 参数设置")
    col_p1, col_p2 = st.columns(2)
    start_p = col_p1.number_input("起始页码", min_value=1, value=800, step=1)
    end_p = col_p2.number_input("结束页码", min_value=1, value=805, step=1)
    
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
                st.download_button("📥 下载结果 (CSV)", csv, "gooood_v3_results.csv", "text/csv")
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

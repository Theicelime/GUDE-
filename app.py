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

# 随机 User-Agent 池，防止被当作单一爬虫屏蔽
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36"
]

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Referer": "https://www.gooood.cn/"
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

def scan_html_for_count(html_text):
    """
    [核弹级] 暴力文本搜索
    不解析 DOM，直接在 HTML 源码字符串里找 "11 评论" 这种模式
    """
    count = 0
    # 模式1: "11 评论" 或 "11 条评论" 或 "11 Comments"
    # [>\"\s] 确保数字前面是标签结束符 > 或空格或引号，防止把 ID 里的数字读出来
    matches = re.findall(r'[>\"\s](\d+)\s*(?:条)?(?:评论|Comments)', html_text, re.IGNORECASE)
    if matches:
        # 找到所有匹配的数字，取最大的那个（防止抓到侧边栏的热门评论数）
        # 过滤掉过大的离谱数字（比如年份 2020）
        valid_nums = [int(m) for m in matches if int(m) < 1000]
        if valid_nums:
            count = max(valid_nums)
            
    # 模式2: "评论 (11)"
    if count == 0:
        matches2 = re.findall(r'(?:评论|Comments)\s*[:\uff1a\(（]\s*(\d+)', html_text, re.IGNORECASE)
        if matches2:
            valid_nums = [int(m) for m in matches2 if int(m) < 1000]
            if valid_nums:
                count = max(valid_nums)
    
    return count

def extract_authors(soup):
    """提取作者列表"""
    authors = []
    # 穷举所有可能的作者标签 class
    selectors = [
        '.fn', '.comment-author', 'cite', '.url', 
        '.comment-meta .author', '.comment-body b', 
        '.vcard .fn', 'a[rel="external nofollow"]'
    ]
    for sel in selectors:
        tags = soup.select(sel)
        for t in tags:
            name = t.get_text(strip=True)
            # 过滤掉一些不是人名的关键词
            if name and len(name) < 30 and "回复" not in name and "20" not in name:
                authors.append(name)
    return authors

def fetch_detail_and_count(article_url, target_user="false"):
    """
    [V4.0 逻辑]
    1. 请求网页
    2. 暴力正则搜索评论数
    3. 解析 DOM 搜索作者名
    4. 综合判断
    """
    try:
        time.sleep(random.uniform(0.5, 1.5))
        
        # 随机切换 UA
        current_headers = HEADERS.copy()
        current_headers["User-Agent"] = random.choice(USER_AGENTS)
        
        resp = requests.get(article_url, headers=current_headers, timeout=20)
        resp.encoding = 'utf-8' # 强制 UTF-8，防止乱码导致正则失败
        
        if resp.status_code != 200:
            return None, 0, f"HTTP {resp.status_code}"
        
        html_text = resp.text
        soup = BeautifulSoup(html_text, 'html.parser')
        
        # 1. 暴力搜索评论数
        regex_count = scan_html_for_count(html_text)
        
        # 2. 尝试提取作者
        authors = extract_authors(soup)
        real_author_count = len(authors)
        
        # 3. 最终数量取最大值
        final_count = max(regex_count, real_author_count)
        
        if final_count == 0:
            return True, 0, "无评论"

        # 4. 过滤逻辑
        # 只有当我们既抓到了数量，又抓到了作者名时，才能进行 false 过滤
        if len(authors) > 0:
            unique_authors = set(authors)
            target_user_lower = target_user.lower()
            # 检查是否所有作者都是 target_user
            all_match = True
            for u in unique_authors:
                if target_user_lower not in u.lower():
                    all_match = False
                    break
            
            if all_match:
                return False, final_count, f"仅含用户 {target_user}"
            else:
                return True, final_count, "有效 (已验证作者)"
        
        # 如果正则抓到了数量(例如11)，但没抓到作者名(HTML结构太怪)
        # 此时无法过滤 false，但为了不漏掉，我们必须保留！
        if regex_count > 0:
            return True, regex_count, f"检测到 {regex_count} 条评论 (作者未知)"

        return True, final_count, "有效"

    except Exception as e:
        return None, 0, f"Err: {str(e)[:20]}"

def scrape_logic_v4(start_page, end_page, min_comments, target_user_filter):
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
        status_text.markdown(f"**⚡ 正在暴力扫描第 {page} 页...** (命中: {stats['hit']})")
        
        try:
            resp = requests.get(url, headers={"User-Agent": random.choice(USER_AGENTS)}, timeout=20)
            if resp.status_code != 200:
                continue
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            # 兼容多种文章容器
            articles = soup.select('.post') or soup.select('article') or soup.select('.type-post')
            
            if not articles:
                # 如果连文章列表都抓不到，可能是反爬或者结构变了，尝试直接找 h2 a
                links = soup.select('h2 a')
                if not links:
                    st.warning(f"第 {page} 页未识别到文章列表")
                    continue
                # 构造临时 article 对象
                articles = [{'link': l['href'], 'title': l.get_text(strip=True)} for l in links]
            else:
                # 提取标准结构
                temp_articles = []
                for art in articles:
                    t_tag = art.select_one('h2 a') or art.select_one('h1 a') or art.select_one('a[rel="bookmark"]')
                    if t_tag:
                        temp_articles.append({'link': t_tag['href'], 'title': t_tag.get_text(strip=True)})
                articles = temp_articles

            for art in articles:
                title = art['title']
                link = art['link']
                
                # 清洗
                if not contains_chinese(title): continue
                if has_brackets(title): continue
                
                stats["processed"] += 1
                log_area.text(f"正在检查: {title[:25]}...")
                
                # 进入详情页
                is_valid, count, note = fetch_detail_and_count(link, target_user_filter)
                
                if is_valid is True:
                    if count >= min_comments:
                        results.append({
                            "页码": page,
                            "标题": title,
                            "链接": link,
                            "评论数": count,
                            "状态": note
                        })
                        stats["hit"] += 1
            
        except Exception as e:
            st.error(f"Page {page} error: {e}")
            
    progress_bar.progress(100)
    status_text.success(f"完成！检查 {stats['processed']} 篇，命中 {stats['hit']} 篇。")
    log_area.empty()
    return results

# --- Streamlit 界面 ---

st.set_page_config(page_title="Gooood 暴力抓取版", layout="wide", page_icon="⚡")

st.title("⚡ Gooood.cn 暴力抓取工具 (V4.0)")
st.markdown("""
**核心逻辑**：
1. **暴力正则**：直接在网页源代码中搜索 `11 评论` 或 `11 Comments` 字样，不依赖 HTML 标签。
2. **强制检查**：对所有标题合规的文章，逐一进入详情页。
3. **安全兜底**：如果检测到评论数但抓不到作者名，强制保留，防止误删。
""")

with st.sidebar:
    st.header("🛠️ 参数设置")
    col_p1, col_p2 = st.columns(2)
    start_p = col_p1.number_input("起始页码", min_value=1, value=800, step=1)
    end_p = col_p2.number_input("结束页码", min_value=1, value=805, step=1)
    
    min_c = st.number_input("最小评论数 (N)", min_value=0, value=1)
    target_user = st.text_input("剔除单一评论用户", value="false")
    run_btn = st.button("🚀 开始暴力抓取", type="primary", use_container_width=True)

tab1, tab2 = st.tabs(["📋 结果列表", "🕒 历史记录"])

with tab1:
    if run_btn:
        with st.spinner(f'正在对第 {start_p}-{end_p} 页进行暴力扫描...'):
            data = scrape_logic_v4(start_p, end_p, min_c, target_user)
        
        if data:
            df = pd.DataFrame(data)
            save_history({"criteria": f"Page: {start_p}-{end_p}", "count": len(data), "data": data})
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
        else:
            st.warning("⚠️ 未找到案例。如果这还找不到，说明该网站可能启用了高级反爬或评论是纯动态加载的。")

with tab2:
    st.header("历史记录")
    h_data = load_history()
    if h_data:
        for i, rec in enumerate(h_data):
            with st.expander(f"{rec['saved_at']} (结果: {rec['count']})"):
                if rec['data']: st.dataframe(pd.DataFrame(rec['data']), hide_index=True)

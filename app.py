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

# 随机 User-Agent
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

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

def get_real_comment_count(soup, html_text):
    """
    [V5.0 核心] 混合计算策略
    """
    # 策略 1: 数元素 (最准)
    # WordPress 通常使用 ol.commentlist > li.comment 或 .comment-list > li
    # 或者直接数 .comment-body 的数量
    count_by_tag = 0
    
    # 查找评论列表容器
    comment_list = soup.select_one('.commentlist') or soup.select_one('.comment-list')
    if comment_list:
        # 直接数列表下的 li 数量
        count_by_tag = len(comment_list.find_all('li', recursive=False))
    
    if count_by_tag == 0:
        # 如果没找到列表容器，直接数所有 class 包含 comment-body 的元素
        count_by_tag = len(soup.select('.comment-body'))
    
    # 策略 2: 正则匹配文本 (兜底)
    # 匹配 "11评论", "11 评论", "11 条评论", "Comments (11)", "评论：11"
    count_by_text = 0
    patterns = [
        r'(\d+)\s*(?:条)?\s*(?:评论|Comments?)',  # 11 评论
        r'(?:评论|Comments?)\s*[:\uff1a\(（]\s*(\d+)'  # 评论: 11
    ]
    
    for p in patterns:
        matches = re.findall(p, html_text, re.IGNORECASE)
        if matches:
            # 过滤掉年份等干扰项(假设评论数不会超过2000)
            valid = [int(m) for m in matches if int(m) < 2000]
            if valid:
                count_by_text = max(valid)
                break
    
    # 返回两者中较大的那个
    return max(count_by_tag, count_by_text), count_by_tag, count_by_text

def get_authors(soup):
    """提取所有评论者名字"""
    authors = []
    # 穷举作者标签
    selectors = ['.fn', '.comment-author', '.url', 'cite', '.vcard']
    for sel in selectors:
        for tag in soup.select(sel):
            name = tag.get_text(strip=True)
            if name and len(name) < 50: # 排除过长的错误文本
                authors.append(name)
    return authors

def process_detail_page(url, target_user, debug=False):
    """处理详情页"""
    try:
        time.sleep(random.uniform(0.5, 1.0))
        resp = requests.get(url, headers={"User-Agent": random.choice(USER_AGENTS)}, timeout=15)
        resp.encoding = 'utf-8'
        
        if resp.status_code != 200:
            return None, 0, f"HTTP {resp.status_code}"
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 1. 获取数量
        final_count, count_tag, count_text = get_real_comment_count(soup, resp.text)
        
        if debug:
            st.text(f"[DEBUG] {url}\n -> 标签统计: {count_tag}, 文本正则: {count_text} -> 最终认定: {final_count}")

        if final_count == 0:
            return True, 0, "无评论"
            
        # 2. 获取作者并过滤
        authors = get_authors(soup)
        
        # 如果有作者，进行 target_user 过滤
        if len(authors) > 0:
            unique = set([a.lower() for a in authors])
            target_lower = target_user.lower()
            
            # 如果去重后只有这一个用户
            if len(unique) == 1 and target_lower in unique:
                return False, final_count, f"仅含用户 {target_user}"
            
            return True, final_count, "有效"
            
        # 如果没抓到作者，但有数量 -> 保留
        return True, final_count, "有效 (有数量无作者详情)"

    except Exception as e:
        return None, 0, f"Error: {str(e)}"

def run_scraper(start_p, end_p, min_c, target_u, debug_mode):
    results = []
    
    status_box = st.empty()
    bar = st.progress(0)
    
    total = end_p - start_p + 1
    stats = {"checked": 0, "found": 0}
    
    for i, page in enumerate(range(start_p, end_p + 1)):
        bar.progress(i / total)
        status_box.markdown(f"**正在扫描第 {page} 页...** (已找到 {stats['found']} 个)")
        
        url = f"{BASE_URL}/page/{page}" if page > 1 else BASE_URL
        
        try:
            r = requests.get(url, headers={"User-Agent": random.choice(USER_AGENTS)}, timeout=15)
            if r.status_code != 200: continue
            
            soup = BeautifulSoup(r.text, 'html.parser')
            # 兼容多种结构
            posts = soup.select('.post') or soup.select('article')
            
            if not posts:
                # 尝试直接找链接
                if debug_mode: st.warning(f"第 {page} 页未找到 .post 元素，尝试直接搜索链接")
                h2_links = soup.select('h2 a')
                posts = [{'link': a['href'], 'title': a.get_text(strip=True)} for a in h2_links]
            else:
                # 提取标准结构
                temp = []
                for p in posts:
                    a = p.select_one('h2 a') or p.select_one('h1 a')
                    if a: temp.append({'link': a['href'], 'title': a.get_text(strip=True)})
                posts = temp
                
            for post in posts:
                title = post['title']
                link = post['link']
                
                # 标题清洗
                if not contains_chinese(title): continue
                if has_brackets(title): continue
                
                stats["checked"] += 1
                
                # 详情页检查
                is_valid, count, note = process_detail_page(link, target_u, debug_mode)
                
                if is_valid is True:
                    if count >= min_c:
                        results.append({
                            "页码": page,
                            "标题": title,
                            "评论数": count,
                            "状态": note,
                            "链接": link
                        })
                        stats["found"] += 1
                        
        except Exception as e:
            if debug_mode: st.error(f"Page {page} error: {e}")
            
    bar.progress(100)
    status_box.success(f"完成！共扫描 {stats['checked']} 篇，符合条件 {stats['found']} 篇。")
    return results

# --- UI ---

st.set_page_config(page_title="Gooood V5.0", layout="wide")
st.title("🏛️ Gooood 案例筛选 (V5.0 终极数人头版)")

with st.sidebar:
    st.header("设置")
    c1, c2 = st.columns(2)
    s_p = c1.number_input("起始页", value=800, step=1)
    e_p = c2.number_input("结束页", value=805, step=1)
    min_c = st.number_input("最小评论数", value=1, min_value=0)
    t_u = st.text_input("排除单一用户", value="false")
    
    st.markdown("---")
    debug = st.checkbox("开启调试模式 (显示详细抓取过程)", value=False)
    btn = st.button("开始抓取", type="primary", use_container_width=True)

tab1, tab2 = st.tabs(["结果", "历史"])

with tab1:
    if btn:
        if s_p > e_p:
            st.error("页码错误")
        else:
            with st.spinner("正在抓取..."):
                data = run_scraper(s_p, e_p, min_c, t_u, debug)
                
            if data:
                df = pd.DataFrame(data)
                save_history({"criteria": f"P{s_p}-{e_p}", "count": len(data), "data": data})
                st.success(f"找到 {len(data)} 条数据")
                st.data_editor(
                    df,
                    column_config={
                        "链接": st.column_config.LinkColumn(),
                        "评论数": st.column_config.NumberColumn(format="%d 💬")
                    },
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.warning("未找到数据。请尝试勾选'开启调试模式'查看具体原因。")

with tab2:
    st.header("历史")
    h = load_history()
    if h:
        for r in h:
            with st.expander(f"{r['saved_at']} ({r['count']}条)"):
                st.dataframe(pd.DataFrame(r['data']), hide_index=True)

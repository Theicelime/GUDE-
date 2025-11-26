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
    "Referer": "https://www.gooood.cn/"
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
    return (re.search(r'（[^）]*）', title) is not None or 
            re.search(r'\([^)]*\)', title) is not None)

def contains_chinese(text):
    """检查是否包含中文"""
    if not text: return False
    return bool(re.search(r'[\u4e00-\u9fff]+', text))

def get_list_page_comment_count(article_soup):
    """
    [修复核心] 尝试从列表页的文章卡片中提取评论数
    使用了多种策略，防止漏抓
    返回: (int 数量, bool 是否成功找到)
    """
    try:
        # 策略 1: 标准 class (.comments-link)
        tag = article_soup.select_one('.comments-link')
        if tag:
            nums = re.findall(r'\d+', tag.get_text())
            if nums: return int(nums[0]), True

        # 策略 2: 查找链接中包含 #comments 的 (通常是评论链接)
        links = article_soup.select('a[href*="#comments"]')
        for link in links:
            txt = link.get_text()
            # 排除 "Add a comment" 这种没有数字的
            nums = re.findall(r'\d+', txt)
            if nums: return int(nums[0]), True

        # 策略 3: 查找文本中包含 "评论" 或 "Comment" 的任何小字
        meta_tags = article_soup.select('.post-meta, .entry-meta, .meta-info')
        for meta in meta_tags:
            txt = meta.get_text()
            if "评论" in txt or "Comment" in txt:
                nums = re.findall(r'\d+', txt)
                if nums: return int(nums[0]), True
        
        # 如果都找不到，返回 0，且标记为 False (没找到明确数字)
        return 0, False
    except:
        return 0, False

def check_comments_deeply(article_url, target_user="false"):
    """
    [详情页逻辑] 进入文章详情页：获取真实评论数 + 黑名单过滤
    """
    try:
        time.sleep(random.uniform(0.3, 0.8)) # 稍微加快一点速度
        
        resp = requests.get(article_url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return False, 0, "无法访问详情页"
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 提取评论区域 (适配多种结构)
        # .comment-body 是正文, .comment-list li 是列表项
        comment_elements = soup.select('.comment-body') 
        if not comment_elements:
            comment_elements = soup.select('li.comment')
        
        authors = []
        for c in comment_elements:
            # 尝试获取作者名
            author_tag = c.select_one('.fn') or c.select_one('.comment-author') or c.select_one('.url')
            if author_tag:
                authors.append(author_tag.get_text(strip=True))
        
        real_count = len(authors)
        
        if real_count == 0:
            return False, 0, "详情页无评论"

        # --- "false" 用户排查逻辑 ---
        unique_authors = set(authors)
        if len(unique_authors) == 1 and target_user.lower() in [u.lower() for u in unique_authors]:
            return False, real_count, f"仅包含用户 {target_user}，已剔除"
            
        return True, real_count, "有效案例"

    except Exception as e:
        return False, 0, f"详情页解析误: {str(e)}"

def scrape_logic_by_pages(start_page, end_page, min_comments, target_user_filter):
    """
    [主循环]
    """
    results = []
    
    status_text = st.empty()
    progress_bar = st.progress(0)
    
    total_pages = end_page - start_page + 1
    
    # 统计数据
    stats = {"scanned": 0, "deep_checked": 0, "found": 0}
    
    for i, page in enumerate(range(start_page, end_page + 1)):
        
        progress_percentage = (i) / total_pages
        progress_bar.progress(progress_percentage)
        
        url = f"{BASE_URL}/page/{page}" if page > 1 else BASE_URL
        status_text.markdown(f"**📡 正在扫描第 {page} 页...** (已找到: {stats['found']} 个)")
        
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                st.warning(f"⚠️ 第 {page} 页返回状态码 {resp.status_code}，跳过。")
                continue
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            articles = soup.select('.post') 
            
            if not articles:
                # 尝试备用选择器，防止 Gooood 改版
                articles = soup.select('article')
            
            if not articles:
                st.warning(f"第 {page} 页未找到文章元素，可能页面结构已变或到达末尾。")
                continue

            for article in articles:
                stats["scanned"] += 1
                
                # 1. 提取标题和链接
                title_tag = article.select_one('h2 a') or article.select_one('h1 a') or article.select_one('.entry-title a')
                if not title_tag: continue
                
                title = title_tag.get_text(strip=True)
                link = title_tag['href']

                # 2. 标题清洗
                if not contains_chinese(title): continue
                if has_brackets(title): continue

                # 3. 评论数初筛 (列表页) - 核心修复部分
                raw_count, found_on_list = get_list_page_comment_count(article)
                
                # 决策逻辑：
                # A. 如果列表页明确显示数量 >= min，当然要查。
                # B. 如果列表页明确显示数量 < min (且不为0)，那就不查。
                # C. [关键] 如果列表页没找到数字 (found_on_list is False)，或者是 0，
                #    为了防止漏抓，我们假设它可能有评论，强制查详情页！
                
                should_deep_check = False
                
                if found_on_list:
                    if raw_count >= min_comments:
                        should_deep_check = True
                else:
                    # 列表页没读出来，或者读出来是0但可能是误读 -> 强制检查
                    # 除非用户设置的阈值极高(比如50)，否则都进去看看，保证不漏
                    should_deep_check = True 

                if should_deep_check:
                    # status_text.text(f"🔍 检查详情: {title[:15]}...") # 减少UI刷新频率提速
                    stats["deep_checked"] += 1
                    
                    is_valid, final_count, note = check_comments_deeply(link, target_user_filter)
                    
                    if is_valid and final_count >= min_comments:
                        results.append({
                            "页码": page,
                            "标题": title,
                            "链接": link,
                            "评论数": final_count,
                            "状态": note
                        })
                        stats["found"] += 1
            
            # 简单的防封延时
            time.sleep(0.5)
            
        except Exception as e:
            st.error(f"第 {page} 页系统错误: {e}")
            
    progress_bar.progress(100)
    status_text.success(f"完成！扫描 {stats['scanned']} 篇，深度检查 {stats['deep_checked']} 篇，命中 {stats['found']} 篇。")
    return results

# --- Streamlit 界面 ---

st.set_page_config(page_title="Gooood 案例筛选 (修复版)", layout="wide", page_icon="🏛️")

st.title("🏛️ Gooood.cn 案例筛选工具 (修复版)")
st.markdown("""
**本次更新修复了漏抓问题**：如果列表页无法读取评论数，将强制进入详情页检查，确保不错过任何一条评论。
""")

with st.sidebar:
    st.header("🛠️ 筛选设置")
    col_p1, col_p2 = st.columns(2)
    start_p = col_p1.number_input("起始页码", min_value=1, value=800, step=1)
    end_p = col_p2.number_input("结束页码", min_value=1, value=805, step=1)
    
    st.markdown("---")
    min_c = st.number_input("最小评论数 (N)", min_value=0, value=1)
    target_user = st.text_input("剔除单一评论用户", value="false")
    st.markdown("---")
    run_btn = st.button("🚀 开始抓取", type="primary", use_container_width=True)

tab1, tab2 = st.tabs(["📋 结果列表", "🕒 历史记录"])

with tab1:
    if run_btn:
        if start_p > end_p:
            st.error("❌ 起始页码不能大于结束页码")
        else:
            with st.spinner(f'正在深度扫描第 {start_p} 到 {end_p} 页...'):
                data = scrape_logic_by_pages(start_p, end_p, min_c, target_user)
            
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
                st.download_button("📥 下载结果 (CSV)", csv, "gooood_results.csv", "text/csv")
            else:
                st.warning("⚠️ 未找到符合条件的案例。如果确认有，请检查网络是否通畅。")

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

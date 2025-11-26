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

# 模拟浏览器请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
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
    if len(history) > 20: # 只保留最近20条
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

def check_comments_deeply(article_url, target_user="false"):
    """
    [核心逻辑] 进入文章详情页：
    1. 获取真实评论数
    2. 检查是否只有 'false' 用户评论
    """
    try:
        # 随机延时，防止请求过快
        time.sleep(random.uniform(0.5, 1.2))
        
        resp = requests.get(article_url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return False, 0, "无法访问详情页"
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 提取评论区域
        comment_elements = soup.select('.comment-body') 
        
        authors = []
        for c in comment_elements:
            # 适配不同 WordPress 主题结构
            author_tag = c.select_one('.fn') or c.select_one('.comment-author')
            if author_tag:
                authors.append(author_tag.get_text(strip=True))
        
        real_count = len(authors)
        
        if real_count == 0:
            return False, 0, "详情页无评论"

        # --- "false" 用户排查逻辑 ---
        unique_authors = set(authors)
        # 如果去重后的作者只有 "false" (不区分大小写)，则视为无效
        if len(unique_authors) == 1 and target_user.lower() in [u.lower() for u in unique_authors]:
            return False, real_count, f"仅包含用户 {target_user}，已剔除"
            
        return True, real_count, "有效案例"

    except Exception as e:
        return False, 0, f"解析错误: {str(e)}"

def scrape_logic_by_pages(start_page, end_page, min_comments, target_user_filter):
    """
    基于页码范围的爬虫逻辑
    """
    results = []
    
    # UI 进度显示
    status_text = st.empty()
    progress_bar = st.progress(0)
    
    total_pages = end_page - start_page + 1
    
    # 循环遍历指定的页码范围
    for i, page in enumerate(range(start_page, end_page + 1)):
        
        # 更新进度条
        progress_percentage = (i) / total_pages
        progress_bar.progress(progress_percentage)
        
        # 构建 URL
        url = f"{BASE_URL}/page/{page}" if page > 1 else BASE_URL
        status_text.markdown(f"**📡 正在扫描第 {page} 页...** ({i+1}/{total_pages})")
        
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                st.warning(f"⚠️ 第 {page} 页无法访问，可能已到达网站末尾。停止任务。")
                break
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # 获取文章列表
            articles = soup.select('.post') 
            
            if not articles:
                st.info(f"第 {page} 页未找到文章，可能已到达末尾。")
                break

            for article in articles:
                # 1. 提取标题和链接
                title_tag = article.select_one('h2 a') or article.select_one('h1 a')
                if not title_tag: continue
                
                title = title_tag.get_text(strip=True)
                link = title_tag['href']

                # 2. 标题清洗
                # A. 必须包含中文
                if not contains_chinese(title): continue
                # B. 不能包含括号
                if has_brackets(title): continue

                # 3. 评论数初筛 (列表页)
                raw_comment_count = 0
                comment_tag = article.select_one('.comments-link')
                if comment_tag:
                    txt = comment_tag.get_text()
                    nums = re.findall(r'\d+', txt)
                    if nums:
                        raw_comment_count = int(nums[0])
                
                # 4. 深度检查
                if raw_comment_count >= min_comments:
                    status_text.text(f"🔍 正在深度检查: {title[:20]}...")
                    
                    is_valid, final_count, note = check_comments_deeply(link, target_user_filter)
                    
                    if is_valid and final_count >= min_comments:
                        results.append({
                            "页码": page,
                            "标题": title,
                            "链接": link,
                            "评论数": final_count,
                            "状态": note
                        })
            
            # 防封延时
            time.sleep(1)
            
        except Exception as e:
            st.error(f"第 {page} 页抓取中断: {e}")
            break
            
    progress_bar.progress(100)
    status_text.success(f"抓取完成！范围: {start_page}-{end_page} 页")
    return results

# --- Streamlit 界面构建 ---

st.set_page_config(page_title="Gooood 案例筛选 (页码版)", layout="wide", page_icon="🏛️")

st.title("🏛️ Gooood.cn 案例筛选工具 (页码版)")
st.markdown("""
通过指定 **页码范围** 直接抓取案例。
*   **标题清洗**：自动剔除无中文或含括号 `()` `（）` 的标题。
*   **黑名单**：自动剔除仅由指定用户（如 `false`）评论的案例。
""")

# --- 侧边栏 ---
with st.sidebar:
    st.header("🛠️ 筛选设置")
    
    col_p1, col_p2 = st.columns(2)
    # 页码输入
    start_p = col_p1.number_input("起始页码", min_value=1, value=100, step=1)
    end_p = col_p2.number_input("结束页码", min_value=1, value=110, step=1)
    
    st.caption(f"计划扫描: **{end_p - start_p + 1}** 个页面")
    
    st.markdown("---")
    
    # 评论数设置
    min_c = st.number_input("最小评论数 (N)", min_value=0, value=5)
    
    # 用户过滤
    target_user = st.text_input("剔除单一评论用户", value="false")
    
    st.markdown("---")
    run_btn = st.button("🚀 开始抓取", type="primary", use_container_width=True)

# --- 主界面 ---

tab1, tab2 = st.tabs(["📋 结果列表", "🕒 历史记录"])

with tab1:
    if run_btn:
        if start_p > end_p:
            st.error("❌ 错误：起始页码不能大于结束页码！")
        else:
            with st.spinner(f'正在扫描第 {start_p} 到 {end_p} 页...'):
                data = scrape_logic_by_pages(start_p, end_p, min_c, target_user)
            
            if data:
                df = pd.DataFrame(data)
                
                # 保存历史
                save_history({
                    "criteria": f"Page: {start_p}-{end_p} | Min: {min_c}",
                    "count": len(data),
                    "data": data
                })
                
                st.success(f"✅ 完成！共扫描 {end_p - start_p + 1} 页，找到 {len(data)} 个符合条件的案例。")
                
                # 展示表格
                st.data_editor(
                    df,
                    column_config={
                        "链接": st.column_config.LinkColumn("点击查看"),
                        "评论数": st.column_config.NumberColumn("热度", format="%d 💬"),
                        "页码": st.column_config.NumberColumn("来源页", format="第 %d 页"),
                    },
                    hide_index=True,
                    use_container_width=True
                )
                
                # CSV 下载
                csv = df.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 下载结果 (CSV)", csv, "gooood_pages_result.csv", "text/csv")
                
            else:
                st.warning("⚠️ 在指定页码范围内未找到符合条件的案例。")

with tab2:
    st.header("历史记录")
    history_data = load_history()
    
    if not history_data:
        st.caption("暂无历史记录")
    
    for i, record in enumerate(history_data):
        with st.expander(f"📅 {record['saved_at']} - {record['criteria']} (结果: {record['count']})"):
            if record['data']:
                h_df = pd.DataFrame(record['data'])
                st.dataframe(
                    h_df,
                    column_config={"链接": st.column_config.LinkColumn("链接")},
                    hide_index=True,
                    use_container_width=True
                )
                h_csv = h_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button(f"下载此记录", h_csv, key=f"hist_{i}")

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

# 模拟浏览器请求头 (防止被反爬)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
}

# --- 逻辑处理函数 (基于你的参考代码移植) ---

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
    # 添加时间戳
    record['saved_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    history.insert(0, record)  # 插入到最前面
    # 限制历史记录数量，防止文件过大
    if len(history) > 20:
        history = history[:20]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=4)

def parse_date(date_str):
    """解析日期，兼容 gooood 的格式"""
    if not date_str: return None
    try:
        # 清理字符串，gooood 有时用 . 有时用 -
        date_str = date_str.strip().replace('.', '-')
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except:
        return None

def has_brackets(title):
    """
    [移植功能] 检查标题是否包含括号
    支持中文括号（）和英文括号()
    """
    if not title:
        return False
    # 检查中文括号
    chinese_brackets = re.search(r'（[^）]*）', title)
    # 检查英文括号
    english_brackets = re.search(r'\([^)]*\)', title)
    return chinese_brackets is not None or english_brackets is not None

def contains_chinese(text):
    """[移植功能] 检查是否包含中文"""
    if not text:
        return False
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]+')
    return bool(chinese_pattern.search(text))

def check_comments_deeply(article_url, target_user="false"):
    """
    [核心逻辑] 进入文章详情页：
    1. 获取真实评论数
    2. 检查是否只有 'false' 用户评论
    返回: (是否保留, 真实数量, 备注信息)
    """
    try:
        # 随机延时，防止请求过快被封
        time.sleep(random.uniform(0.5, 1.2))
        
        resp = requests.get(article_url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return False, 0, "无法访问详情页"
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # --- 提取评论者逻辑 ---
        # 说明：Wordpress 常见的评论者 class 是 .fn 或 .comment-author
        # 如果 gooood 改版，这里可能需要调整 CSS 选择器
        comment_elements = soup.select('.comment-body') 
        
        authors = []
        for c in comment_elements:
            # 尝试获取作者名
            author_tag = c.select_one('.fn') or c.select_one('.comment-author')
            if author_tag:
                authors.append(author_tag.get_text(strip=True))
        
        real_count = len(authors)
        
        if real_count == 0:
            return False, 0, "详情页无评论"

        # --- "false" 用户排查逻辑 ---
        # 你的需求：如果只有这个用户评论，删除
        unique_authors = set(authors)
        
        # 如果去重后的作者只有 "false" (不区分大小写)，则视为无效
        if len(unique_authors) == 1 and target_user.lower() in [u.lower() for u in unique_authors]:
            return False, real_count, f"仅包含用户 {target_user}，已剔除"
            
        return True, real_count, "有效案例"

    except Exception as e:
        return False, 0, f"解析错误: {str(e)}"

def scrape_logic(start_date, end_date, min_comments, target_user_filter):
    """
    主爬虫逻辑
    """
    results = []
    page = 1
    keep_scraping = True
    
    # UI 占位符
    status_text = st.empty()
    progress_bar = st.progress(0)
    
    # 转换日期格式以便比较
    start_date = pd.to_datetime(start_date).date()
    end_date = pd.to_datetime(end_date).date()

    while keep_scraping:
        # 构建 URL
        url = f"{BASE_URL}/page/{page}" if page > 1 else BASE_URL
        status_text.markdown(f"**正在扫描第 {page} 页...**")
        
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                st.warning(f"页面 {url} 无法访问，爬虫停止。")
                break
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # 获取文章列表 (Gooood 常见的文章容器 class 是 .post)
            articles = soup.select('.post') 
            
            if not articles:
                st.info("未找到更多文章，已到达末尾。")
                break

            for i, article in enumerate(articles):
                # 1. 提取日期
                date_tag = article.select_one('.time') or article.select_one('.entry-date')
                if not date_tag: continue
                
                article_date = parse_date(date_tag.get_text())
                if not article_date: continue

                # 2. 日期范围判断
                if article_date > end_date:
                    continue # 太新了，跳过，继续找同一页的下一个
                if article_date < start_date:
                    keep_scraping = False # 太旧了，整个循环结束
                    break
                
                # 3. 提取标题和链接
                title_tag = article.select_one('h2 a') or article.select_one('h1 a')
                if not title_tag: continue
                
                title = title_tag.get_text(strip=True)
                link = title_tag['href']

                # --- 移植的过滤逻辑 ---
                # A. 必须包含中文
                if not contains_chinese(title):
                    continue
                # B. 不能包含括号
                if has_brackets(title):
                    # print(f"过滤掉括号标题: {title}")
                    continue

                # 4. 初步评论数筛选 (在列表页快速筛选)
                # 列表页通常显示 "15 Comments"
                raw_comment_count = 0
                comment_tag = article.select_one('.comments-link')
                if comment_tag:
                    txt = comment_tag.get_text()
                    # 提取数字
                    nums = re.findall(r'\d+', txt)
                    if nums:
                        raw_comment_count = int(nums[0])
                
                # 只有列表页显示的评论数 > N，才进去细查
                # 优化：如果 min_comments 很小，可能不需要这一步，但为了效率还是加上
                if raw_comment_count >= min_comments:
                    
                    status_text.text(f"正在深度检查: {title[:20]}...")
                    
                    # 进入详情页检查 (检查是否有 false 用户)
                    is_valid, final_count, note = check_comments_deeply(link, target_user_filter)
                    
                    if is_valid and final_count >= min_comments:
                        results.append({
                            "日期": str(article_date),
                            "标题": title,
                            "链接": link,
                            "评论数": final_count,
                            "状态": note
                        })
            
            # 更新进度条 (模拟效果)
            if page % 5 == 0:
                progress_bar.progress(min(page / 50, 1.0))
                
            page += 1
            # 简单的防封延时
            time.sleep(1)
            
        except Exception as e:
            st.error(f"抓取中断: {e}")
            break
            
    progress_bar.progress(100)
    status_text.success("抓取完成！")
    return results

# --- Streamlit 界面构建 ---

st.set_page_config(page_title="Gooood 案例筛选器 (Web版)", layout="wide", page_icon="🏛️")

st.title("🏛️ Gooood.cn 案例筛选工具")
st.markdown("""
这是一个基于 **Python Streamlit** 的 Web 工具，移植了原有的筛选逻辑：
1. **日期筛选**：精准定位时间段。
2. **标题清洗**：自动剔除不含中文或包含括号 `()` `（）` 的标题。
3. **用户黑名单**：自动剔除仅由指定用户（如 `false`）评论的案例。
""")

# --- 侧边栏：设置 ---
with st.sidebar:
    st.header("🛠️ 筛选条件设置")
    
    # 日期设置
    col_d1, col_d2 = st.columns(2)
    start_d = col_d1.date_input("开始日期", value=pd.to_datetime("2023-01-01"))
    end_d = col_d2.date_input("结束日期", value=datetime.now())
    
    # 评论数设置
    min_c = st.number_input("最小评论数 (N)", min_value=0, value=5, help="只有大于等于此数量的案例才会被保留")
    
    # 用户过滤设置
    target_user = st.text_input("剔除单一评论用户", value="false", help="如果某案例的所有评论都仅来自此用户名，该案例将被剔除。")
    
    st.markdown("---")
    run_btn = st.button("🚀 开始抓取", type="primary", use_container_width=True)

# --- 主界面：结果展示 ---

tab1, tab2 = st.tabs(["📋 当前查询结果", "🕒 历史记录"])

with tab1:
    if run_btn:
        if start_d > end_d:
            st.error("❌ 错误：开始日期不能晚于结束日期！")
        else:
            with st.spinner('正在连接 gooood.cn 进行数据抓取与分析，请稍候...'):
                # 运行爬虫
                data = scrape_logic(start_d, end_d, min_c, target_user)
            
            if data:
                df = pd.DataFrame(data)
                
                # 保存本次结果到历史
                save_history({
                    "criteria": f"{start_d} ~ {end_d} | Min: {min_c}",
                    "count": len(data),
                    "data": data
                })
                
                st.success(f"✅ 成功找到 {len(data)} 个符合条件的案例！")
                
                # 显示交互式表格
                st.data_editor(
                    df,
                    column_config={
                        "链接": st.column_config.LinkColumn("点击跳转"),
                        "评论数": st.column_config.NumberColumn("评论热度", format="%d 💬"),
                    },
                    hide_index=True,
                    use_container_width=True
                )
                
                # 下载按钮区
                c1, c2 = st.columns(2)
                # CSV 下载
                csv = df.to_csv(index=False).encode('utf-8-sig')
                c1.download_button("📥 下载为 CSV", csv, "gooood_cases.csv", "text/csv", use_container_width=True)
                
                # Excel 下载 (需要 openpyxl)
                # 为了简单起见，这里演示 CSV，如果需要 Excel，需确保安装 openpyxl 并使用 pd.to_excel
            else:
                st.warning("⚠️ 在指定条件下未找到任何案例。")

with tab2:
    st.header("历史查询记录")
    history_data = load_history()
    
    if not history_data:
        st.caption("暂无历史记录")
    
    for i, record in enumerate(history_data):
        with st.expander(f"📅 {record['saved_at']} - 找到 {record['count']} 个案例"):
            st.caption(f"筛选条件: {record['criteria']}")
            if record['data']:
                h_df = pd.DataFrame(record['data'])
                st.dataframe(
                    h_df,
                    column_config={"链接": st.column_config.LinkColumn("链接")},
                    hide_index=True,
                    use_container_width=True
                )
                # 历史记录下载
                h_csv = h_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button(f"下载此记录 (CSV)", h_csv, key=f"hist_{i}")

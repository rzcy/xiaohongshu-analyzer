"""
小红书爆款拆解器 - Streamlit Demo
用户通过书签一键提取笔记数据 → 粘贴到此页面 → 数据洞察 + AI拆解分析
部署：Streamlit Cloud
"""

import json
import math
from datetime import datetime, timezone
from collections import Counter
import streamlit as st
from openai import OpenAI
from knowledge_base import get_full_prompt

# ============ 页面配置 ============
st.set_page_config(page_title="小红书爆款拆解器", page_icon="🔥", layout="centered")
st.title("🔥 小红书爆款拆解器")
st.caption("一键提取 + 数据洞察 + AI 深度拆解，帮你看懂爆款为什么火")

# ============ 侧边栏 ============
with st.sidebar:
    st.header("⚙️ 设置")
    default_key = ""
    try:
        default_key = st.secrets.get("DEEPSEEK_API_KEY", "")
    except Exception:
        pass
    api_key = st.text_input("DeepSeek API Key", value=default_key, type="password",
                            help="[点此免费注册获取](https://platform.deepseek.com)")
    api_base = st.text_input("API Base URL", value="https://api.deepseek.com")
    model = st.text_input("模型", value="deepseek-chat")
    category = st.selectbox(
        "📂 笔记品类（可选，提升分析精准度）",
        ["通用", "美妆", "穿搭", "美食", "家居", "母婴", "职场", "旅行"]
    )
    st.divider()
    st.caption("单次分析成本 ≈ ¥0.002")


# ============ 书签脚本（增强版：提取更多字段） ============
BOOKMARKLET = """javascript:void(function(){try{var s=window.__INITIAL_STATE__;if(!s||!s.note){alert('请在小红书笔记页面使用');return}var cid=s.note.currentNoteId;var noteId=(cid&&cid._value)?cid._value:(typeof cid==='string'?cid:'');var m=s.note.noteDetailMap;var keys=Object.keys(m).filter(function(k){return k&&k!=='undefined'&&k.length>5});var key=noteId&&m[noteId]?noteId:keys[0];if(!key){alert('未找到笔记数据，请刷新页面重试');return}var entry=m[key];var raw=entry.__v_raw||entry;var d=raw.note.__v_raw||raw.note;if(!d||!d.title){alert('笔记数据为空，请刷新重试');return}var interact=d.interactInfo?(d.interactInfo.__v_raw||d.interactInfo):{};var user=d.user?(d.user.__v_raw||d.user):{};var tags=d.tagList?(d.tagList.__v_raw||d.tagList):[];var imgs=d.imageList?(d.imageList.__v_raw||d.imageList):[];var imgUrls=Array.from(imgs||[]).map(function(img){var i=img.__v_raw||img;return{url:i.urlDefault||i.urlPre||'',w:i.width||0,h:i.height||0}}).filter(function(x){return x.url});var vid=d.video?(d.video.__v_raw||d.video):null;var videoInfo=null;if(vid){var media=vid.media?(vid.media.__v_raw||vid.media):null;if(media){var vs=media.stream?(media.stream.__v_raw||media.stream):{};var h264=vs.h264||[];var best=h264[0]||{};var vv=media.video?(media.video.__v_raw||media.video):{};videoInfo={url:best.masterUrl||'',duration:vv.duration||0,height:best.height||0}}else{videoInfo={url:vid.url||vid.urlDefault||'',duration:vid.duration||0,height:0}}}var r={title:d.title||'',content:d.desc||'',tags:Array.from(tags||[]).map(function(t){return t.name||t}),likes:parseInt(interact.likedCount||0),collects:parseInt(interact.collectedCount||0),comments:parseInt(interact.commentCount||0),shares:parseInt(interact.shareCount||0),author:user.nickname||'',noteType:d.type||'normal',images:imgUrls,video:videoInfo,time:d.time||''};var ta=document.createElement('textarea');ta.value=JSON.stringify(r);document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);alert('✅ 已复制！回到拆解器页面粘贴即可')}catch(e){alert('提取失败：'+e.message+'\\n请确认当前在笔记详情页')}})()"""


# ============ 数据分析函数 ============
def extract_hours_from_timestamp(time_value) -> float:
    """从笔记的 time 字段计算距现在的小时数
    
    支持格式：
    - 数字时间戳（秒级/毫秒级）
    - ISO 格式字符串
    - 小红书中文相对时间："刚刚"、"X分钟前"、"X小时前"、"X天前"、"昨天 HH:MM"
    - 小红书日期格式："MM-DD"、"YYYY-MM-DD"
    """
    import re
    if not time_value:
        return None
    try:
        if isinstance(time_value, str):
            time_value = time_value.strip()
            if not time_value:
                return None
            
            # 1. 中文相对时间解析
            if "刚刚" in time_value:
                return 0.5
            
            m = re.match(r'(\d+)\s*分钟前', time_value)
            if m:
                return max(int(m.group(1)) / 60, 0.5)
            
            m = re.match(r'(\d+)\s*小时前', time_value)
            if m:
                return max(float(m.group(1)), 1)
            
            m = re.match(r'(\d+)\s*天前', time_value)
            if m:
                return float(m.group(1)) * 24
            
            if "昨天" in time_value:
                return 24.0
            
            if "前天" in time_value:
                return 48.0
            
            # 2. 日期格式：YYYY-MM-DD 或 MM-DD
            m = re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})', time_value)
            if m:
                dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                              tzinfo=timezone.utc)
                seconds_elapsed = datetime.now(timezone.utc).timestamp() - dt.timestamp()
                return max(seconds_elapsed / 3600, 1)
            
            m = re.match(r'(\d{1,2})-(\d{1,2})', time_value)
            if m:
                now = datetime.now(timezone.utc)
                dt = datetime(now.year, int(m.group(1)), int(m.group(2)),
                              tzinfo=timezone.utc)
                # 如果算出来是未来时间，说明是去年的
                if dt > now:
                    dt = dt.replace(year=now.year - 1)
                seconds_elapsed = now.timestamp() - dt.timestamp()
                return max(seconds_elapsed / 3600, 1)
            
            # 3. 尝试作为数字时间戳
            try:
                timestamp_float = float(time_value)
            except ValueError:
                # 4. ISO 格式
                try:
                    dt = datetime.fromisoformat(time_value.replace('Z', '+00:00'))
                    timestamp_float = dt.timestamp()
                except ValueError:
                    return None
        else:
            timestamp_float = float(time_value)

        # 判断毫秒 vs 秒级时间戳
        if timestamp_float > 1000000000000:
            timestamp_float /= 1000

        current_timestamp = datetime.now(timezone.utc).timestamp()
        seconds_elapsed = current_timestamp - timestamp_float
        hours = max(seconds_elapsed / 3600, 1)
        return round(hours, 1)
    except Exception:
        return None


def calc_viral_score(likes, collects, comments, hours):
    engagement = likes + collects * 1.5 + comments * 2
    hours = max(hours, 1)
    density = engagement / hours
    fan_factor = math.log10(max(100, 100))
    score = density / fan_factor * 10
    return round(score, 1)


def get_level(score):
    if score >= 50:
        return "🔥🔥🔥 超级爆款"
    elif score >= 20:
        return "🔥🔥 准爆款"
    elif score >= 8:
        return "🔥 表现优秀"
    else:
        return "📊 正常水平"


def analyze_engagement(likes, collects, comments, shares):
    """基于互动数据的纯逻辑分析（不依赖AI）"""
    total = likes + collects + comments + shares
    if total == 0:
        return []

    insights = []

    # 收藏率分析
    if likes > 0:
        save_rate = collects / likes
        if save_rate > 1.2:
            insights.append(("💎 超高收藏率", f"收藏/点赞 = {save_rate:.1f}，远超均值0.3-0.5。说明内容有极强的「实用价值」或「稍后再看」属性，用户认为值得反复查阅。"))
        elif save_rate > 0.6:
            insights.append(("📌 高收藏率", f"收藏/点赞 = {save_rate:.1f}，高于均值。内容有较强的工具/参考价值。"))
        elif save_rate < 0.15:
            insights.append(("⚡ 情绪驱动型", f"收藏/点赞 = {save_rate:.1f}，用户点赞但不收藏，说明内容靠情绪共鸣/娱乐性而非实用价值驱动。"))

    # 评论互动分析
    if likes > 0:
        comment_rate = comments / likes
        if comment_rate > 0.15:
            insights.append(("💬 强讨论性", f"评论/点赞 = {comment_rate:.2f}，话题引发了大量讨论。可能涉及争议点、求推荐、或强共鸣。"))
        elif comment_rate < 0.03:
            insights.append(("📖 纯阅读型", f"评论/点赞 = {comment_rate:.2f}，用户看完即走。适合干货类内容但缺乏互动钩子。"))

    # 分享率分析
    if shares > 0 and likes > 0:
        share_rate = shares / likes
        if share_rate > 0.3:
            insights.append(("🔗 高传播性", f"分享/点赞 = {share_rate:.2f}，用户主动帮你扩散。内容具有社交货币属性（有趣/有用/想安利）。"))

    # 互动总量判断
    if total > 2000:
        insights.append(("📈 流量池突破", f"总互动 {total:,}，已突破小红书多级流量池，获得了持续的推荐曝光。"))

    return insights


def get_content_type_analysis(likes, collects, comments, note_type, image_count):
    """基于数据判断内容类型特征"""
    traits = []

    if collects > likes:
        traits.append("📚 强工具属性（收藏>点赞=用户当参考资料用）")
    if comments > likes * 0.1:
        traits.append("🎯 强话题属性（高评论率=引发讨论/共鸣）")
    if note_type == "video":
        traits.append("🎬 视频笔记（视频完播率是推荐权重关键因子）")
    if image_count >= 6:
        traits.append(f"🖼️ 多图笔记（{image_count}张图，信息密度高，用户停留时间长）")
    elif 0 < image_count <= 2 and note_type != "video":
        traits.append(f"📝 轻图文（{image_count}张图，靠标题和文字取胜）")

    return traits


def parse_input(text: str) -> dict:
    """尝试解析用户粘贴的内容"""
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict) and ("title" in data or "content" in data):
            return data
    except json.JSONDecodeError:
        pass
    return None


def parse_ai_sections(markdown_text: str) -> dict:
    """将 AI 返回的 Markdown 按 ## 分块，映射到各维度"""
    import re
    sections = {}
    parts = re.split(r'\n(?=## )', markdown_text.strip())

    for part in parts:
        part = part.strip()
        if not part:
            continue
        lines = part.split('\n', 1)
        title = lines[0].lstrip('#').strip()
        content = lines[1].strip() if len(lines) > 1 else ""

        # 映射到标签名
        if "选题" in title:
            sections["📋 选题评分"] = content
        elif "标题" in title:
            sections["📝 标题拆解"] = content
        elif "封面" in title or "首图" in title:
            sections["🖼️ 封面策略"] = content
        elif "内容" in title or "结构" in title:
            sections["📚 内容结构"] = content
        elif "互动" in title:
            sections["💬 互动设计"] = content
        elif "算法" in title:
            sections["🔍 算法适配"] = content
        elif "行动" in title or "建议" in title:
            sections["💡 行动建议"] = content

    return sections


def extract_summary_from_sections(sections: dict) -> tuple:
    """从各维度中提取摘要信息：(评分, 评分理由, top3建议列表)"""
    import re

    # 提取选题评分
    score_text = sections.get("📋 选题评分", "")
    score_match = re.search(r'(\d+(?:\.\d+)?)\s*/\s*10', score_text)
    ai_score = score_match.group(1) if score_match else "N/A"

    # 提取评分理由（第一段非空文本）
    reason = ""
    for line in score_text.split('\n'):
        line = line.strip()
        if line and not line.startswith('#') and not line.startswith('|') and not line.startswith('---'):
            reason = line[:100]  # 截取前100字
            break

    # 提取行动建议（前3条）
    advice_text = sections.get("💡 行动建议", "")
    recommendations = []
    for line in advice_text.split('\n'):
        line = line.strip()
        if re.match(r'^\d+[\.\、]', line):
            # 去掉序号
            rec = re.sub(r'^\d+[\.\、]\s*', '', line)
            # 去掉 markdown 加粗
            rec = re.sub(r'\*\*(.*?)\*\*', r'\1', rec)
            if rec:
                recommendations.append(rec[:80])  # 截取前80字
            if len(recommendations) >= 3:
                break

    return ai_score, reason, recommendations


def convert_md_to_html(md_text: str) -> str:
    """简单的 Markdown 到 HTML 转换"""
    import re
    html = md_text
    # 标题
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    # 加粗
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    # 列表
    html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    # 引用
    html = re.sub(r'^> (.+)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)
    # 换行
    html = html.replace('\n\n', '</p><p>').replace('\n', '<br>')
    html = f'<p>{html}</p>'
    return html


def generate_html_report(title, author, likes, collects, comments, shares,
                         score, level, hours, engagement_insights,
                         content_traits, ai_result, category) -> str:
    """生成美观的 HTML 分析报告"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>爆款拆解报告 - {title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.8; color: #333; background: #f8f9fa;
            padding: 40px 20px;
        }}
        .container {{ max-width: 800px; margin: 0 auto; background: #fff;
                     border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08);
                     padding: 48px; }}
        .header {{ text-align: center; margin-bottom: 32px; padding-bottom: 24px;
                  border-bottom: 2px solid #ff4757; }}
        .header h1 {{ font-size: 24px; color: #ff4757; margin-bottom: 8px; }}
        .header .subtitle {{ color: #666; font-size: 14px; }}
        .metrics {{ display: flex; justify-content: space-around; margin: 24px 0;
                   padding: 20px; background: #fff5f5; border-radius: 8px; }}
        .metric {{ text-align: center; }}
        .metric .value {{ font-size: 24px; font-weight: bold; color: #ff4757; }}
        .metric .label {{ font-size: 12px; color: #666; margin-top: 4px; }}
        .section {{ margin: 28px 0; }}
        .section h2 {{ font-size: 18px; color: #333; margin-bottom: 12px;
                      padding-left: 12px; border-left: 3px solid #ff4757; }}
        .section h3 {{ font-size: 15px; color: #555; margin: 16px 0 8px; }}
        .insight {{ background: #f8f9fa; padding: 12px 16px; border-radius: 6px;
                   margin: 8px 0; border-left: 3px solid #ffa502; }}
        .ai-content {{ white-space: pre-wrap; }}
        .ai-content h2 {{ margin-top: 24px; }}
        .footer {{ text-align: center; margin-top: 40px; padding-top: 20px;
                  border-top: 1px solid #eee; color: #999; font-size: 12px; }}
        strong {{ color: #333; }}
        blockquote {{ border-left: 3px solid #ddd; padding-left: 12px; color: #666; margin: 8px 0; }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>🔥 爆款拆解报告</h1>
        <div class="subtitle">{title} | 作者：{author or '未知'}</div>
    </div>

    <div class="metrics">
        <div class="metric"><div class="value">{score}</div><div class="label">爆款指数</div></div>
        <div class="metric"><div class="value">{likes:,}</div><div class="label">点赞</div></div>
        <div class="metric"><div class="value">{collects:,}</div><div class="label">收藏</div></div>
        <div class="metric"><div class="value">{comments:,}</div><div class="label">评论</div></div>
        <div class="metric"><div class="value">{shares:,}</div><div class="label">分享</div></div>
    </div>

    <div class="section">
        <h2>📊 数据洞察</h2>
        {''.join(f'<div class="insight"><strong>{t}</strong><br>{d}</div>' for t, d in engagement_insights) if engagement_insights else '<p>互动数据不足</p>'}
        {('<h3>内容特征</h3><ul>' + ''.join(f'<li>{t}</li>' for t in content_traits) + '</ul>') if content_traits else ''}
    </div>

    <div class="section">
        <h2>🤖 AI 深度拆解</h2>
        <div class="ai-content">{convert_md_to_html(ai_result)}</div>
    </div>

    <div class="footer">
        由「小红书爆款拆解器」生成 | {category or '通用'}品类
    </div>
</div>
</body>
</html>"""
    return html


# ============ 主界面 ============
st.markdown("---")

# ---- 使用说明 ----
with st.expander("📖 首次使用？1分钟设置（只需一次）", expanded=False):
    st.markdown("""
**第一步：保存「提取书签」到收藏栏**

1. 显示书签栏：`Ctrl+Shift+B`（Mac 用 `Cmd+Shift+B`）
2. 右键书签栏 → 点「添加网页」
3. 名称填：`📋 提取笔记`
4. 网址栏粘贴下面这段代码：
""")
    st.code(BOOKMARKLET, language=None)
    st.markdown("""
**第二步：使用方式**

1. 在浏览器中打开一篇小红书笔记
2. 点击收藏栏里的「📋 提取笔记」书签
3. 看到"已复制"提示后，回到本页面
4. 在下方输入框里 `Ctrl+V` 粘贴，点击拆解

就这么简单！以后每篇笔记只需要"点书签 → 粘贴"两步。
""")

# ---- 输入区 ----
st.markdown("#### 粘贴笔记数据")
json_input = st.text_area(
    "点击书签提取后，在这里 Ctrl+V / Cmd+V 粘贴",
    height=120,
    placeholder='{"title": "...", "content": "...", "likes": 329, ...}',
    label_visibility="collapsed",
)
btn = st.button("🚀 开始拆解", use_container_width=True, type="primary")

# ============ 分析流程 ============
if btn:
    if not json_input.strip():
        st.error('请先粘贴笔记数据（点击上方「首次使用」查看教程）')
        st.stop()
    if not api_key:
        st.error("请在左侧填写 DeepSeek API Key")
        st.stop()

    data = parse_input(json_input)
    if not data:
        st.error("无法识别粘贴的内容，请确认是通过书签提取的数据")
        st.stop()

    # ---- 自动计算发布时间 ----
    hours = extract_hours_from_timestamp(data.get("time"))
    if hours is None:
        hours = 48
        st.caption("⏰ 未检测到发布时间，使用默认值48小时计算爆款指数")
    else:
        if hours < 24:
            st.caption(f"⏰ 发布于约 {hours:.0f} 小时前")
        else:
            days = hours / 24
            st.caption(f"⏰ 发布于约 {days:.1f} 天前")

    # ---- 基础信息 ----
    st.markdown("---")
    title = data.get("title", "无标题")
    author = data.get("author", "")
    st.markdown(f"### 📝 {title}")
    if author:
        st.caption(f"作者：{author}")

    likes = int(data.get("likes", 0))
    collects = int(data.get("collects", 0))
    comments = int(data.get("comments", 0))
    shares = int(data.get("shares", 0))
    note_type = data.get("noteType", "normal")
    images = data.get("images", [])
    image_count = len(images) if images else int(data.get("imageCount", 0))
    video = data.get("video", None)

    # ---- 爆款指数 ----
    if likes + collects + comments > 0:
        score = calc_viral_score(likes, collects, comments, hours)
        level = get_level(score)

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("爆款指数", score)
        col2.metric("点赞", f"{likes:,}")
        col3.metric("收藏", f"{collects:,}")
        col4.metric("评论", f"{comments:,}")
        col5.metric("分享", f"{shares:,}")
        st.caption(level)
    else:
        score = 0
        level = "数据不足"

    # ---- 媒体展示 ----
    img_urls = [img.get("url", "") for img in images if img.get("url")] if images else []
    has_video = video and video.get("url")

    if img_urls or has_video:
        st.markdown("---")
        st.markdown("### 🖼️ 媒体内容")
        st.caption("⚠️ 媒体内容来自小红书CDN，链接有时效性，仅临时有效")

        # 图片画廊
        if img_urls:
            st.markdown("**图片**")
            # 每行3张图，使用 HTML img 标签绕过防盗链
            for row_start in range(0, len(img_urls), 3):
                row_imgs = img_urls[row_start:row_start + 3]
                cols = st.columns(3)
                for idx, url in enumerate(row_imgs):
                    with cols[idx]:
                        st.markdown(
                            f'<img src="{url}" referrerpolicy="no-referrer" '
                            f'style="width:100%;border-radius:8px;" />',
                            unsafe_allow_html=True
                        )

        # 视频播放
        if has_video:
            st.markdown("**视频**")
            duration = video.get("duration", 0)
            height = video.get("height", 0)
            info_parts = []
            if duration:
                minutes, seconds = divmod(int(duration), 60)
                info_parts.append(f"时长 {minutes}:{seconds:02d}")
            if height:
                info_parts.append(f"分辨率 {height}p")
            if info_parts:
                st.caption(" | ".join(info_parts))
            try:
                st.video(video["url"])
            except Exception:
                st.info("视频加载失败（链接可能已过期）")

    # ---- 数据洞察（纯算法，不依赖 AI） ----
    st.markdown("---")
    st.markdown("### 📊 数据洞察")

    engagement_insights = analyze_engagement(likes, collects, comments, shares)
    content_traits = get_content_type_analysis(likes, collects, comments, note_type, image_count)

    if engagement_insights:
        for emoji_title, detail in engagement_insights:
            st.markdown(f"**{emoji_title}**")
            st.markdown(f"> {detail}")
            st.markdown("")
    else:
        st.info("互动数据不足，暂无法生成数据洞察")

    if content_traits:
        st.markdown("**内容特征**")
        for trait in content_traits:
            st.markdown(f"- {trait}")

    # ---- AI 拆解（三层增强） ----
    st.markdown("---")
    st.markdown("### 🤖 AI 深度拆解（增强版）")

    tags = data.get("tags", [])
    tag_str = ", ".join(tags) if tags else "无"
    data_traits_str = "; ".join([t for _, t in engagement_insights] + content_traits) if (engagement_insights or content_traits) else "无明显特征"

    # 构建媒体信息描述
    media_parts = []
    if images:
        orientations = []
        for img in images:
            w = img.get("w", 0)
            h = img.get("h", 0)
            if w and h:
                if h > w:
                    orientations.append("竖版")
                elif w > h:
                    orientations.append("横版")
                else:
                    orientations.append("方图")
        if orientations:
            orient_count = Counter(orientations)
            orient_desc = "、".join([f"{v}张{k}" for k, v in orient_count.items()])
            media_parts.append(f"{image_count}张图片（{orient_desc}）")
        else:
            media_parts.append(f"{image_count}张图片")
    if video and video.get("url"):
        duration = video.get("duration", 0)
        if duration:
            minutes, seconds = divmod(int(duration), 60)
            media_parts.append(f"视频时长 {minutes}:{seconds:02d}")
        else:
            media_parts.append("含视频")
    media_info_str = "；".join(media_parts) if media_parts else "无媒体信息"

    # 使用三层增强 prompt
    cat = category if category != "通用" else ""
    messages = get_full_prompt(
        title=title,
        content=data.get("content", ""),
        tags=tag_str,
        likes=likes, collects=collects, comments=comments, shares=shares,
        note_type="视频" if note_type == "video" else "图文",
        image_count=image_count,
        score=score, level=level,
        data_traits=data_traits_str,
        media_info=media_info_str,
        category=cat,
    )

    with st.spinner("AI 深度分析中（三层增强），约 20 秒..."):
        try:
            base = f"{api_base}/v1" if not api_base.endswith("/v1") else api_base
            client = OpenAI(api_key=api_key, base_url=base)
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=3000,
            )
            ai_result = resp.choices[0].message.content

            # 解析 AI 结果
            sections = parse_ai_sections(ai_result)

            if not sections:
                # fallback：解析失败时直接展示原文
                st.markdown(ai_result)
            else:
                # === 快速摘要卡 ===
                ai_score, reason, recommendations = extract_summary_from_sections(sections)

                # 摘要卡容器
                st.markdown("#### 🎯 快速摘要")
                col1, col2 = st.columns([1, 2])

                with col1:
                    st.metric("AI 选题评分", f"{ai_score}/10")
                    if reason:
                        st.caption(reason)

                with col2:
                    if recommendations:
                        st.markdown("**💡 Top 行动建议：**")
                        for i, rec in enumerate(recommendations, 1):
                            st.markdown(f"{i}. {rec}")
                    else:
                        st.caption("暂未提取到行动建议")

                # === 标签页详情 ===
                st.markdown("---")
                st.markdown("#### 📖 详细分析")

                # 按固定顺序排列标签
                tab_order = ["📋 选题评分", "📝 标题拆解", "💬 互动设计",
                             "📚 内容结构", "🔍 算法适配", "🖼️ 封面策略", "💡 行动建议"]
                available_tabs = [t for t in tab_order if t in sections]

                if available_tabs:
                    tabs = st.tabs(available_tabs)
                    for tab, tab_name in zip(tabs, available_tabs):
                        with tab:
                            st.markdown(sections[tab_name])
                else:
                    # 标签也失败的 fallback
                    st.markdown(ai_result)

            # ---- 导出 HTML 报告 ----
            st.markdown("---")
            html_report = generate_html_report(
                title=title, author=author,
                likes=likes, collects=collects, comments=comments, shares=shares,
                score=score, level=level, hours=hours,
                engagement_insights=engagement_insights,
                content_traits=content_traits,
                ai_result=ai_result,
                category=category,
            )
            st.download_button(
                label="📥 导出分析报告（HTML）",
                data=html_report,
                file_name=f"爆款拆解_{title[:20]}.html",
                mime="text/html",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"分析失败：{e}")

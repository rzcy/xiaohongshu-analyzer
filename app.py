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

# TODO: 登录注册功能暂时关闭，后续恢复
# try:
#     from auth import render_auth_ui, get_current_user, check_quota, consume_quota
#     AUTH_ENABLED = True
# except Exception:
#     AUTH_ENABLED = False
AUTH_ENABLED = False

# ============ 页面配置 ============
st.set_page_config(page_title="小红书爆款拆解器", page_icon="🔥", layout="centered")

# 全局禁止发送 Referer（解决小红书 CDN 防盗链，兼容手机浏览器）
st.markdown(
    '<meta name="referrer" content="no-referrer">',
    unsafe_allow_html=True
)

st.title("🔥 小红书爆款拆解器")
st.caption("一键提取 + 数据洞察 + AI 深度拆解，帮你看懂爆款为什么火")

# ============ 侧边栏 ============
with st.sidebar:
    # TODO: 登录注册功能暂时关闭，后续恢复
    # if AUTH_ENABLED:
    #     st.header("👤 账号")
    #     user = render_auth_ui()
    # else:
    #     user = None
    user = None

    # 设置区
    st.header("⚙️ 设置")
    default_key = ""
    try:
        default_key = st.secrets.get("DEEPSEEK_API_KEY", "")
    except Exception:
        pass
    # API Key 优先从 secrets 读取，无需用户手动输入
    if default_key:
        api_key = default_key
    else:
        api_key = st.text_input("DeepSeek API Key", type="password",
                                help="[点此免费注册获取](https://platform.deepseek.com)")
    model = "deepseek-chat"
    category = st.selectbox(
        "📂 笔记品类（可选，提升分析精准度）",
        ["通用", "美妆", "穿搭", "美食", "家居", "母婴", "职场", "旅行"]
    )
    # 分析维度定制
    all_dimensions = ["选题评分", "标题拆解", "封面/首图策略", "内容结构拆解", "互动设计分析", "平台算法适配度", "行动建议"]
    with st.expander("📐 分析维度定制", expanded=False):
        selected_dims = st.multiselect(
            "去掉不需要的维度，AI 只输出选中部分",
            all_dimensions,
            default=all_dimensions,
        )
    api_base = "https://api.deepseek.com"


# ============ 书签脚本（增强版：提取更多字段） ============
BOOKMARKLET = """javascript:void(function(){try{var s=window.__INITIAL_STATE__;if(!s||!s.note){alert('请在小红书笔记页面使用');return}function pn(v){if(!v)return 0;var str=String(v).trim();if(str.indexOf('万')>-1){return Math.round(parseFloat(str)*10000)}return parseInt(str)||0}var cid=s.note.currentNoteId;var noteId=(cid&&cid._value)?cid._value:(typeof cid==='string'?cid:'');var m=s.note.noteDetailMap;var keys=Object.keys(m).filter(function(k){return k&&k!=='undefined'&&k.length>5});var key=noteId&&m[noteId]?noteId:keys[0];if(!key){alert('未找到笔记数据，请刷新页面重试');return}var entry=m[key];var raw=entry.__v_raw||entry;var d=raw.note.__v_raw||raw.note;if(!d||!d.title){alert('笔记数据为空，请刷新重试');return}var interact=d.interactInfo?(d.interactInfo.__v_raw||d.interactInfo):{};var user=d.user?(d.user.__v_raw||d.user):{};var tags=d.tagList?(d.tagList.__v_raw||d.tagList):[];var imgs=d.imageList?(d.imageList.__v_raw||d.imageList):[];var imgUrls=Array.from(imgs||[]).map(function(img){var i=img.__v_raw||img;return{url:i.urlDefault||i.urlPre||'',w:i.width||0,h:i.height||0}}).filter(function(x){return x.url});var vid=d.video?(d.video.__v_raw||d.video):null;var videoInfo=null;if(vid){var media=vid.media?(vid.media.__v_raw||vid.media):null;if(media){var vs=media.stream?(media.stream.__v_raw||media.stream):{};var h264=vs.h264||[];var best=h264[0]||{};var vv=media.video?(media.video.__v_raw||media.video):{};videoInfo={url:best.masterUrl||'',duration:vv.duration||0,height:best.height||0}}else{videoInfo={url:vid.url||vid.urlDefault||'',duration:vid.duration||0,height:0}}}var r={title:d.title||'',content:d.desc||'',tags:Array.from(tags||[]).map(function(t){return t.name||t}),likes:pn(interact.likedCount),collects:pn(interact.collectedCount),comments:pn(interact.commentCount),shares:pn(interact.shareCount),author:user.nickname||'',noteType:d.type||'normal',images:imgUrls,video:videoInfo,time:d.time||''};var ta=document.createElement('textarea');ta.value=JSON.stringify(r);document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);alert('✅ 已复制！回到拆解器页面粘贴即可')}catch(e){alert('提取失败：'+e.message+'\\n请确认当前在笔记详情页')}})()"""


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


def parse_executive_summary(markdown_text: str) -> dict:
    """从AI输出中提取前置摘要信息（爆款指数、一句话总结、Top3行动）"""
    import re
    result = {
        "score": None,        # 如 "4223"
        "score_max": 5000,
        "score_detail": "",   # 括号内的计分说明
        "summary": "",        # 一句话总结
        "top3_actions": [],   # 3条行动建议列表
    }

    # 提取爆款指数部分
    score_match = re.search(r'##\s*爆款指数\s*\n(.+?)(?=\n##|\Z)', markdown_text, re.DOTALL)
    if score_match:
        score_text = score_match.group(1).strip()
        # 提取数字分数
        num_match = re.search(r'(\d+)\s*/\s*(\d+)', score_text)
        if num_match:
            result["score"] = int(num_match.group(1))
            result["score_max"] = int(num_match.group(2))
        # 提取括号内说明
        detail_match = re.search(r'[（(](.+?)[）)]', score_text)
        if detail_match:
            result["score_detail"] = detail_match.group(1)

    # 提取一句话总结
    summary_match = re.search(r'##\s*一句话总结\s*\n(.+?)(?=\n##|\Z)', markdown_text, re.DOTALL)
    if summary_match:
        result["summary"] = summary_match.group(1).strip()

    # 提取3件事
    actions_match = re.search(r'##\s*你现在最该做的3件事\s*\n(.+?)(?=\n##|\Z)', markdown_text, re.DOTALL)
    if actions_match:
        actions_text = actions_match.group(1).strip()
        # 提取编号列表项
        actions = re.findall(r'\d+\.\s*(.+)', actions_text)
        result["top3_actions"] = actions[:3]

    return result


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

        # 从标题中提取评分等关键信息（如 "1. 选题评分：9/10" → 提取 "9/10"）
        score_in_title = ""
        score_m = re.search(r'(\d+(?:\.\d+)?)\s*/\s*10', title)
        if score_m:
            score_in_title = f"**综合评分：{score_m.group(0)}**\n\n"

        # 内容 = 标题中的评分信息（如有）+ 正文（不含重复的序号标题）
        display_content = score_in_title + content if content else score_in_title or title

        # 映射到标签名
        if "选题" in title:
            sections["📋 选题评分"] = display_content
        elif "标题" in title:
            sections["📝 标题拆解"] = display_content
        elif "封面" in title or "首图" in title:
            sections["🖼️ 封面策略"] = display_content
        elif "内容" in title or "结构" in title:
            sections["📚 内容结构"] = display_content
        elif "互动" in title:
            sections["💬 互动设计"] = display_content
        elif "算法" in title:
            sections["🔍 算法适配"] = display_content
        elif "行动" in title or "建议" in title:
            sections["💡 行动建议"] = display_content

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
                         content_traits, ai_result, category,
                         exec_summary=None) -> str:
    """生成三层金字塔结构的 HTML 分析报告

    三层结构：
    1. 顶部醒目区域：爆款指数（大字+渐变进度条）+ 一句话总结
    2. 行动建议区域：3条最该做的事
    3. 完整分析区域：7维度分析展开
    """
    # 如果未传入 exec_summary，自行从 ai_result 中解析
    if exec_summary is None:
        try:
            exec_summary = parse_executive_summary(ai_result)
        except Exception:
            exec_summary = {"score": None, "score_max": 5000, "score_detail": "",
                            "summary": "", "top3_actions": []}

    # 解析7维度分析
    sections = parse_ai_sections(ai_result)

    # 爆款指数数值
    es_score = exec_summary.get("score")
    es_max = exec_summary.get("score_max", 5000)
    es_detail = exec_summary.get("score_detail", "")
    es_summary = exec_summary.get("summary", "")
    es_actions = exec_summary.get("top3_actions", [])
    score_pct = (es_score / es_max * 100) if es_score and es_max else 0

    # 进度条颜色
    if score_pct >= 80:
        bar_gradient = "linear-gradient(90deg, #ff416c, #ff4b2b)"
        score_color = "#ff4b2b"
    elif score_pct >= 60:
        bar_gradient = "linear-gradient(90deg, #f7971e, #ffd200)"
        score_color = "#f7971e"
    else:
        bar_gradient = "linear-gradient(90deg, #667eea, #764ba2)"
        score_color = "#667eea"

    # 构建爆款指数 Hero 区域
    hero_score_html = ""
    if es_score is not None:
        hero_score_html = f"""
        <div class="score-badge" style="color:{score_color}">{es_score} <span class="score-max">/ {es_max}</span></div>
        <div class="score-bar-track">
            <div class="score-bar-fill" style="width:{min(score_pct,100):.1f}%;background:{bar_gradient}"></div>
        </div>
        """
        if es_detail:
            hero_score_html += f'<p class="score-detail">{es_detail}</p>'

    hero_summary_html = ""
    if es_summary:
        hero_summary_html = f'<blockquote class="summary">{es_summary}</blockquote>'

    # 构建行动建议区域
    actions_html = ""
    if es_actions:
        action_items = ""
        for i, action in enumerate(es_actions, 1):
            # 分离 "操作描述 → 预期效果" 格式
            if "→" in action:
                parts = action.split("→", 1)
                action_items += f'<li><span class="action-text">{parts[0].strip()}</span><span class="action-arrow">→</span><span class="action-effect">{parts[1].strip()}</span></li>'
            else:
                action_items += f'<li><span class="action-text">{action}</span></li>'
        actions_html = f"""
    <div class="actions-section">
        <h2>🎯 你现在最该做的3件事</h2>
        <ol class="action-list">{action_items}</ol>
    </div>"""

    # 构建数据洞察
    insights_html = ""
    if engagement_insights:
        insights_html = ''.join(
            f'<div class="insight-card"><strong>{t}</strong><br>{d}</div>'
            for t, d in engagement_insights
        )
    if content_traits:
        insights_html += '<div class="traits"><h3>内容特征</h3><ul>' + ''.join(
            f'<li>{t}</li>' for t in content_traits
        ) + '</ul></div>'

    # 构建7维度分析
    tab_order = ["📋 选题评分", "📝 标题拆解", "🖼️ 封面策略",
                 "📚 内容结构", "💬 互动设计", "🔍 算法适配", "💡 行动建议"]
    analysis_cards = ""
    for tab_name in tab_order:
        if tab_name in sections:
            content_html = convert_md_to_html(sections[tab_name])
            analysis_cards += f"""
        <div class="analysis-card">
            <h3>{tab_name}</h3>
            <div class="card-content">{content_html}</div>
        </div>"""

    if not analysis_cards:
        # fallback: 直接渲染原始AI输出
        analysis_cards = f'<div class="analysis-card"><div class="card-content">{convert_md_to_html(ai_result)}</div></div>'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>爆款拆解报告 - {title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
                         'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
            line-height: 1.8; color: #2d3436; background: #f0f2f5;
            padding: 40px 16px;
        }}
        .container {{ max-width: 840px; margin: 0 auto; }}

        /* === Hero Section: 爆款指数 === */
        .hero-section {{
            background: linear-gradient(135deg, #fff 0%, #fdf2f8 100%);
            border-radius: 16px;
            padding: 40px 36px 32px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.06);
            text-align: center;
            margin-bottom: 20px;
        }}
        .hero-section .report-title {{
            font-size: 22px; font-weight: 700; color: #1a1a2e;
            margin-bottom: 4px;
        }}
        .hero-section .report-subtitle {{
            font-size: 13px; color: #999; margin-bottom: 24px;
        }}
        .score-badge {{
            font-size: 56px; font-weight: 800; letter-spacing: -2px;
            margin-bottom: 8px;
        }}
        .score-max {{ font-size: 24px; font-weight: 400; color: #aaa; }}
        .score-bar-track {{
            width: 100%; max-width: 480px; height: 14px;
            background: #e9ecef; border-radius: 7px;
            margin: 12px auto; overflow: hidden;
        }}
        .score-bar-fill {{
            height: 100%; border-radius: 7px;
            transition: width 0.6s ease;
        }}
        .score-detail {{
            font-size: 13px; color: #888; margin-top: 8px;
        }}
        .summary {{
            margin: 20px auto 0; max-width: 600px;
            font-size: 16px; font-style: italic; color: #555;
            border-left: 4px solid #ff6b81; padding: 12px 20px;
            background: rgba(255,107,129,0.06); border-radius: 0 8px 8px 0;
            text-align: left;
        }}

        /* === 数据指标条 === */
        .metrics-bar {{
            display: flex; justify-content: space-around; flex-wrap: wrap;
            background: #fff; border-radius: 12px;
            padding: 20px 12px; margin-bottom: 20px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.04);
        }}
        .metric {{ text-align: center; min-width: 80px; padding: 4px 8px; }}
        .metric .value {{ font-size: 22px; font-weight: 700; color: #ff4757; }}
        .metric .label {{ font-size: 12px; color: #999; margin-top: 2px; }}

        /* === Actions Section === */
        .actions-section {{
            background: #fff; border-radius: 12px;
            padding: 28px 32px; margin-bottom: 20px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.04);
        }}
        .actions-section h2 {{
            font-size: 18px; color: #1a1a2e; margin-bottom: 16px;
        }}
        .action-list {{
            list-style: none; counter-reset: action-counter;
            padding: 0;
        }}
        .action-list li {{
            counter-increment: action-counter;
            padding: 14px 16px 14px 52px;
            margin: 10px 0; border-radius: 10px;
            background: linear-gradient(135deg, #f8f9ff 0%, #f0f4ff 100%);
            position: relative; font-size: 15px; line-height: 1.6;
        }}
        .action-list li::before {{
            content: counter(action-counter);
            position: absolute; left: 14px; top: 50%; transform: translateY(-50%);
            width: 28px; height: 28px; border-radius: 50%;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: #fff; font-weight: 700; font-size: 14px;
            display: flex; align-items: center; justify-content: center;
        }}
        .action-arrow {{
            display: inline-block; margin: 0 8px;
            color: #764ba2; font-weight: 700;
        }}
        .action-effect {{ color: #667eea; font-weight: 600; }}

        /* === Data Insights Section === */
        .insights-section {{
            background: #fff; border-radius: 12px;
            padding: 28px 32px; margin-bottom: 20px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.04);
        }}
        .insights-section h2 {{
            font-size: 18px; color: #1a1a2e; margin-bottom: 16px;
        }}
        .insight-card {{
            background: #fafbfc; padding: 14px 18px; border-radius: 8px;
            margin: 10px 0; border-left: 4px solid #ffa502;
            font-size: 14px;
        }}
        .traits {{ margin-top: 16px; }}
        .traits h3 {{ font-size: 15px; color: #555; margin-bottom: 8px; }}
        .traits ul {{ padding-left: 20px; }}
        .traits li {{ margin: 4px 0; font-size: 14px; }}

        /* === Analysis Section === */
        .analysis-section {{
            background: #fff; border-radius: 12px;
            padding: 28px 32px; margin-bottom: 20px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.04);
        }}
        .analysis-section > h2 {{
            font-size: 18px; color: #1a1a2e; margin-bottom: 20px;
        }}
        .analysis-card {{
            border: 1px solid #eef0f2; border-radius: 10px;
            padding: 20px 24px; margin: 16px 0;
            background: #fafbfc;
        }}
        .analysis-card h3 {{
            font-size: 16px; font-weight: 700; color: #333;
            margin-bottom: 12px; padding-bottom: 8px;
            border-bottom: 2px solid #ff4757;
        }}
        .card-content {{ font-size: 14px; line-height: 1.9; }}
        .card-content h2 {{ font-size: 15px; color: #444; margin: 16px 0 8px; }}
        .card-content h3 {{ font-size: 14px; color: #555; margin: 12px 0 6px;
                           border-bottom: none; padding-bottom: 0; }}
        .card-content strong {{ color: #1a1a2e; }}
        .card-content li {{ margin: 4px 0; }}
        .card-content blockquote {{
            border-left: 3px solid #ddd; padding-left: 12px;
            color: #666; margin: 8px 0;
        }}

        /* === Footer === */
        .footer {{
            text-align: center; padding: 24px 0 8px;
            color: #bbb; font-size: 12px;
        }}

        /* === 响应式 === */
        @media (max-width: 600px) {{
            body {{ padding: 16px 8px; }}
            .hero-section {{ padding: 28px 18px 24px; }}
            .score-badge {{ font-size: 40px; }}
            .score-max {{ font-size: 18px; }}
            .actions-section, .insights-section, .analysis-section {{
                padding: 20px 16px;
            }}
            .action-list li {{ padding: 12px 12px 12px 46px; font-size: 14px; }}
            .metrics-bar {{ padding: 14px 8px; }}
            .metric .value {{ font-size: 18px; }}
            .analysis-card {{ padding: 16px; }}
        }}

        /* === 打印友好 === */
        @media print {{
            body {{ background: #fff; padding: 0; }}
            .container {{ box-shadow: none; }}
            .hero-section, .actions-section, .insights-section, .analysis-section {{
                box-shadow: none; break-inside: avoid;
            }}
            .analysis-card {{ break-inside: avoid; }}
            .action-list li {{ background: #f5f5f5; }}
        }}
    </style>
</head>
<body>
<div class="container">

    <!-- 第一层：爆款指数 + 一句话总结 -->
    <div class="hero-section">
        <div class="report-title">🔥 爆款拆解报告</div>
        <div class="report-subtitle">{title} | 作者：{author or '未知'}</div>
        {hero_score_html}
        {hero_summary_html}
    </div>

    <!-- 数据指标 -->
    <div class="metrics-bar">
        <div class="metric"><div class="value">{score}</div><div class="label">爆款指数</div></div>
        <div class="metric"><div class="value">{likes:,}</div><div class="label">点赞</div></div>
        <div class="metric"><div class="value">{collects:,}</div><div class="label">收藏</div></div>
        <div class="metric"><div class="value">{comments:,}</div><div class="label">评论</div></div>
        <div class="metric"><div class="value">{shares:,}</div><div class="label">分享</div></div>
    </div>

    <!-- 第二层：行动建议 -->
    {actions_html}

    <!-- 数据洞察 -->
    {('<div class="insights-section"><h2>📊 数据洞察</h2>' + insights_html + '</div>') if insights_html else ''}

    <!-- 第三层：完整7维度分析 -->
    <div class="analysis-section">
        <h2>📊 完整分析报告</h2>
        {analysis_cards}
    </div>

    <div class="footer">
        由「小红书爆款拆解器」生成 | {category or '通用'}品类 | {datetime.now().strftime('%Y-%m-%d %H:%M')}
    </div>
</div>
</body>
</html>"""
    return html


# ============ 主界面 ============

# ============ 功能介绍 ============
st.markdown("---")
col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("##### 📊 数据洞察")
    st.caption("自动计算爆款指数、互动率分析、内容特征识别")
with col2:
    st.markdown("##### 🤖 AI 深度拆解")
    st.caption("7维度专业分析：选题/标题/封面/内容/互动/算法/建议")
with col3:
    st.markdown("##### 💡 可执行建议")
    st.caption("不说空话，每条建议带模板、带数字、直接能用")
st.markdown("---")

# ============ 示例分析结果 ============
with st.expander("👀 查看示例分析效果", expanded=False):
    st.markdown("**示例笔记**：《这5个平价护肤品，学生党闭眼入！》")
    st.caption("点赞 2.3万 | 收藏 1.8万 | 评论 3600")
    
    # 示例摘要卡
    st.markdown("---")
    st.markdown("#### 🎯 快速摘要")
    demo_col1, demo_col2 = st.columns([1, 2])
    with demo_col1:
        st.metric("AI 选题评分", "9/10")
        st.caption("精准命中学生群体护肤刚需，搜索+浏览双通道流量")
    with demo_col2:
        st.markdown("**💡 Top 行动建议：**")
        st.markdown("1. 标题加入「2024最新」时效词，抢占搜索流量")
        st.markdown("2. 正文第3段加引导「你们用的哪款？评论区分享」提升评论率")
        st.markdown("3. 封面加价格对比数据「¥39 vs ¥390」提升点击率")
    
    # 示例标签页
    st.markdown("---")
    st.markdown("#### 📖 详细分析预览")
    demo_tabs = st.tabs(["📋 选题评分", "📝 标题拆解", "💬 互动设计", "💡 行动建议"])
    with demo_tabs[0]:
        st.markdown("""**9/10 - 优质选题**

- **选题类型**：好物推荐型 × 痛点解决型（高复合价值）
- **目标人群**：学生群体（体量大、消费决策链短、分享意愿强）
- **流量模式**：搜索+浏览双通道 ——\u201c学生 护肤品 平价\u201d为高搜索量长尾词，同时标题的数字+身份标签适合信息流推荐""")
    with demo_tabs[1]:
        st.markdown("""**标题公式拆解**

- **钩子技巧**：数字锚定（\u201c5个\u201d）+ 身份共鸣（\u201c学生党\u201d）+ 利益承诺（\u201c闭眼入\u201d）
- **字数**：19字（最优区间18-25字 ✓）
- **SEO布局**：\u201c平价护肤品\u201d+\u201c学生党\u201d 两个高搜索量关键词在前半段
- **可复用模板**：「这X个[品类关键词]，[目标人群]闭眼入！」""")
    with demo_tabs[2]:
        st.markdown("""**高互动驱动分析**

- **收藏驱动**：清单体+具体产品名+价格 → 用户\u201c存着以后买\u201d → 收藏率 78%（极高）
- **评论驱动**：产品选择天然引发讨论 → \u201c我用的是XX更好用\u201d → 3600条评论
- **转发动机**：利他分享 → \u201c这个适合我室友/闺蜜\u201d → 社交推荐链""")
    with demo_tabs[3]:
        st.markdown("""**可执行建议（示例）**

1. **标题优化**：开头加「2024最新」→ \u201c2024最新！这5个平价护肤品，学生党闭眼入\u201d，预计搜索点击率提升20%
2. **引导评论**：正文结尾加\u201c你们还有什么平价好物？评论区分享一下🙏\u201d，预计评论数增长15%
3. **封面强化**：加一行\u201c均价¥39\u201d的价格标签，制造对比锚点，预计点击率提升25%
4. **追加SEO**：标签增加\u201c大学生必备\u201d\u201c宿舍好物\u201d，扩大搜索流量入口""")
    
    st.info("👆 以上是示例效果，粘贴你的笔记数据即可获得同样深度的个性化分析！")

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

    # 图文教程
    st.markdown("**📸 图文教程（点击可放大）：**")
    tutorial_cols = st.columns(4)
    with tutorial_cols[0]:
        st.image("resourse/添加网页.png", caption="① 添加网页", use_container_width=True)
    with tutorial_cols[1]:
        st.image("resourse/添加书签.png", caption="② 添加书签", use_container_width=True)
    with tutorial_cols[2]:
        st.image("resourse/提取笔记.png", caption="③ 提取笔记", use_container_width=True)
    with tutorial_cols[3]:
        st.image("resourse/粘贴.png", caption="④ 粘贴数据", use_container_width=True)

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

    # TODO: 登录注册功能暂时关闭，后续恢复
    # if AUTH_ENABLED:
    #     user = get_current_user()
    #     if not user:
    #         st.warning("🔒 请先登录或注册（注册即送 10 次免费分析）")
    #         st.stop()
    #     remaining = check_quota(user["id"])
    #     if remaining <= 0:
    #         st.error("😢 免费次数已用完（10/10），请联系获取更多额度")
    #         st.stop()

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
        media_label = f"🖼️ 媒体内容（{len(img_urls)}张图{'、含视频' if has_video else ''}）"
        with st.expander(media_label, expanded=False):
            st.caption("⚠️ 媒体来自小红书CDN，链接有时效性")
            # 图片画廊
            if img_urls:
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
                duration = video.get("duration", 0)
                height = video.get("height", 0)
                info_parts = []
                if duration:
                    minutes, seconds = divmod(int(duration), 60)
                    info_parts.append(f"时长 {minutes}:{seconds:02d}")
                if height:
                    info_parts.append(f"分辨率 {height}p")
                if info_parts:
                    st.caption("视频：" + " | ".join(info_parts))
                try:
                    st.video(video["url"])
                except Exception:
                    st.info("视频加载失败（链接可能已过期）")

    # ---- 数据洞察（纯算法，不依赖 AI） ----
    engagement_insights = analyze_engagement(likes, collects, comments, shares)
    content_traits = get_content_type_analysis(likes, collects, comments, note_type, image_count)

    insight_summary = f"{len(engagement_insights)}条互动洞察、{len(content_traits)}条内容特征" if (engagement_insights or content_traits) else "数据不足"
    with st.expander(f"📊 数据洞察（{insight_summary}）", expanded=False):
        if engagement_insights:
            for emoji_title, detail in engagement_insights:
                st.markdown(f"**{emoji_title}**　{detail}")
        else:
            st.info("互动数据不足，暂无法生成数据洞察")
        if content_traits:
            st.markdown("**内容特征：**" + "　|　".join(content_traits))

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
    dims_param = selected_dims if len(selected_dims) < len(all_dimensions) else None
    try:
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
            dimensions=dims_param,
        )
    except TypeError:
        # 兼容旧版 knowledge_base.py（无 dimensions 参数）
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

            # TODO: 登录注册功能暂时关闭，后续恢复
            # if AUTH_ENABLED and get_current_user():
            #     consume_quota(get_current_user()["id"], title)

            # === 三层金字塔展示 ===
            try:
                exec_summary = parse_executive_summary(ai_result)
            except Exception:
                exec_summary = {"score": None, "score_max": 5000, "score_detail": "", "summary": "", "top3_actions": []}

            # 降级兼容：从 parse_ai_sections 提取 fallback 数据
            sections = parse_ai_sections(ai_result)
            if exec_summary["score"] is None and sections:
                # 尝试从选题评分维度提取分数作为替代
                import re as _re
                _score_text = sections.get("📋 选题评分", "")
                _sm = _re.search(r'(\d+(?:\.\d+)?)\s*/\s*10', _score_text)
                if _sm:
                    try:
                        exec_summary["score"] = int(float(_sm.group(1)) * 500)
                        exec_summary["score_max"] = 5000
                    except Exception:
                        pass

            if not exec_summary["top3_actions"] and sections:
                # 尝试从行动建议维度提取前3条
                import re as _re
                _advice_text = sections.get("💡 行动建议", "")
                _actions = _re.findall(r'\d+[.\、]\s*(.+)', _advice_text)
                if _actions:
                    exec_summary["top3_actions"] = [a.strip()[:80] for a in _actions[:3]]

            # --- 第一层：爆款指数 + 一句话总结（始终可见） ---
            if exec_summary["score"] is not None:
                score_val = exec_summary["score"]
                score_max = exec_summary["score_max"]
                score_pct = score_val / score_max if score_max > 0 else 0

                st.markdown("### 🔥 爆款指数")
                col_score, col_detail = st.columns([1, 2])
                with col_score:
                    color = '#ff4b4b' if score_pct >= 0.8 else '#ffa500' if score_pct >= 0.6 else '#666'
                    st.markdown(
                        f"<h1 style='margin:0; color: {color};'>{score_val} "
                        f"<span style='font-size:0.5em; color:#999'>/ {score_max}</span></h1>",
                        unsafe_allow_html=True
                    )
                with col_detail:
                    st.progress(min(score_pct, 1.0))
                    if exec_summary["score_detail"]:
                        st.caption(exec_summary["score_detail"])

            if exec_summary["summary"]:
                st.markdown(f"> **{exec_summary['summary']}**")

            st.markdown("---")

            # --- 第二层：你现在最该做的3件事（始终可见） ---
            if exec_summary["top3_actions"]:
                st.markdown("### 🎯 你现在最该做的3件事")
                for i, action in enumerate(exec_summary["top3_actions"], 1):
                    st.markdown(f"**{i}.** {action}")
                st.markdown("---")

            # --- 第三层：完整分析报告（折叠） ---
            with st.expander("📊 查看完整分析报告（点击展开）", expanded=False):
                tab_order = ["📋 选题评分", "📝 标题拆解", "🖼️ 封面策略",
                             "📚 内容结构", "💬 互动设计", "🔍 算法适配", "💡 行动建议"]
                available_tabs = [t for t in tab_order if t in sections]

                if available_tabs:
                    tabs = st.tabs(available_tabs)
                    for tab, tab_name in zip(tabs, available_tabs):
                        with tab:
                            st.markdown(sections[tab_name])
                else:
                    # fallback: 直接显示原始AI输出
                    st.markdown(ai_result)

            # ---- 导出报告 ----
            st.markdown("---")
            html_report = generate_html_report(
                title=title, author=author,
                likes=likes, collects=collects, comments=comments, shares=shares,
                score=score, level=level, hours=hours,
                engagement_insights=engagement_insights,
                content_traits=content_traits,
                ai_result=ai_result,
                category=category,
                exec_summary=exec_summary,
            )

            # ---- 导出按钮区域 ----
            export_col1, export_col2 = st.columns(2)

            with export_col1:
                st.download_button(
                    label="📥 导出 HTML 报告",
                    data=html_report,
                    file_name=f"爆款拆解_{title[:20]}.html",
                    mime="text/html",
                    use_container_width=True,
                )

            with export_col2:
                if st.button("📸 导出报告截图", use_container_width=True, key="export_png"):
                    st.session_state["show_screenshot_preview"] = True

            # 截图：使用 html2canvas 客户端方案，加载后自动截图下载
            if st.session_state.get("show_screenshot_preview"):
                screenshot_component = f'''
                <div id="report-content" style="position:absolute; left:-9999px; top:0; width:1200px; background:#fff; padding:20px;">
                    {html_report}
                </div>
                <div id="status-box" style="text-align:center; padding:40px 20px;">
                    <p id="status-text" style="color:#666; font-size:16px;">⏳ 正在生成截图，请稍候...</p>
                </div>
                <script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
                <script>
                window.onload = function() {{{{
                    var element = document.getElementById('report-content');
                    var status = document.getElementById('status-text');
                    html2canvas(element, {{{{
                        scale: 2,
                        useCORS: true,
                        allowTaint: true,
                        backgroundColor: '#ffffff',
                        logging: false,
                        width: 1200
                    }}}}).then(function(canvas) {{{{
                        var link = document.createElement('a');
                        link.download = '爆款拆解报告.png';
                        link.href = canvas.toDataURL('image/png');
                        link.click();
                        status.textContent = '✅ 截图已生成并开始下载！';
                        status.style.color = '#10b981';
                    }}}}).catch(function(err) {{{{
                        status.textContent = '❌ 截图失败：' + err.message;
                        status.style.color = '#ef4444';
                    }}}});
                }}}};
                </script>
                '''

                st.components.v1.html(screenshot_component, height=100, scrolling=False)
        except Exception as e:
            st.error(f"分析失败：{e}")

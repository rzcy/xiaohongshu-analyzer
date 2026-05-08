"""
小红书爆款拆解器 - Streamlit Demo
用户通过书签一键提取笔记数据 → 粘贴到此页面 → 数据洞察 + AI拆解分析
部署：Streamlit Cloud
"""

import json
import math
from collections import Counter
import streamlit as st
from openai import OpenAI

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
    st.divider()
    st.caption("单次分析成本 ≈ ¥0.002")


# ============ 书签脚本（增强版：提取更多字段） ============
BOOKMARKLET = """javascript:void(function(){try{var s=window.__INITIAL_STATE__;if(!s||!s.note){alert('请在小红书笔记页面使用');return}var cid=s.note.currentNoteId;var noteId=(cid&&cid._value)?cid._value:(typeof cid==='string'?cid:'');var m=s.note.noteDetailMap;var keys=Object.keys(m).filter(function(k){return k&&k!=='undefined'&&k.length>5});var key=noteId&&m[noteId]?noteId:keys[0];if(!key){alert('未找到笔记数据，请刷新页面重试');return}var entry=m[key];var raw=entry.__v_raw||entry;var d=raw.note.__v_raw||raw.note;if(!d||!d.title){alert('笔记数据为空，请刷新重试');return}var interact=d.interactInfo?(d.interactInfo.__v_raw||d.interactInfo):{};var user=d.user?(d.user.__v_raw||d.user):{};var tags=d.tagList?(d.tagList.__v_raw||d.tagList):[];var imgs=d.imageList?(d.imageList.__v_raw||d.imageList):[];var imgUrls=Array.from(imgs||[]).map(function(img){var i=img.__v_raw||img;return{url:i.urlDefault||i.urlPre||'',w:i.width||0,h:i.height||0}}).filter(function(x){return x.url});var vid=d.video?(d.video.__v_raw||d.video):null;var videoInfo=null;if(vid){var media=vid.media?(vid.media.__v_raw||vid.media):null;if(media){var vs=media.stream?(media.stream.__v_raw||media.stream):{};var h264=vs.h264||[];var best=h264[0]||{};var vv=media.video?(media.video.__v_raw||media.video):{};videoInfo={url:best.masterUrl||'',duration:vv.duration||0,height:best.height||0}}else{videoInfo={url:vid.url||vid.urlDefault||'',duration:vid.duration||0,height:0}}}var r={title:d.title||'',content:d.desc||'',tags:Array.from(tags||[]).map(function(t){return t.name||t}),likes:parseInt(interact.likedCount||0),collects:parseInt(interact.collectedCount||0),comments:parseInt(interact.commentCount||0),shares:parseInt(interact.shareCount||0),author:user.nickname||'',noteType:d.type||'normal',images:imgUrls,video:videoInfo,time:d.time||''};var ta=document.createElement('textarea');ta.value=JSON.stringify(r);document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);alert('✅ 已复制！回到拆解器页面粘贴即可')}catch(e){alert('提取失败：'+e.message+'\\n请确认当前在笔记详情页')}})()"""


# ============ 数据分析函数 ============
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
    elif image_count <= 2 and note_type != "video":
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


# ============ Prompt（优化版：适应短内容） ============
PROMPT = """# 角色
你是一位资深小红书内容策略师，已分析过10000+篇爆款笔记。你的分析以数据为依据，以实操为导向。

# 任务
深度拆解这篇小红书笔记，帮博主理解「为什么这种内容能火」以及「如何复用这套打法」。

# 笔记信息
- 标题：{title}
- 正文：{content}
- 标签：{tags}
- 互动数据：👍{likes} ⭐{collects} 💬{comments} 🔗{shares}
- 笔记类型：{note_type}（{image_count}张图）
- 爆款指数：{score}（{level}）
- 数据特征：{data_traits}
- 视觉信息：{media_info}

# 分析要求

## 1. 爆款内核（最重要）
这篇笔记的「1个核心爆点」是什么？用一句话概括它打动用户的底层逻辑。
然后分析：
- 戳中了什么具体场景下的什么需求？
- 为什么用户愿意点赞/收藏/分享？（结合上面的数据特征来分析）

## 2. 标题拆解
- 这个标题用了什么心理机制？（好奇心缺口/社交认同/利益承诺/情绪共鸣/反常识）
- 标题中哪个词/句式是关键触发词？
- 提炼 2-3 个可直接套用的标题模板：
  - 模板格式：___（地点/品类）+ ___（程度词）+ ___（行为/结果）
  - 每个模板给一个具体示例

## 3. 内容策略
- 这篇采用了什么内容结构？（注意：小红书短内容往往靠「留白」和「图片叙事」取胜）
- 文案的信息密度策略是什么？（极简引导 vs 密集干货）
- 正文中哪些词句在引导用户互动？
- 图片排列策略/视频节奏：图片数量、尺寸比例、排序逻辑如何服务于内容表达？视频类则分析时长和节奏设计。

## 4. 可复用打法
给出 2 个不同品类博主可以直接套用的仿写方案：

**方案A（同品类）：**
- 标题：（直接可用）
- 正文话术：（30字以内，模仿原文风格）
- 关键要素：封面怎么拍、几张图、什么角度

**方案B（跨品类迁移）：**
- 适用品类：
- 标题：
- 套用逻辑：为什么同一套路在其他品类也能火

# 输出风格
- 每个点 2-4 句话，不要写成论文
- 多用「因为...所以...」的因果逻辑，少用形容词
- 关键结论加粗标注"""


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
hours = st.slider("⏰ 大约发了多久？", 1, 720, 48, help="用于计算爆款指数，估算即可")
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
    if images or video:
        st.markdown("---")
        st.markdown("### 🖼️ 媒体内容")
        st.caption("⚠️ 媒体内容来自小红书CDN，链接有时效性，仅临时有效")

        # 图片画廊
        if images:
            st.markdown("**图片**")
            img_urls = [img.get("url", "") for img in images if img.get("url")]
            # 每行3张图
            for row_start in range(0, len(img_urls), 3):
                row_imgs = img_urls[row_start:row_start + 3]
                cols = st.columns(3)
                for idx, url in enumerate(row_imgs):
                    with cols[idx]:
                        try:
                            st.image(url, use_container_width=True)
                        except Exception:
                            st.info(f"图片 {row_start + idx + 1} 加载失败（链接可能已过期）")

        # 视频播放
        if video and video.get("url"):
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

    # ---- AI 拆解 ----
    st.markdown("---")
    st.markdown("### 🤖 AI 深度拆解")

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

    prompt = PROMPT.format(
        title=title,
        content=data.get("content", ""),
        tags=tag_str,
        likes=likes, collects=collects, comments=comments, shares=shares,
        note_type="视频" if note_type == "video" else "图文",
        image_count=image_count,
        score=score, level=level,
        data_traits=data_traits_str,
        media_info=media_info_str,
    )

    with st.spinner("AI 深度分析中，约 15 秒..."):
        try:
            base = f"{api_base}/v1" if not api_base.endswith("/v1") else api_base
            client = OpenAI(api_key=api_key, base_url=base)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=3000,
            )
            st.markdown(resp.choices[0].message.content)
        except Exception as e:
            st.error(f"分析失败：{e}")

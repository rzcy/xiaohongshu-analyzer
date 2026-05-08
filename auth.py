"""
小红书爆款拆解器 - 用户认证与配额管理模块
基于 Supabase Auth + PostgreSQL
"""
from __future__ import annotations

import streamlit as st
from supabase import create_client, Client


@st.cache_resource
def get_supabase_client() -> Client:
    """获取 Supabase 客户端（全局单例，缓存复用）"""
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


def sign_up(email: str, password: str) -> dict:
    """
    用户注册
    返回: {"success": bool, "message": str, "user": dict|None}
    """
    try:
        client = get_supabase_client()
        res = client.auth.sign_up({"email": email, "password": password})
        if res.user:
            return {"success": True, "message": "注册成功！请查收验证邮件", "user": res.user}
        return {"success": False, "message": "注册失败，请稍后重试", "user": None}
    except Exception as e:
        msg = str(e)
        if "already registered" in msg.lower() or "already exists" in msg.lower():
            return {"success": False, "message": "该邮箱已注册，请直接登录", "user": None}
        return {"success": False, "message": f"注册失败：{msg}", "user": None}


def sign_in(email: str, password: str) -> dict:
    """
    用户登录
    返回: {"success": bool, "message": str, "user": dict|None}
    """
    try:
        client = get_supabase_client()
        res = client.auth.sign_in_with_password({"email": email, "password": password})
        if res.user:
            user_data = {
                "id": res.user.id,
                "email": res.user.email,
            }
            st.session_state["user"] = user_data
            st.session_state["access_token"] = res.session.access_token
            return {"success": True, "message": "登录成功", "user": user_data}
        return {"success": False, "message": "登录失败", "user": None}
    except Exception as e:
        msg = str(e)
        if "invalid" in msg.lower() or "credentials" in msg.lower():
            return {"success": False, "message": "邮箱或密码错误", "user": None}
        return {"success": False, "message": f"登录失败：{msg}", "user": None}


def sign_out():
    """用户登出，清除 session"""
    st.session_state.pop("user", None)
    st.session_state.pop("access_token", None)


def get_current_user() -> dict | None:
    """获取当前登录用户信息，未登录返回 None"""
    return st.session_state.get("user", None)


def check_quota(user_id: str) -> int:
    """
    检查用户剩余免费分析次数
    如果是新用户（配额表中无记录），自动初始化 10 次
    返回: 剩余次数
    """
    try:
        client = get_supabase_client()
        quota = client.table("user_quotas").select("*").eq("user_id", user_id).execute()
        if not quota.data:
            # 新用户，初始化配额
            client.table("user_quotas").insert({
                "user_id": user_id,
                "free_limit": 10,
                "used_count": 0,
            }).execute()
            return 10
        record = quota.data[0]
        return record["free_limit"] - record["used_count"]
    except Exception:
        # 数据库异常时不阻塞用户使用
        return 10


def consume_quota(user_id: str, note_title: str = "") -> bool:
    """
    消耗一次分析配额
    同时在 usage_records 表记录使用历史
    返回: 是否成功扣减
    """
    try:
        client = get_supabase_client()
        
        # 获取当前使用量
        quota = client.table("user_quotas").select("used_count").eq("user_id", user_id).execute()
        if quota.data:
            new_count = quota.data[0]["used_count"] + 1
            client.table("user_quotas").update({"used_count": new_count}).eq("user_id", user_id).execute()
        else:
            # 配额记录不存在，创建并标记已使用1次
            client.table("user_quotas").insert({
                "user_id": user_id,
                "free_limit": 10,
                "used_count": 1,
            }).execute()
        
        # 记录使用历史
        client.table("usage_records").insert({
            "user_id": user_id,
            "note_title": note_title[:200] if note_title else "",
        }).execute()
        
        return True
    except Exception:
        # 扣减失败不阻塞分析流程
        return False


def render_auth_ui():
    """
    渲染侧边栏认证 UI
    返回: 当前用户 dict 或 None
    """
    user = get_current_user()
    
    if user:
        st.success(f"✓ {user['email']}")
        remaining = check_quota(user["id"])
        st.caption(f"剩余免费次数：{remaining}/10")
        if st.button("退出登录", use_container_width=True):
            sign_out()
            st.rerun()
        st.divider()
        return user
    else:
        auth_mode = st.radio("账号", ["登录", "注册"], horizontal=True, label_visibility="collapsed")
        email = st.text_input("邮箱", placeholder="your@email.com")
        password = st.text_input("密码", type="password", placeholder="至少6位")
        
        if auth_mode == "登录":
            if st.button("登录", use_container_width=True, type="primary"):
                if not email or not password:
                    st.error("请填写邮箱和密码")
                else:
                    result = sign_in(email, password)
                    if result["success"]:
                        st.success(result["message"])
                        st.rerun()
                    else:
                        st.error(result["message"])
        else:
            if st.button("注册", use_container_width=True, type="primary"):
                if not email or not password:
                    st.error("请填写邮箱和密码")
                elif len(password) < 6:
                    st.error("密码至少6位")
                else:
                    result = sign_up(email, password)
                    if result["success"]:
                        st.success(result["message"])
                    else:
                        st.error(result["message"])
        
        st.divider()
        return None

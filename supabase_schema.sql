-- 用户配额表
CREATE TABLE IF NOT EXISTS user_quotas (
    user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
    free_limit int DEFAULT 10 NOT NULL,
    used_count int DEFAULT 0 NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL
);

-- 使用记录表
CREATE TABLE IF NOT EXISTS usage_records (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL,
    note_title text DEFAULT ''
);

-- 启用 RLS（行级安全）
ALTER TABLE user_quotas ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_records ENABLE ROW LEVEL SECURITY;

-- RLS 策略：用户只能访问自己的数据
CREATE POLICY "Users can view own quota" ON user_quotas
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own quota" ON user_quotas
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own quota" ON user_quotas
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can view own records" ON usage_records
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own records" ON usage_records
    FOR INSERT WITH CHECK (auth.uid() = user_id);

-- 为 service_role 添加完整访问（后端API调用需要）
-- 注意：Streamlit 使用 anon key，需要 RLS 策略放行
-- 或者使用 service_role key（更简单但安全性稍低）

import streamlit as st
import requests
import json
import asyncio
import edge_tts
import os
import random
import hashlib
import csv
import io
from datetime import datetime

# --- 核心配置区 ---
API_URL = "https://api.deepseek.com/chat/completions" 
API_KEY = st.secrets["DEEPSEEK_API_KEY"] 
DB_FILE = "my_vocab_db.json"

# --- 0. 数据库引擎 ---
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"history": [], "favorites": []}

def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# --- 0.5 导出引擎 (新增：将 JSON 转换为 Anki 兼容的 CSV 格式) ---
def generate_anki_csv(favorites):
    output = io.StringIO()
    writer = csv.writer(output)
    # 写入表头
    writer.writerow(['法语单词', '中文释义', '词性', '例句', '例句翻译', '词形溯源'])
    for item in favorites:
        writer.writerow([
            item.get('word_with_article', ''),
            item.get('chinese', ''),
            item.get('part_of_speech', ''),
            item.get('example_fr', ''),
            item.get('example_cn', ''),
            item.get('word_origin', '')
        ])
    # 必须使用 utf-8-sig 编码，否则导出后用 Excel 打开法语字符和中文会乱码
    return output.getvalue().encode('utf-8-sig')

# --- 1. 核心翻译引擎 ---
@st.cache_data(show_spinner=False, ttl=86400) 
def get_translation(word):
    prompt = f"""
    我正在备考法语 TCF 考试，请精准分析用户输入的法语单词："{word}"。
    【指令】：如果是变位/变形词，请还原为原型（Base Form）解析！
    
    按以下 JSON 输出：
    {{
        "word_origin": "如是变位变形词，解释来源；若是原型则留空",
        "word_with_article": "名词加 un/une 或 le/la，动词等原样",
        "part_of_speech": "原型词词性",
        "english": "英文翻译",
        "chinese": "中文翻译",
        "synonyms": [{{"fr": "法语同义词", "cn": "中文翻译"}}],
        "antonyms": [{{"fr": "法语反义词", "cn": "中文翻译"}}],
        "collocations": ["搭配1 (中文)", "搭配2 (中文)"], 
        "example_fr": "包含该单词的实用例句",
        "example_cn": "例句的中文翻译",
        "conjugation": "动词提供直陈式现在时变位；非动词留空"
    }}
    """
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    data = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
    
    try:
        response = requests.post(API_URL, headers=headers, json=data)
        resp_data = response.json()
        if 'choices' not in resp_data:
            return {"error": f"API 拒绝请求：{resp_data}"}
        result_text = resp_data['choices'][0]['message']['content']
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        return json.loads(result_text)
    except Exception as e:
        return {"error": str(e)}

# --- 1.5 实战对话生成引擎 ---
@st.cache_data(show_spinner=False, ttl=86400)
def get_dialogue(word):
    prompt = f"""
    请使用法语单词 "{word}" 编写一段非常简短的日常生活双人对话（A和B）。
    严格按以下 JSON 格式输出：
    {{
        "scenario": "一句话描述场景（如：在巴黎的咖啡馆）",
        "dialogue": [
            {{"speaker": "A", "fr": "法语句子", "cn": "中文翻译"}},
            {{"speaker": "B", "fr": "法语句子", "cn": "中文翻译"}}
        ]
    }}
    """
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    data = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.5}
    
    try:
        response = requests.post(API_URL, headers=headers, json=data)
        result_text = response.json()['choices'][0]['message']['content']
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        return json.loads(result_text)
    except Exception as e:
        return {"error": str(e)}

# --- 1.8 句子互译引擎 ---
@st.cache_data(show_spinner=False, ttl=86400)
def get_text_translation(text):
    prompt = f"""
    你是一个专业的法语翻译官。请将以下文本进行中法互译。
    如果输入是法语，请翻译成中文；如果输入是中文，请翻译成地道的法语。
    待翻译文本："{text}"
    只返回纯净的翻译结果，不要有任何多余的废话或解释。
    """
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    data = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
    
    try:
        response = requests.post(API_URL, headers=headers, json=data)
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        return f"翻译出错了: {str(e)}"

# --- 2. 同步发音引擎 ---
@st.cache_data(show_spinner=False)
def get_audio_sync(text, prefix="audio"):
    text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
    filename = f"{prefix}_{text_hash}.mp3"
    return asyncio.run(generate_audio(text, filename))

async def generate_audio(text, filename):
    if not os.path.exists(filename):
        communicate = edge_tts.Communicate(text, "fr-FR-DeniseNeural")
        await communicate.save(filename)
    return filename

# --- 全局公共引擎 ---
def execute_search(target_word):
    st.session_state.dialogue_for = None 
    found_local = None
    for item in st.session_state.db['history']:
        if item['original_word'].lower() == target_word.lower():
            found_local = item
            break
            
    if found_local:
        st.session_state.current_word = found_local
        st.toast(f"⚡ 已极速跳转至【{target_word}】", icon="⚡")
    else:
        with st.spinner(f"正在全网解析衍生词汇【{target_word}】..."):
            data = get_translation(target_word)
            if "error" in data:
                st.error(data['error'])
                return
            else:
                data['query_time'] = datetime.now().strftime("%Y-%m-%d %H:%M")
                data['original_word'] = target_word
                st.session_state.current_word = data
                st.session_state.db['history'].insert(0, data)
                save_db(st.session_state.db)
    st.rerun() 

# --- 3. 界面绘制 ---
st.set_page_config(page_title="TCF 专属法语词典", page_icon="🇫🇷", layout="centered")

if 'db' not in st.session_state:
    st.session_state.db = load_db()
if 'current_word' not in st.session_state:
    st.session_state.current_word = None

st.title("🇫🇷 TCF 核心词库系统")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔍 查词", "⭐ 背诵", "🕒 历史", "🎯 盲盒", "🌐 翻译"])

# ================= TAB 1: 查词工作台 =================
with tab1:
    with st.form("search_form", clear_on_submit=True):
        word_input = st.text_input("🔍 请输入法语单词 (自动匹配历史词库或全网解析)：").strip()
        submit_btn = st.form_submit_button("🚀 极速解析")
        
    if submit_btn and word_input:
        execute_search(word_input)

    if st.session_state.current_word:
        cw = st.session_state.current_word
        st.markdown("---")
        
        if cw.get("word_origin"):
            st.info(f"💡 **词形溯源**：{cw.get('word_origin')}")
            
        is_favorited = any(item.get('original_word') == cw['original_word'] for item in st.session_state.db['favorites'])
        
        col_title, col_btn = st.columns([3, 1])
        with col_title:
            st.subheader(f"✨ {cw.get('word_with_article', cw['original_word'])}")
        with col_btn:
            if is_favorited:
                st.button("✅ 已收藏", disabled=True)
            else:
                if st.button("❤️ 加入背诵"):
                    st.session_state.db['favorites'].insert(0, cw)
                    save_db(st.session_state.db)
                    st.rerun() 
                    
        st.caption(f"词性：{cw.get('part_of_speech', '')}")
        st.success(f"🇨🇳 {cw.get('chinese', '')}  |  🇬🇧 {cw.get('english', '')}")
        
        word_audio = get_audio_sync(cw.get("word_with_article", cw['original_word']), "word")
        st.audio(word_audio, format="audio/mp3")
        
        if cw.get("conjugation"):
            st.warning(f"⚙️ 变位: {cw.get('conjugation')}")
        
        if cw.get("synonyms") or cw.get("antonyms"):
            st.markdown("### 🧬 词汇拓展 (点击直接跳转)")
            col_syn, col_ant = st.columns(2)
            with col_syn:
                st.write("**同义词:**")
                for i, syn in enumerate(cw.get("synonyms", [])):
                    if isinstance(syn, dict) and syn.get("fr"):
                        btn_label = f"🔍 {syn.get('fr')} ({syn.get('cn', '')})"
                        target_word = syn.get('fr')
                    else:
                        btn_label = f"🔍 {syn}"
                        target_word = str(syn)
                        
                    if st.button(btn_label, key=f"syn_{i}_{cw['original_word']}"):
                        execute_search(target_word)
                        
            with col_ant:
                st.write("**反义词:**")
                for i, ant in enumerate(cw.get("antonyms", [])):
                    if isinstance(ant, dict) and ant.get("fr"):
                        btn_label = f"🔍 {ant.get('fr')} ({ant.get('cn', '')})"
                        target_word = ant.get('fr')
                    else:
                        btn_label = f"🔍 {ant}"
                        target_word = str(ant)
                        
                    if st.button(btn_label, key=f"ant_{i}_{cw['original_word']}"):
                        execute_search(target_word)
            
        collocations = cw.get("collocations", [])
        if collocations:
            st.markdown("### 🔗 常用搭配")
            for col in collocations:
                st.write(f"- {col}")
            
        st.markdown("### 📝 实用例句")
        st.write(f"**{cw.get('example_fr', '')}**")
        st.write(f"*{cw.get('example_cn', '')}*")
        
        if cw.get("example_fr"):
            example_audio = get_audio_sync(cw.get("example_fr"), "example")
            st.audio(example_audio, format="audio/mp3")
            
        st.markdown("---")
        if st.button("💬 一键生成【生活实战场景对话】"):
            st.session_state.dialogue_for = cw['original_word']
            
        if st.session_state.get('dialogue_for') == cw['original_word']:
            with st.spinner("正在连线大模型排练对话剧本，并录制语音中..."):
                d_data = get_dialogue(cw['original_word'])
                if "error" not in d_data:
                    st.info(f"🎭 **场景：{d_data.get('scenario', '')}**")
                    for line in d_data.get('dialogue', []):
                        st.write(f"**{line.get('speaker')}**: {line.get('fr')}")
                        st.caption(f"_{line.get('cn')}_")
                        dia_audio = get_audio_sync(line.get('fr'), "dialogue")
                        st.audio(dia_audio, format="audio/mp3")
                else:
                    st.error("生成对话失败，请重试。")

# ================= TAB 2: 我的背诵列表 (升级：新增 Anki 导出) =================
with tab2:
    st.header("⭐ 待攻克核心词汇")
    if not st.session_state.db['favorites']:
        st.info("你的背诵列表还是空的，快去查词台添加吧！")
    else:
        # ✨ 新增：生成 CSV 并提供下载按钮 ✨
        csv_data = generate_anki_csv(st.session_state.db['favorites'])
        st.download_button(
            label="💾 一键导出为 Anki 格式 (CSV)",
            data=csv_data,
            file_name=f"tcf_vocab_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            help="下载后可直接导入 Anki，第一列为正面，后面几列为背面。"
        )
        st.divider()
    
    for item in st.session_state.db['favorites']:
        with st.expander(f"{item.get('word_with_article')} - {item.get('chinese')}"):
            if item.get("word_origin"):
                st.caption(f"💡 {item.get('word_origin')}")
            st.write(f"**词性**: {item.get('part_of_speech')}")
            st.write(f"**例句**: {item.get('example_fr')}")

# ================= TAB 3: 历史记录 =================
with tab3:
    st.header("🕒 查词轨迹")
    for i, item in enumerate(st.session_state.db['history'][:50]):
        col1, col2 = st.columns([4, 1])
        with col1:
            st.write(f"**{item.get('word_with_article')}** ({item.get('chinese')})")
            st.caption(f"时间: {item.get('query_time')}")
        with col2:
            if st.button("🔄 查看", key=f"hist_btn_{i}_{item.get('original_word')}"):
                execute_search(item['original_word'])
        st.divider()

# ================= TAB 4: 刷词大挑战 =================
with tab4:
    st.header("🎯 盲盒记忆挑战")
    if not st.session_state.db['favorites']:
        st.warning("背诵列表为空！请先去查词台【加入背诵】。")
    else:
        if 'fc_word' not in st.session_state:
            st.session_state.fc_word = random.choice(st.session_state.db['favorites'])
            st.session_state.fc_revealed = False
            
        col1, col2 = st.columns([3, 1])
        with col2:
            if st.button("🎲 换一个词"):
                st.session_state.fc_word = random.choice(st.session_state.db['favorites'])
                st.session_state.fc_revealed = False
                st.rerun()
                
        st.markdown(f"<h2 style='text-align: center; color: #1E90FF; padding: 2rem 0;'>{st.session_state.fc_word.get('word_with_article')}</h2>", unsafe_allow_html=True)
        
        if not st.session_state.fc_revealed:
            if st.button("👀 翻开底牌，查看释义", use_container_width=True):
                st.session_state.fc_revealed = True
                st.rerun()
        else:
            fc_w = st.session_state.fc_word
            st.success(f"🇨🇳 **{fc_w.get('chinese')}**")
            st.write(f"**英文**: {fc_w.get('english')}")
            st.info(f"**例句**: {fc_w.get('example_fr')}\n\n_{fc_w.get('example_cn')}_")
            
            fc_audio = get_audio_sync(fc_w.get("word_with_article"), "fc")
            st.audio(fc_audio, format="audio/mp3")

# ================= TAB 5: 句子翻译 =================
with tab5:
    st.header("🌐 智能中法互译")
    st.caption("输入法语长句自动翻译为中文；输入中文自动翻译为地道法语。")
    
    with st.form("translate_form"):
        trans_input = st.text_area("请输入要翻译的文本：", height=150)
        trans_btn = st.form_submit_button("开始翻译 🚀")
        
    if trans_btn and trans_input:
        with st.spinner("正在呼叫翻译官并录制发音..."):
            result = get_text_translation(trans_input)
            st.success("翻译结果：")
            st.write(f"**{result}**")
            trans_audio = get_audio_sync(result, "trans")
            st.audio(trans_audio, format="audio/mp3")

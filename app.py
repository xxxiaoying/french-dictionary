import streamlit as st
import requests
import json
import asyncio
import edge_tts
import os
import random
import hashlib
import genanki # ✨ 新增：Anki 原生打包库
from datetime import datetime

# --- 核心配置区 ---
API_URL = "https://api.deepseek.com/chat/completions" 
API_KEY = "你的_API_KEY_填在这里" 
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

# --- 0.5 导出引擎 (核心：生成 .apkg 文件) ---
def generate_apkg(favorites):
    # 定义 Anki 卡片模型 (ID 随机生成)
    model_id = random.randrange(1 << 30, 1 << 31)
    deck_id = random.randrange(1 << 30, 1 << 31)
    
    my_model = genanki.Model(
      model_id,
      'TCF French Model',
      fields=[{'name': 'Question'}, {'name': 'Answer'}],
      templates=[{
        'name': 'Card 1',
        'qfmt': '{{Question}}',
        'afmt': '{{FrontSide}}<hr id="answer">{{Answer}}',
      }])

    my_deck = genanki.Deck(deck_id, 'TCF 核心词库')

    for item in favorites:
        question = f"<h3>{item.get('word_with_article')}</h3>"
        answer = f"<div><b>中文</b>: {item.get('chinese')}</div><br>" \
                 f"<div><b>词性</b>: {item.get('part_of_speech')}</div><br>" \
                 f"<div><b>例句</b>: {item.get('example_fr')}</div><br>" \
                 f"<div><i>{item.get('example_cn')}</i></div>"
        
        note = genanki.Note(model=my_model, fields=[question, answer])
        my_deck.add_note(note)

    # 打包并存入内存
    pkg_name = f"tcf_vocab_{datetime.now().strftime('%Y%m%d')}.apkg"
    genanki.Package(my_deck).write_to_file(pkg_name)
    
    with open(pkg_name, 'rb') as f:
        data = f.read()
    os.remove(pkg_name) # 清理临时文件
    return data, pkg_name

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

# --- 1.5 实战对话生成引擎 & 1.8 句子互译引擎 ---
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
            st.markdown("### 🧬 词汇拓展")
            col_syn, col_ant = st.columns(2)
            with col_syn:
                st.write("**同义词:**")
                for i, syn in enumerate(cw.get("synonyms", [])):
                    if isinstance(syn, dict) and syn.get("fr"):
                        btn_label = f"🔍 {syn.get('fr')}"
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
                        btn_label = f"🔍 {ant.get('fr')}"
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

# ================= TAB 2: 我的背诵列表 (Anki 导出) =================
with tab2:
    st.header("⭐ 待攻克核心词汇")
    if not st.session_state.db['favorites']:
        st.info("你的背诵列表还是空的，快去查词台添加吧！")
    else:
        # ✨ 升级：导出为 .apkg 格式 ✨
        apkg_data, filename = generate_apkg(st.session_state.db['favorites'])
        st.download_button(
            label="💾 一键导出为 Anki 牌组 (.apkg)",
            data=apkg_data,
            file_name=filename,
            mime="application/octet-stream",
            help="下载后发送到手机，点击即可导入 Anki App！"
        )
        st.divider()
    
    for item in st.session_state.db['favorites']:
        with st.expander(f"{item.get('word_with_article')} - {item.get('chinese')}"):
            if item.get("word_origin"):
                st.caption(f"💡 {item.get('word_origin')}")
            st.write(f"**词性**: {item.get('part_of_speech')}")
            st.write(f"**例句**: {item.get('example_fr')}")

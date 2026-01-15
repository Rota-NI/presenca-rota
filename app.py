import streamlit as st
import gspread
from gspread.exceptions import APIError
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, time, timedelta
import pytz
from fpdf import FPDF
import urllib.parse
import time as time_module
import random
import re

# ==========================================================
# CONFIGURAÇÃO DE ACESSO
# ==========================================================
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
SPREADSHEET_NAME = "ListaPresenca"
WS_USUARIOS = "Usuarios"
WS_CONFIG = "Config"
FUSO_BR = pytz.timezone("America/Sao_Paulo")

# ==========================================================
# UTILITÁRIOS DE TELEFONE
# ==========================================================
def tel_only_digits(s: str) -> str:
    return re.sub(r"\D+", "", str(s or ""))

def tel_format_br(digits: str) -> str:
    d = tel_only_digits(digits)
    if len(d) < 2: return d
    ddd = d[:2]
    rest = d[2:]
    if len(rest) >= 9: return f"({ddd}) {rest[:5]}.{rest[5:9]}"
    elif len(rest) > 5: return f"({ddd}) {rest[:5]}.{rest[5:]}"
    else: return f"({ddd}) {rest}"

def tel_is_valid_11(s: str) -> bool:
    return len(tel_only_digits(s)) == 11

# ==========================================================
# WRAPPER CONTRA ERRO 429 (QUOTA EXCEEDED)
# ==========================================================
def gs_call(func, *args, **kwargs):
    max_tries = 3
    for attempt in range(max_tries):
        try: return func(*args, **kwargs)
        except APIError as e:
            if "429" in str(e) or "Quota" in str(e):
                time_module.sleep(2 * (attempt + 1))
                continue
            raise
    return func(*args, **kwargs)

# ==========================================================
# CONEXÕES E LEITURAS (CACHE OTIMIZADO)
# ==========================================================
@st.cache_resource
def conectar_gsheets():
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=scope)
    return gspread.authorize(creds)

@st.cache_data(ttl=60)
def buscar_usuarios_cadastrados():
    try:
        client = conectar_gsheets()
        sheet_u = client.open(SPREADSHEET_NAME).worksheet(WS_USUARIOS)
        return gs_call(sheet_u.get_all_records)
    except: return []

@st.cache_data(ttl=120)
def buscar_limite_dinamico():
    try:
        client = conectar_gsheets()
        doc = client.open(SPREADSHEET_NAME)
        try: sheet_c = doc.worksheet(WS_CONFIG)
        except:
            sheet_c = doc.add_worksheet(title=WS_CONFIG, rows="10", cols="5")
            sheet_c.update('A1:A2', [['LIMITE'], ['100']])
        return int(sheet_c.acell('A2').value)
    except: return 100

@st.cache_data(ttl=10)
def buscar_presenca_atualizada():
    try:
        client = conectar_gsheets()
        return gs_call(client.open(SPREADSHEET_NAME).sheet1.get_all_values)
    except: return None

def ws_usuarios():
    return conectar_gsheets().open(SPREADSHEET_NAME).worksheet(WS_USUARIOS)

def ws_presenca():
    return conectar_gsheets().open(SPREADSHEET_NAME).sheet1

# ==========================================================
# LÓGICA DE NEGÓCIO
# ==========================================================
def filtrar_linhas_presenca(dados_p):
    if not dados_p or len(dados_p) < 2: return dados_p
    header = dados_p[0]
    body_ok = [r for r in dados_p[1:] if len(r) >= 6 and r[0] and r[3] and r[5]]
    return [header] + body_ok

def verificar_status_e_limpar(sheet_p, dados_p):
    agora = datetime.now(FUSO_BR)
    hora_atual = agora.time()
    if hora_atual >= time(18, 50): marco = agora.replace(hour=18, minute=50, second=0)
    elif hora_atual >= time(6, 50): marco = agora.replace(hour=6, minute=50, second=0)
    else: marco = (agora - timedelta(days=1)).replace(hour=18, minute=50, second=0)
    
    if dados_p and len(dados_p) > 1:
        try:
            ultima_dt = FUSO_BR.localize(datetime.strptime(dados_p[-1][0], "%d/%m/%Y %H:%M:%S"))
            if ultima_dt < marco:
                sheet_p.resize(rows=1); sheet_p.resize(rows=100)
                st.cache_data.clear(); st.rerun()
        except: pass
    
    dia = agora.weekday()
    aberto = (dia == 6 and hora_atual >= time(19, 0)) or \
             (dia in [0,1,2,3] and (hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0) or hora_atual >= time(19, 0))) or \
             (dia == 4 and time(7, 0) <= hora_atual <= time(17, 0))
    return aberto, (time(5, 0) < hora_atual < time(7, 0)) or (time(17, 0) < hora_atual < time(19, 0))

def aplicar_ordenacao(df):
    p_orig = {"QG": 1, "RMCF": 2, "OUTROS": 3}
    p_grad = {"TCEL": 1, "MAJ": 2, "CAP": 3, "1º TEN": 4, "2º TEN": 5, "SUBTEN": 6, "1º SGT": 7, "2º SGT": 8, "3º SGT": 9, "CB": 10, "SD": 11, "FC COM": 101, "FC TER": 102}
    df['dt'] = pd.to_datetime(df['DATA_HORA'], dayfirst=True, errors='coerce')
    df['p_o'] = df['QG_RMCF_OUTROS'].map(p_orig).fillna(99)
    df['p_g'] = df['GRADUAÇÃO'].map(p_grad).fillna(999)
    df = df.sort_values(by=['p_o', 'p_g', 'dt']).reset_index(drop=True)
    df.insert(0, 'Nº', [str(i+1) if i < 38 else f"Exc-{i-37:02d}" for i in range(len(df))])
    df_v = df.copy()
    for i, r in df_v.iterrows():
        if "Exc-" in str(r['Nº']):
            for c in df_v.columns: df_v.at[i, c] = f"<span style='color:#d32f2f; font-weight:bold;'>{r[c]}</span>"
    return df.drop(columns=['dt','p_o','p_g']), df_v.drop(columns=['dt','p_o','p_g'])

# ==========================================================
# INTERFACE STREAMLIT
# ==========================================================
st.set_page_config(page_title="Rota Nova Iguaçu", layout="centered")
st.markdown("""<style>
    .titulo-container { text-align: center; }
    .titulo-responsivo { font-size: 1.8rem; font-weight: bold; margin-bottom: 20px; }
    .tabela-responsiva { width: 100%; overflow-x: auto; }
    table { font-size: 11px; text-align: center; width: 100%; }
    .footer { text-align: center; font-size: 11px; color: #888; margin-top: 40px; border-top: 1px solid #eee; padding: 10px; }
</style>""", unsafe_allow_html=True)

st.markdown('<div class="titulo-container"><div class="titulo-responsivo">🚌 ROTA NOVA IGUAÇU 🚌</div></div>', unsafe_allow_html=True)

if "usuario_logado" not in st.session_state: st.session_state.usuario_logado = None
if "is_admin" not in st.session_state: st.session_state.is_admin = False
if "conf_ativa" not in st.session_state: st.session_state.conf_ativa = False

try:
    records_u = buscar_usuarios_cadastrados()
    limite_max = buscar_limite_dinamico()

    if st.session_state.usuario_logado is None and not st.session_state.is_admin:
        t1, t2, t3, t4, t5 = st.tabs(["Login", "Cadastro", "Instruções", "Recuperar", "ADM"])
        
        with t1:
            with st.form("f_login"):
                l_e = st.text_input("E-mail:")
                l_t = st.text_input("Telefone (DDD + Número):")
                l_s = st.text_input("Senha:", type="password")
                if st.form_submit_button("ENTRAR", use_container_width=True):
                    u_a = next((u for u in records_u if str(u.get('Email','')).lower() == l_e.lower() and str(u.get('Senha','')) == l_s and tel_only_digits(u.get('TELEFONE','')) == tel_only_digits(l_t)), None)
                    if u_a:
                        if str(u_a.get('STATUS','')).upper() == 'ATIVO':
                            st.session_state.usuario_logado = u_a; st.rerun()
                        else: st.error("Aguardando aprovação do Administrador.")
                    else: st.error("Dados incorretos.")

        with t2:
            if len(records_u) >= limite_max: st.warning(f"Limite de {limite_max} usuários atingido.")
            else:
                with st.form("f_cad"):
                    n_n, n_e, n_t = st.text_input("Nome Escala:"), st.text_input("E-mail:"), st.text_input("Telefone:")
                    n_g = st.selectbox("Graduação:", ["TCEL", "MAJ", "CAP", "1º TEN", "2º TEN", "SUBTEN", "1º SGT", "2º SGT", "3º SGT", "CB", "SD", "FC COM", "FC TER"])
                    n_l, n_o, n_p = st.text_input("Lotação:"), st.selectbox("Origem:", ["QG", "RMCF", "OUTROS"]), st.text_input("Senha:", type="password")
                    if st.form_submit_button("CADASTRAR", use_container_width=True):
                        if any(u.get('Email','') == n_e for u in records_u): st.error("E-mail já existe.")
                        else:
                            gs_call(ws_usuarios().append_row, [n_n, n_g, n_l, n_p, n_o, n_e, n_t, "PENDENTE"])
                            st.cache_data.clear(); st.success("Cadastrado! Aguarde aprovação."); st.rerun()

        with t3:
            st.markdown("### 📖 Guia de Uso")
            st.success("📲 **COMO INSTALAR**")
            st.markdown("* **Android:** Menu > Instalar Aplicativo.\n* **iPhone:** Compartilhar > Adicionar à Tela de Início.")
            st.markdown("**QR CODE:** https://drive.google.com/file/d/1RU1i0u1hSqdfaL3H7HUaeV4hRvR2cROf/view?usp=sharing")

        with t4:
            e_r = st.text_input("E-mail cadastrado:")
            if st.button("RECUPERAR"):
                u_r = next((u for u in records_u if str(u.get('Email','')).lower() == e_r.lower()), None)
                if u_r: st.info(f"Nome: {u_r.get('Nome')} | Senha: {u_r.get('Senha')} | Tel: {u_r.get('TELEFONE')}")

        with t5:
            with st.form("f_adm"):
                ad_u, ad_s = st.text_input("ADM:"), st.text_input("Senha:", type="password")
                if st.form_submit_button("ACESSAR ADM"):
                    if ad_u == "Administrador" and ad_s == "Administrador@123":
                        st.session_state.is_admin = True; st.rerun()

    elif st.session_state.is_admin:
        st.header("🛡️ PAINEL ADMINISTRATIVO")
        if st.button("⬅️ SAIR"): st.session_state.is_admin = False; st.rerun()
        
        limite = st.number_input("Limite de usuários:", value=limite_max)
        if st.button("SALVAR LIMITE"):
            gs_call(conectar_gsheets().open(SPREADSHEET_NAME).worksheet(WS_CONFIG).update, 'A2', [[str(limite)]])
            st.cache_data.clear(); st.success("Salvo!"); st.rerun()

        st.divider(); busca = st.text_input("🔍 Pesquisar:").strip().lower()
        
        if st.button("✅ ATIVAR TODOS E DESLOGAR"):
            if records_u:
                gs_call(ws_usuarios().update, f'H2:H{len(records_u)+1}', [["ATIVO"]] * len(records_u))
                time_module.sleep(3); st.session_state.clear(); st.cache_data.clear(); st.rerun()

        for i, u in enumerate(records_u):
            if busca == "" or busca in str(u.get('Nome','')).lower() or busca in str(u.get('Email','')).lower():
                status = str(u.get('STATUS','')).upper()
                with st.expander(f"{u.get('Nome')} - {status}"):
                    c1, c2 = st.columns([3, 1])
                    is_at = (status == 'ATIVO')
                    if c1.checkbox("Ativo", value=is_at, key=f"adm_{i}"):
                        if not is_at: gs_call(ws_usuarios().update_cell, i+2, 8, "ATIVO"); st.cache_data.clear(); st.rerun()
                    elif is_at: gs_call(ws_usuarios().update_cell, i+2, 8, "INATIVO"); st.cache_data.clear(); st.rerun()
                    if c2.button("🗑️", key=f"del_{i}"): gs_call(ws_usuarios().delete_rows, i+2); st.cache_data.clear(); st.rerun()

    else:
        u = st.session_state.usuario_logado
        st.sidebar.markdown(f"### 👤 {u.get('Graduação')} {u.get('Nome')}")
        if st.sidebar.button("Sair"): st.session_state.clear(); st.rerun()
        
        sheet_p = ws_presenca()
        dados_p = buscar_presenca_atualizada()
        dados_f = filtrar_linhas_presenca(dados_p)
        aberto, jan_conf = verificar_status_e_limpar(sheet_p, dados_f)

        df_o, df_v = pd.DataFrame(), pd.DataFrame()
        ja = False; pos = 999
        if dados_f and len(dados_f) > 1:
            df_o, df_v = aplicar_ordenacao(pd.DataFrame(dados_f[1:], columns=dados_f[0]))
            ja = any(str(u.get('Email')).lower() == str(r.get('EMAIL','')).lower() for _, r in df_o.iterrows())
            if ja: pos = df_o.index[df_o['EMAIL'].str.lower() == str(u.get('Email')).lower()].tolist()[0] + 1

        if ja:
            st.success(f"✅ Presença: {pos}º")
            if st.button("❌ EXCLUIR ASSINATURA"):
                for idx, r in enumerate(dados_p):
                    if len(r) >= 6 and str(r[5]).lower() == str(u.get('Email')).lower():
                        gs_call(sheet_p.delete_rows, idx+1); st.cache_data.clear(); st.rerun()
        elif aberto:
            if st.button("🚀 SALVAR PRESENÇA"):
                agora = datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M:%S")
                gs_call(sheet_p.append_row, [agora, u.get('QG_RMCF_OUTROS') or "QG", u.get('Graduação'), u.get('Nome'), u.get('Lotação'), u.get('Email')])
                st.cache_data.clear(); st.rerun()
        else: st.info("⌛ Lista fechada.")

        # CORREÇÃO DO ERRO NONE NA CONFERÊNCIA
        if ja and pos <= 3 and jan_conf:
            st.divider(); st.subheader("📋 CONFERÊNCIA")
            if st.button("📝 PAINEL"): st.session_state.conf_ativa = not st.session_state.conf_ativa
            if st.session_state.conf_ativa:
                container_conf = st.container()
                with container_conf:
                    for i, row in df_o.iterrows():
                        st.checkbox(f"{row['Nº']} - {row.get('NOME')}", key=f"chk_p_{i}")

        if dados_f and len(dados_f) > 1:
            insc = len(df_o); rest = 38 - insc
            st.subheader(f"Inscritos: {insc} | Vagas: 38 | {'Sobra' if rest >= 0 else 'Exc'}: {abs(rest)}")
            st.write(f'<div class="tabela-responsiva">{df_v.drop(columns=["EMAIL"]).to_html(index=False, justify="center", border=0, escape=False)}</div>', unsafe_allow_html=True)
            if st.button("🔄 ATUALIZAR"): st.cache_data.clear(); st.rerun()

    st.markdown('<div class="footer">Desenvolvido por: <b>MAJ ANDRÉ AGUIAR - CAES</b></div>', unsafe_allow_html=True)
except Exception as e: st.error(f"⚠️ Erro: {e}")

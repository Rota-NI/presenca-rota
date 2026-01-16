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
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

SPREADSHEET_NAME = "ListaPresenca"
WS_USUARIOS = "Usuarios"
WS_CONFIG = "Config"

FUSO_BR = pytz.timezone("America/Sao_Paulo")


# ==========================================================
# TELEFONE:
# ==========================================================
def tel_only_digits(s: str) -> str:
    return re.sub(r"\D+", "", str(s or ""))

def tel_format_br(digits: str) -> str:
    d = tel_only_digits(digits)
    if len(d) >= 2:
        ddd = d[:2]
        rest = d[2:]
    else:
        return d

    if len(rest) >= 9:
        p1 = rest[:5]
        p2 = rest[5:9]
        return f"({ddd}) {p1}.{p2}"
    elif len(rest) > 5:
        p1 = rest[:5]
        p2 = rest[5:]
        return f"({ddd}) {p1}.{p2}"
    else:
        return f"({ddd}) {rest}"

def tel_is_valid_11(s: str) -> bool:
    return len(tel_only_digits(s)) == 11


# ==========================================================
# WRAPPER COM RETRY
# ==========================================================
def gs_call(func, *args, **kwargs):
    max_tries = 6
    base = 0.6
    for attempt in range(max_tries):
        try:
            return func(*args, **kwargs)
        except APIError as e:
            msg = str(e)
            is_429 = ("429" in msg) or ("Quota exceeded" in msg) or ("RESOURCE_EXHAUSTED" in msg)
            if is_429:
                sleep_s = (base * (2 ** attempt)) + random.uniform(0.0, 0.35)
                time_module.sleep(min(sleep_s, 6.0))
                continue
            raise
    raise APIError("Google Sheets: muitas requisições (429).")


# ==========================================================
# CONEXÕES
# ==========================================================
@st.cache_resource
def conectar_gsheets():
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=scope)
    return gspread.authorize(creds)

@st.cache_resource
def abrir_documento():
    client = conectar_gsheets()
    return gs_call(client.open, SPREADSHEET_NAME)

@st.cache_resource
def ws_usuarios():
    doc = abrir_documento()
    return gs_call(doc.worksheet, WS_USUARIOS)

@st.cache_resource
def ws_presenca():
    doc = abrir_documento()
    return doc.sheet1

@st.cache_resource
def ws_config():
    doc = abrir_documento()
    try:
        return gs_call(doc.worksheet, WS_CONFIG)
    except Exception:
        sheet_c = gs_call(doc.add_worksheet, title=WS_CONFIG, rows="10", cols="5")
        gs_call(sheet_c.update, "A1:A2", [["LIMITE"], ["100"]])
        return sheet_c


# ==========================================================
# LEITURAS
# ==========================================================
@st.cache_data(ttl=30)
def buscar_usuarios_cadastrados():
    try:
        sheet_u = ws_usuarios()
        return gs_call(sheet_u.get_all_records)
    except Exception:
        return []

@st.cache_data(ttl=120)
def buscar_limite_dinamico():
    try:
        sheet_c = ws_config()
        val = gs_call(sheet_c.acell, "A2").value
        return int(val)
    except Exception:
        return 100

@st.cache_data(ttl=6)
def buscar_presenca_atualizada():
    try:
        sheet_p = ws_presenca()
        return gs_call(sheet_p.get_all_values)
    except Exception:
        return None

# ==========================================================
# LÓGICA DE CICLO (NOVO)
# ==========================================================
def obter_info_ciclo():
    agora = datetime.now(FUSO_BR)
    hora_atual = agora.time()
    
    # Se passou das 19:00, o ciclo é o das 06:30 de amanhã
    if hora_atual >= time(19, 0):
        data_ciclo = (agora + timedelta(days=1)).strftime("%d/%m/%Y")
        hora_ciclo = "06:30h"
    # Se está entre 07:00 e 19:00, o ciclo é o das 18:30 de hoje
    elif hora_atual >= time(7, 0):
        data_ciclo = agora.strftime("%d/%m/%Y")
        hora_ciclo = "18:30h"
    # Se é antes das 07:00 (madrugada), o ciclo é o das 06:30 de hoje
    else:
        data_ciclo = agora.strftime("%d/%m/%Y")
        hora_ciclo = "06:30h"
        
    return f"Ciclo: {data_ciclo} - {hora_ciclo}"


# ==========================================================
# FILTRO E ORDENAÇÃO (CORRIGIDO)
# ==========================================================
def filtrar_linhas_presenca(dados_p):
    if not dados_p or len(dados_p) < 2:
        return dados_p
    header = dados_p[0]
    body = [r for r in dados_p[1:] if len(r) >= 6 and r[0] and r[3] and r[5]]
    return [header] + body

def aplicar_ordenacao(df):
    if df.empty:
        return df, df

    # Prioridade de Origem
    p_orig = {"QG": 1, "RMCF": 2, "OUTROS": 3}
    
    # Prioridade de Graduação (Militares primeiro, depois Civis)
    p_grad = {
        "TCEL": 1, "MAJ": 2, "CAP": 3, "1º TEN": 4, "2º TEN": 5, "SUBTEN": 6,
        "1º SGT": 7, "2º SGT": 8, "3º SGT": 9, "CB": 10, "SD": 11,
        "FC COM": 12, "FC TER": 13
    }

    # Criar colunas auxiliares para ordenação
    df["p_o"] = df["QG_RMCF_OUTROS"].map(p_orig).fillna(99)
    df["p_g"] = df["GRADUAÇÃO"].map(p_grad).fillna(999)
    df["dt"] = pd.to_datetime(df["DATA_HORA"], dayfirst=True, errors="coerce")

    # Ordenação: 1º Origem, 2º Graduação, 3º Hora de entrada
    df = df.sort_values(by=["p_o", "p_g", "dt"]).reset_index(drop=True)
    
    # Numeração com regra de excedentes (38 vagas)
    df.insert(0, "Nº", [str(i + 1) if i < 38 else f"Exc-{i - 37:02d}" for i in range(len(df))])

    df_v = df.copy()
    for i, r in df_v.iterrows():
        if "Exc-" in str(r["Nº"]):
            for c in df_v.columns:
                df_v.at[i, c] = f"<span style='color:#d32f2f; font-weight:bold;'>{r[c]}</span>"

    return df.drop(columns=["p_o", "p_g", "dt"]), df_v.drop(columns=["p_o", "p_g", "dt"])


def verificar_status_e_limpar(sheet_p, dados_p):
    agora = datetime.now(FUSO_BR)
    hora_atual, dia_semana = agora.time(), agora.weekday()

    if hora_atual >= time(18, 50):
        marco = agora.replace(hour=18, minute=50, second=0, microsecond=0)
    elif hora_atual >= time(6, 50):
        marco = agora.replace(hour=6, minute=50, second=0, microsecond=0)
    else:
        marco = (agora - timedelta(days=1)).replace(hour=18, minute=50, second=0, microsecond=0)

    if dados_p and len(dados_p) > 1:
        try:
            ultima_str = dados_p[-1][0]
            ultima_dt = FUSO_BR.localize(datetime.strptime(ultima_str, "%d/%m/%Y %H:%M:%S"))
            if ultima_dt < marco:
                gs_call(sheet_p.resize, rows=1)
                gs_call(sheet_p.resize, rows=100)
                st.session_state["_force_refresh_presenca"] = True
                st.rerun()
        except Exception:
            pass

    is_aberto = (dia_semana == 6 and hora_atual >= time(19, 0)) or \
                (dia_semana in [0, 1, 2, 3] and (hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0) or hora_atual >= time(19, 0))) or \
                (dia_semana == 4 and time(7, 0) <= hora_atual <= time(17, 0))

    janela_conferencia = (time(5, 0) < hora_atual < time(7, 0)) or (time(17, 0) < hora_atual < time(19, 0))
    return is_aberto, janela_conferencia


# ==========================================================
# PDF
# ==========================================================
class PDFRelatorio(FPDF):
    def __init__(self, titulo="LISTA DE PRESENÇA", sub=None):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.titulo = titulo
        self.sub = sub or ""
        self.set_auto_page_break(auto=True, margin=12)
        self.alias_nb_pages()

    def header(self):
        self.set_font("Arial", "B", 14)
        self.cell(0, 8, self.titulo, ln=True, align="C")
        self.set_font("Arial", "", 9)
        if self.sub:
            self.cell(0, 5, self.sub, ln=True, align="C")
        self.ln(2)
        self.set_draw_color(180, 180, 180)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font("Arial", "", 8)
        self.cell(0, 6, f"Página {self.page_no()}/{{nb}} - Rota Nova Iguaçu", align="C")


def gerar_pdf_apresentado(df_o: pd.DataFrame, resumo: dict) -> bytes:
    agora = datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M:%S")
    sub = f"Emitido em: {agora}"
    pdf = PDFRelatorio(titulo="ROTA NOVA IGUAÇU - LISTA DE PRESENÇA", sub=sub)
    pdf.add_page()

    pdf.set_font("Arial", "B", 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 8, "RESUMO", ln=True, fill=True)

    pdf.set_font("Arial", "", 9)
    insc = resumo.get("inscritos", 0)
    vagas = resumo.get("vagas", 38)
    pdf.cell(0, 6, f"Inscritos: {insc} | Vagas: {vagas} | Excedentes: {max(0, insc-vagas)}", ln=True)
    pdf.ln(2)

    headers = ["Nº", "GRADUAÇÃO", "NOME", "LOTAÇÃO", "ORIGEM"]
    col_w = [12, 26, 78, 55, 19]

    pdf.set_font("Arial", "B", 9)
    pdf.set_fill_color(30, 30, 30)
    pdf.set_text_color(255, 255, 255)

    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 7, h, border=0, align="C", fill=True)
    pdf.ln()

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", "", 8)

    for idx, (_, r) in enumerate(df_o.iterrows()):
        is_exc = "Exc-" in str(r.get("Nº", ""))
        pdf.set_fill_color(255, 235, 238) if is_exc else pdf.set_fill_color(245, 245, 245) if idx % 2 == 0 else pdf.set_fill_color(255, 255, 255)
        
        origem = str(r.get("QG_RMCF_OUTROS", "")).strip()

        pdf.cell(col_w[0], 6, str(r.get("Nº", "")), border=0, fill=True)
        pdf.cell(col_w[1], 6, str(r.get("GRADUAÇÃO", "")), border=0, fill=True)
        pdf.cell(col_w[2], 6, str(r.get("NOME", ""))[:42], border=0, fill=True)
        pdf.cell(col_w[3], 6, str(r.get("LOTAÇÃO", ""))[:34], border=0, fill=True)
        pdf.cell(col_w[4], 6, origem[:10], border=0, align="C", fill=True)
        pdf.ln()

    return pdf.output(dest="S").encode("latin-1")


# ==========================================================
# INTERFACE STREAMLIT
# ==========================================================
st.set_page_config(page_title="Rota Nova Iguaçu", layout="centered")

st.markdown("""
<style>
    .titulo-container { text-align: center; width: 100%; }
    .titulo-responsivo { font-size: clamp(1.2rem, 5vw, 2.2rem); font-weight: bold; margin-bottom: 5px; }
    .ciclo-info { font-size: 1.1rem; color: #555; margin-bottom: 20px; font-weight: 500; }
    .tabela-responsiva { width: 100%; overflow-x: auto; }
    table { width: 100% !important; font-size: 10px; table-layout: fixed; border-collapse: collapse; }
    th, td { text-align: center; padding: 2px !important; white-space: normal !important; word-wrap: break-word; }
    .footer { text-align: center; font-size: 11px; color: #888; margin-top: 40px; padding: 10px; border-top: 1px solid #eee; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="titulo-container"><div class="titulo-responsivo">🚌 ROTA NOVA IGUAÇU 🚌</div>', unsafe_allow_html=True)
# Exibe a data e hora do ciclo atual abaixo do título
st.markdown(f'<div class="titulo-container"><div class="ciclo-info">{obter_info_ciclo()}</div></div>', unsafe_allow_html=True)

if "usuario_logado" not in st.session_state: st.session_state.usuario_logado = None
if "is_admin" not in st.session_state: st.session_state.is_admin = False
if "conf_ativa" not in st.session_state: st.session_state.conf_ativa = False
if "_force_refresh_presenca" not in st.session_state: st.session_state._force_refresh_presenca = False
if "_tel_login_fmt" not in st.session_state: st.session_state._tel_login_fmt = ""
if "_tel_cad_fmt" not in st.session_state: st.session_state._tel_cad_fmt = ""

try:
    records_u_public = buscar_usuarios_cadastrados()
    limite_max = buscar_limite_dinamico()
    sheet_u_escrita = ws_usuarios()

    if st.session_state.usuario_logado is None and not st.session_state.is_admin:
        t1, t2, t3, t4, t5 = st.tabs(["Login", "Cadastro", "Instruções", "Recuperar", "ADM"])

        with t1:
            with st.form("form_login"):
                l_e = st.text_input("E-mail:")
                raw_tel_login = st.text_input("Telefone:", value=st.session_state._tel_login_fmt)
                st.session_state._tel_login_fmt = tel_format_br(raw_tel_login)
                l_s = st.text_input("Senha:", type="password")
                if st.form_submit_button("ENTRAR", use_container_width=True):
                    tel_login_digits = tel_only_digits(st.session_state._tel_login_fmt)
                    u_a = next((u for u in records_u_public if str(u.get("Email", "")).lower() == l_e.strip().lower() 
                               and str(u.get("Senha", "")) == str(l_s) 
                               and tel_only_digits(u.get("TELEFONE", "")) == tel_login_digits), None)
                    if u_a:
                        if str(u_a.get("STATUS")).upper() == "ATIVO":
                            st.session_state.usuario_logado = u_a
                            st.rerun()
                        else: st.error("Aguardando aprovação do Administrador.")
                    else: st.error("Dados incorretos.")

        with t2:
            if len(records_u_public) >= limite_max: st.warning(f"⚠️ Limite de {limite_max} atingido.")
            else:
                with st.form("form_novo_cadastro"):
                    n_n = st.text_input("Nome de Escala:")
                    n_e = st.text_input("E-mail:")
                    raw_tel_cad = st.text_input("Telefone:", value=st.session_state._tel_cad_fmt)
                    st.session_state._tel_cad_fmt = tel_format_br(raw_tel_cad)
                    n_g = st.selectbox("Graduação:", ["TCEL", "MAJ", "CAP", "1º TEN", "2º TEN", "SUBTEN", "1º SGT", "2º SGT", "3º SGT", "CB", "SD", "FC COM", "FC TER"])
                    n_l = st.text_input("Lotação:")
                    n_o = st.selectbox("Origem:", ["QG", "RMCF", "OUTROS"])
                    n_p = st.text_input("Senha:", type="password")
                    if st.form_submit_button("FINALIZAR CADASTRO", use_container_width=True):
                        if not tel_is_valid_11(st.session_state._tel_cad_fmt): st.error("Telefone inválido.")
                        elif any(str(u.get("Email")).lower() == n_e.strip().lower() for u in records_u_public): st.error("E-mail já cadastrado.")
                        else:
                            gs_call(sheet_u_escrita.append_row, [n_n, n_g, n_l, n_p, n_o, n_e, st.session_state._tel_cad_fmt, "PENDENTE"])
                            buscar_usuarios_cadastrados.clear()
                            st.success("Cadastro realizado! Aguarde aprovação.")
                            st.rerun()
        # ... (Instruções, Recuperar e ADM permanecem com a lógica anterior)
        with t5:
            with st.form("form_admin"):
                ad_u = st.text_input("Usuário ADM:")
                ad_s = st.text_input("Senha ADM:", type="password")
                if st.form_submit_button("ACESSAR PAINEL"):
                    if ad_u == "Administrador" and ad_s == "Administrador@123":
                        st.session_state.is_admin = True
                        st.rerun()
                    else: st.error("ADM inválido.")

    elif st.session_state.is_admin:
        # Painel ADM
        st.header("🛡️ PAINEL ADMINISTRATIVO")
        if st.button("⬅️ SAIR DO PAINEL"):
            st.session_state.is_admin = False
            st.rerun()
        # (Gestão de usuários simplificada para o exemplo)
        st.write("Gerencie os usuários na planilha.")

    else:
        # USUÁRIO LOGADO
        u = st.session_state.usuario_logado
        st.sidebar.info(f"**{u.get('Graduação')} {u.get('Nome')}**")
        if st.sidebar.button("Sair"):
            st.session_state.clear()
            st.rerun()

        sheet_p_escrita = ws_presenca()
        if st.session_state._force_refresh_presenca:
            buscar_presenca_atualizada.clear()
            st.session_state._force_refresh_presenca = False

        dados_p = buscar_presenca_atualizada()
        dados_p_show = filtrar_linhas_presenca(dados_p)
        aberto, janela_conf = verificar_status_e_limpar(sheet_p_escrita, dados_p_show)

        df_o, df_v = pd.DataFrame(), pd.DataFrame()
        ja, pos = False, 999

        if dados_p_show and len(dados_p_show) > 1:
            df_temp = pd.DataFrame(dados_p_show[1:], columns=dados_p_show[0])
            df_o, df_v = aplicar_ordenacao(df_temp)
            email_logado = str(u.get("Email")).strip().lower()
            if not df_o.empty:
                filtro_u = df_o["EMAIL"].str.lower() == email_logado
                if filtro_u.any():
                    ja = True
                    pos = df_o.index[filtro_u].tolist()[0] + 1

        if ja:
            st.success(f"✅ Presença registrada: {pos}º")
            if st.button("❌ EXCLUIR MINHA ASSINATURA", use_container_width=True):
                for idx, r in enumerate(dados_p):
                    if len(r) >= 6 and str(r[5]).strip().lower() == email_logado:
                        gs_call(sheet_p_escrita.delete_rows, idx + 1)
                        buscar_presenca_atualizada.clear()
                        st.rerun()
        elif aberto:
            if st.button("🚀 SALVAR MINHA PRESENÇA", use_container_width=True):
                agora_str = datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M:%S")
                # CORREÇÃO AQUI: u.get("QG_RMCF_OUTROS") garante que pega o campo certo do cadastro
                gs_call(sheet_p_escrita.append_row, [
                    agora_str,
                    u.get("QG_RMCF_OUTROS") or "QG",
                    u.get("Graduação"),
                    u.get("Nome"),
                    u.get("Lotação"),
                    u.get("Email")
                ])
                buscar_presenca_atualizada.clear()
                st.rerun()
        else:
            st.info("⌛ Lista fechada para novas inscrições.")

        if dados_p_show and len(dados_p_show) > 1:
            st.subheader(f"Inscritos: {len(df_o)} | Vagas: 38")
            st.write(f"<div class='tabela-responsiva'>{df_v.drop(columns=['EMAIL']).to_html(index=False, justify='center', border=0, escape=False)}</div>", unsafe_allow_html=True)
            
            c1, c2 = st.columns(2)
            with c1:
                pdf_bytes = gerar_pdf_apresentado(df_o, {"inscritos": len(df_o), "vagas": 38})
                st.download_button("📄 PDF (relatório)", pdf_bytes, "lista_rota.pdf", use_container_width=True)
            with c2:
                txt_w = urllib.parse.quote(f"*🚌 LISTA ROTA - {obter_info_ciclo()}*\n\n" + "\n".join([f"{r['Nº']}. {r['GRADUAÇÃO']} {r['NOME']}" for _, r in df_o.iterrows()]))
                st.markdown(f'<a href="https://wa.me/?text={txt_w}" target="_blank"><button style="width:100%; height:38px; background-color:#25D366; color:white; border:none; border-radius:4px; font-weight:bold;">🟢 WHATSAPP</button></a>', unsafe_allow_html=True)

    st.markdown('<div class="footer">Desenvolvido por: <b>MAJ ANDRÉ AGUIAR - CAES</b></div>', unsafe_allow_html=True)

except Exception as e:
    st.error(f"⚠️ Erro: {e}")

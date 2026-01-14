import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, time, timedelta
import pytz
from fpdf import FPDF
import urllib.parse

# --- CONFIGURAÇÃO DE ACESSO ---
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

@st.cache_resource
def conectar_gsheets():
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=scope)
    return gspread.authorize(creds)

def buscar_dados_seguros():
    client = conectar_gsheets()
    doc = client.open("ListaPresenca")
    sheet_p = doc.sheet1
    sheet_u = doc.worksheet("Usuarios")
    
    dados_p = sheet_p.get_all_values()
    # Garantir que o cabeçalho existe e tem a coluna EMAIL
    if not dados_p:
        headers = ['DATA_HORA', 'QG_RMCF_OUTROS', 'GRADUAÇÃO', 'NOME', 'LOTAÇÃO', 'EMAIL']
        sheet_p.append_row(headers)
        dados_p = [headers]
    
    return sheet_p, dados_p, sheet_u.get_all_records()

def verificar_status_e_limpar(sheet_p, dados_p):
    fuso_br = pytz.timezone('America/Sao_Paulo')
    agora = datetime.now(fuso_br)
    hora_atual, dia_semana = agora.time(), agora.weekday()

    if hora_atual >= time(18, 50): marco = agora.replace(hour=18, minute=50, second=0, microsecond=0)
    elif hora_atual >= time(6, 50): marco = agora.replace(hour=6, minute=50, second=0, microsecond=0)
    else: marco = (agora - timedelta(days=1)).replace(hour=18, minute=50, second=0, microsecond=0)

    if len(dados_p) > 1:
        try:
            ultima = fuso_br.localize(datetime.strptime(dados_p[-1][0], '%d/%m/%Y %H:%M:%S'))
            if ultima < marco:
                sheet_p.resize(rows=1); sheet_p.resize(rows=100)
                st.rerun()
        except: pass
    
    return (dia_semana == 6 and hora_atual >= time(19, 0)) or \
           (dia_semana in [0, 1, 2, 3] and (hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0) or hora_atual >= time(19, 0))) or \
           (dia_semana == 4 and time(7, 0) <= hora_atual <= time(17, 0))

def aplicar_ordenacao(df):
    # Força a existência da coluna EMAIL para evitar erro ['EMAIL']
    if 'EMAIL' not in df.columns: df['EMAIL'] = "N/A"
    
    p_orig = {"QG": 1, "RMCF": 2, "OUTROS": 3}
    p_grad = {"TCEL": 1, "MAJ": 2, "CAP": 3, "1º TEN": 4, "2º TEN": 5, "SUBTEN": 6, 
              "1º SGT": 7, "2º SGT": 8, "3º SGT": 9, "CB": 10, "SD": 11, "FC COM": 101, "FC TER": 102}
    
    df['is_fc'] = df['GRADUAÇÃO'].apply(lambda x: 1 if "FC" in str(x) else 0)
    df['p_o'] = df['QG_RMCF_OUTROS'].map(p_orig).fillna(99)
    df['p_g'] = df['GRADUAÇÃO'].map(p_grad).fillna(999)
    df['dt'] = pd.to_datetime(df['DATA_HORA'], dayfirst=True, errors='coerce')
    
    df = df.sort_values(by=['is_fc', 'p_o', 'p_g', 'dt']).reset_index(drop=True)
    df.insert(0, 'Nº', [str(i+1) if i < 38 else f"Exc-{i-37:02d}" for i in range(len(df))])
    
    df_v = df.copy()
    for i, r in df_v.iterrows():
        if "Exc-" in str(r['Nº']):
            for c in df_v.columns: df_v.at[i, c] = f"<span style='color:#d32f2f; font-weight:bold;'>{r[c]}</span>"
    
    return df.drop(columns=['is_fc', 'p_o', 'p_g', 'dt']), df_v.drop(columns=['is_fc', 'p_o', 'p_g', 'dt'])

# --- INTERFACE ---
st.set_page_config(page_title="Rota Nova Iguaçu", layout="centered")
st.markdown("""<style>
    .titulo-container { text-align: center; width: 100%; }
    .titulo-responsivo { font-size: clamp(1.2rem, 5vw, 2.2rem); font-weight: bold; margin-bottom: 20px; }
    .stCheckbox { background-color: #f8f9fa; padding: 5px; border-radius: 4px; border: 1px solid #eee; }
    .footer { text-align: center; font-size: 11px; color: #888; margin-top: 40px; padding: 10px; border-top: 1px solid #eee; }
</style>""", unsafe_allow_html=True)

st.markdown('<div class="titulo-container"><div class="titulo-responsivo">🚌 ROTA NOVA IGUAÇU</div></div>', unsafe_allow_html=True)

if 'usuario_logado' not in st.session_state: st.session_state.usuario_logado = None
if 'conf_ativa' not in st.session_state: st.session_state.conf_ativa = False

try:
    sheet_p, dados_p, records_u = buscar_dados_seguros()
    
    if st.session_state.usuario_logado is None:
        t1, t2, t3 = st.tabs(["Login", "Cadastro", "Recuperar"])
        with t1:
            with st.form("f_login"):
                l_e, l_s = st.text_input("E-mail:"), st.text_input("Senha:", type="password")
                if st.form_submit_button("ENTRAR", use_container_width=True):
                    u_a = next((u for u in records_u if str(u.get('Email','')).strip().lower() == l_e.strip().lower() and str(u.get('Senha','')) == str(l_s)), None)
                    if u_a: st.session_state.usuario_logado = u_a; st.rerun()
                    else: st.error("Dados incorretos.")
        # ... abas t2 e t3 permanecem iguais ...
    else:
        u = st.session_state.usuario_logado
        st.sidebar.info(f"Conectado: {u.get('Graduação')} {u.get('Nome')}")
        if st.sidebar.button("Sair", use_container_width=True): st.session_state.usuario_logado = None; st.rerun()
        st.sidebar.markdown("---")
        st.sidebar.write("MAJ ANDRÉ AGUIAR - CAES")

        aberto = verificar_status_e_limpar(sheet_p, dados_p)
        df_o, df_v = pd.DataFrame(), pd.DataFrame()
        ja, pos = False, 999
        
        if len(dados_p) > 1:
            df_bruto = pd.DataFrame(dados_p[1:], columns=dados_p[0])
            df_o, df_v = aplicar_ordenacao(df_bruto)
            
            # Verificação de presença à prova de erros
            email_logado = str(u.get('Email')).strip().lower()
            if 'EMAIL' in df_o.columns:
                lista_emails = df_o['EMAIL'].str.strip().str.lower().tolist()
                ja = email_logado in lista_emails
                if ja:
                    pos = df_o.index[df_o['EMAIL'].str.lower() == email_logado].tolist()[0] + 1

        if aberto:
            if not ja:
                orig = u.get('ORIGEM') or u.get('QG_RMCF_OUTROS') or "QG"
                if st.button("🚀 SALVAR MINHA PRESENÇA", use_container_width=True):
                    agora = datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M:%S')
                    sheet_p.append_row([agora, orig, u.get('Graduação'), u.get('Nome'), u.get('Lotação'), u.get('Email')])
                    st.rerun()
            else:
                st.success(f"✅ Presença registrada. Posição: {pos}º")
                if st.button("❌ EXCLUIR MINHA ASSINATURA", use_container_width=True):
                    # Localiza a linha correta pelo e-mail
                    for idx, r in enumerate(dados_p):
                        if len(r) >= 6 and str(r[5]).strip().lower() == email_logado:
                            sheet_p.delete_rows(idx + 1)
                            st.rerun()
        else: st.info("⌛ Lista fechada.")

        # ... restante do código (conferência, PDF, WhatsApp) ...
        if len(dados_p) > 1:
            st.subheader(f"Presentes ({len(df_o)})")
            if st.button("🔄 ATUALIZAR LISTA"): st.rerun()
            st.write(f'<div class="tabela-responsiva">{df_v.drop(columns=["EMAIL"]).to_html(index=False, justify="center", border=0, escape=False)}</div>', unsafe_allow_html=True)

    st.markdown('<div class="footer">Desenvolvido por: <b>MAJ ANDRÉ AGUIAR - CAES</b></div>', unsafe_allow_html=True)
except Exception as e: st.error(f"⚠️ Erro Crítico: {e}. Verifique se a coluna EMAIL existe na planilha.")

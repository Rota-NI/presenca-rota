import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, time, timedelta
import pytz
from fpdf import FPDF
import urllib.parse

# --- CONFIGURAÇÃO DE ACESSO COM CACHE OTIMIZADO ---
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

@st.cache_resource
def conectar_gsheets():
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=scope)
    return gspread.authorize(creds)

@st.cache_data(ttl=20)
def buscar_dados_planilha():
    try:
        client = conectar_gsheets()
        doc = client.open("ListaPresenca")
        sheet_p = doc.sheet1
        sheet_u = doc.worksheet("Usuarios")
        return sheet_p.get_all_values(), sheet_u.get_all_records()
    except:
        return None, None

def conectar_escrita():
    client = conectar_gsheets()
    return client.open("ListaPresenca")

def verificar_status_e_limpar(sheet_p, dados_p):
    fuso_br = pytz.timezone('America/Sao_Paulo')
    agora = datetime.now(fuso_br)
    hora_atual = agora.time()
    dia_semana = agora.weekday()

    if hora_atual >= time(18, 50):
        marco_ciclo_atual = agora.replace(hour=18, minute=50, second=0, microsecond=0)
    elif hora_atual >= time(6, 50):
        marco_ciclo_atual = agora.replace(hour=6, minute=50, second=0, microsecond=0)
    else:
        ontem = agora - timedelta(days=1)
        marco_ciclo_atual = ontem.replace(hour=18, minute=50, second=0, microsecond=0)

    if dados_p and len(dados_p) > 1:
        try:
            ultima_assinatura_str = dados_p[-1][0]
            ultima_assinatura_dt = datetime.strptime(ultima_assinatura_str, '%d/%m/%Y %H:%M:%S')
            ultima_assinatura_dt = fuso_br.localize(ultima_assinatura_dt)
            if ultima_assinatura_dt < marco_ciclo_atual:
                sheet_p.resize(rows=1)
                sheet_p.resize(rows=100)
                for key in list(st.session_state.keys()):
                    if key.startswith("presenca_"): del st.session_state[key]
                st.cache_data.clear()
                st.rerun()
        except: pass

    aberto = False
    if dia_semana == 6:
        if hora_atual >= time(19, 0): aberto = True
    elif dia_semana in [0, 1, 2, 3]:
        if hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0) or hora_atual >= time(19, 0): aberto = True
    elif dia_semana == 4:
        if time(7, 0) <= hora_atual <= time(17, 0): aberto = True
    
    return aberto

def aplicar_ordenacao_e_numeracao(df):
    if 'QG_RMCF_OUT' in df.columns: df = df.rename(columns={'QG_RMCF_OUT': 'ORIGEM'})
    elif 'QG_RMCF_OUTROS' in df.columns: df = df.rename(columns={'QG_RMCF_OUTROS': 'ORIGEM'})
    peso_origem = {"QG": 1, "RMCF": 2, "OUTROS": 3}
    peso_grad = {"TCEL": 1, "MAJ": 2, "CAP": 3, "1º TEN": 4, "2º TEN": 5, "SUBTEN": 6, 
                 "1º SGT": 7, "2º SGT": 8, "3º SGT": 9, "CB": 10, "SD": 11, "FC COM": 101, "FC TER": 102}
    df['is_fc'] = df['GRADUAÇÃO'].apply(lambda x: 1 if "FC" in str(x) else 0)
    df['p_orig'] = df['ORIGEM'].map(peso_origem).fillna(99)
    df['p_grad'] = df['GRADUAÇÃO'].map(peso_grad).fillna(999)
    df['dt_temp'] = pd.to_datetime(df['DATA_HORA'], dayfirst=True)
    df = df.sort_values(by=['is_fc', 'p_orig', 'p_grad', 'dt_temp']).reset_index(drop=True)
    
    df.insert(0, 'Nº', [str(i+1) if i < 38 else f"Exc-{i-37:02d}" for i in range(len(df))])
    
    df_visual = df.copy()
    for i, row in df_visual.iterrows():
        if "Exc-" in str(row['Nº']):
            for col in df_visual.columns:
                df_visual.at[i, col] = f"<span style='color: #d32f2f; font-weight: bold;'>{row[col]}</span>"
    
    return df.drop(columns=['is_fc', 'p_orig', 'p_grad', 'dt_temp']), df_visual.drop(columns=['is_fc', 'p_orig', 'p_grad', 'dt_temp'])

# --- INTERFACE ---
st.set_page_config(page_title="Rota Nova Iguaçu", layout="centered")

st.markdown("""
    <style>
    .titulo-container { text-align: center; width: 100%; }
    .titulo-responsivo { font-size: clamp(1.2rem, 5vw, 2.2rem); font-weight: bold; margin-bottom: 20px; }
    .stCheckbox { background-color: #f8f9fa; padding: 5px; border-radius: 4px; margin-bottom: 2px; border: 1px solid #eee; }
    .tabela-responsiva { width: 100%; overflow-x: auto; display: block; }
    table { width: 100% !important; font-size: 11px; }
    th, td { white-space: nowrap; padding: 4px !important; }
    .footer { text-align: center; font-size: 11px; color: #888; margin-top: 40px; padding: 20px; border-top: 1px solid #eee; }
    </style>
    """, unsafe_allow_html=True)

st.markdown('<div class="titulo-container"><div class="titulo-responsivo">🚌 ROTA NOVA IGUAÇU</div></div>', unsafe_allow_html=True)

if 'usuario_logado' not in st.session_state:
    st.session_state.usuario_logado = None
if 'conferencia_ativa' not in st.session_state:
    st.session_state.conferencia_ativa = False

try:
    dados_p, records_u = buscar_dados_planilha()
    if dados_p is None:
        st.warning("⚠️ Sincronizando dados com o servidor... Aguarde.")
        st.stop()

    doc_escrita = conectar_escrita()
    sheet_p_escrita = doc_escrita.sheet1

    if st.session_state.usuario_logado is None:
        t1, t2, t3 = st.tabs(["Login", "Cadastro", "Esqueci a Senha"])
        with t1:
            with st.form("form_login"):
                l_n = st.text_input("Usuário (Nome de Escala):")
                l_s = st.text_input("Senha:", type="password")
                if st.form_submit_button("ENTRAR", use_container_width=True):
                    u_a = next((u for u in records_u if str(u['Nome']).strip().lower() == l_n.strip().lower() and str(u['Senha']).strip() == str(l_s).strip()), None)
                    if u_a: 
                        st.session_state.usuario_logado = u_a
                        st.rerun()
                    else: st.error("Usuário ou senha inválidos.")
    else:
        user = st.session_state.usuario_logado
        st.sidebar.info(f"Conectado: {user['Graduação']} {user['Nome']}")
        st.sidebar.markdown("---")
        st.sidebar.caption("Desenvolvido por:")
        st.sidebar.write("**MAJ ANDRÉ AGUIAR - CAES**") 
        
        if st.sidebar.button("Sair"): 
            st.session_state.usuario_logado = None
            st.rerun()
        
        aberto = verificar_status_e_limpar(sheet_p_escrita, dados_p)
        df_original, df_visual = pd.DataFrame(), pd.DataFrame()
        ja, posicao_usuario = False, 999
        
        if len(dados_p) > 1:
            df_original, df_visual = aplicar_ordenacao_e_numeracao(pd.DataFrame(dados_p[1:], columns=dados_p[0]))
            ja = any(user['Nome'] == r[3] for r in dados_p[1:])
            if ja:
                try: posicao_usuario = df_original.index[df_original['NOME'] == user['Nome']].tolist()[0] + 1
                except: pass

        if aberto:
            if not ja:
                orig_user = user.get('ORIGEM') or user.get('QG_RMCF_OUTROS') or "QG"
                if st.button("🚀 SALVAR MINHA PRESENÇA", use_container_width=True):
                    agora_str = datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M:%S')
                    sheet_p_escrita.append_row([agora_str, orig_user, user['Graduação'], user['Nome'], user['Lotação']])
                    st.cache_data.clear()
                    st.rerun()
            else: st.warning(f"✅ Presença registrada. Posição: {posicao_usuario}º")
        else: st.info("⌛ Lista fechada.")

        if ja and posicao_usuario <= 2:
            st.divider()
            st.subheader("📋 LISTA DE PRESENÇA")
            if st.button("📝 ABRIR / FECHAR CONFERÊNCIA", use_container_width=True):
                st.session_state.conferencia_ativa = not st.session_state.conferencia_ativa
            
            if st.session_state.conferencia_ativa:
                for i, row in df_original.iterrows():
                    key_p = f"presenca_{i}_{row['NOME']}"
                    if key_p not in st.session_state: st.session_state[key_p] = False
                    st.checkbox(f"{row['Nº']} - {row['GRADUAÇÃO']} {row['NOME']}", key=key_p)
            st.divider()

        if len(dados_p) > 1:
            st.subheader(f"Presentes ({len(df_original)})")
            if st.button("🔄 ATUALIZAR LISTA", use_container_width=True): 
                st.cache_data.clear()
                st.rerun()
            
            html_tab = f'<div class="tabela-responsiva">{df_visual.to_html(index=False, justify="center", border=0, escape=False)}</div>'
            st.write(html_tab, unsafe_allow_html=True)
            
            col_pdf, col_wpp = st.columns(2)
            with col_pdf:
                pdf = FPDF()
                pdf.add_page(); pdf.set_font("Arial", "B", 14)
                pdf.cell(190, 10, "LISTA DE PRESENÇA - ROTA NOVA IGUAÇU", ln=True, align="C")
                pdf.set_font("Arial", "B", 8)
                w = [12, 30, 20, 25, 63, 40]
                headers = ["Nº", "DATA_HORA", "ORIGEM", "GRADUAÇÃO", "NOME", "LOTAÇÃO"]
                for i, h in enumerate(headers): pdf.cell(w[i], 8, h, border=1, align="C")
                pdf.ln(); pdf.set_font("Arial", "", 8)
                for _, r in df_original.iterrows():
                    for i in range(len(headers)): pdf.cell(w[i], 8, str(r[i]), border=1)
                    pdf.ln()
                st.download_button("📄 PDF", pdf.output(dest="S").encode("latin-1"), "lista.pdf", "application/pdf", use_container_width=True)
            
            with col_wpp:
                texto_wpp = f"*🚌 LISTA DE PRESENÇA*\n\n"
                for _, r in df_original.iterrows(): texto_wpp += f"{r['Nº']}. {r['GRADUAÇÃO']} {r['NOME']}\n"
                st.markdown(f'<a href="https://wa.me/?text={urllib.parse.quote(texto_wpp)}" target="_blank"><button style="width:100%; height:38px; background-color:#25D366; color:white; border:none; border-radius:4px; font-weight:bold;">🟢 WHATSAPP</button></a>', unsafe_allow_html=True)

            if ja and st.button("❌ EXCLUIR MINHA ASSINATURA", use_container_width=True):
                for idx, r in enumerate(dados_p):
                    if r[3] == user['Nome']: 
                        sheet_p_escrita.delete_rows(idx + 1)
                        st.cache_data.clear(); st.rerun()

    st.markdown('<div class="footer">Desenvolvido por: <b>MAJ ANDRÉ AGUIAR - CAES</b></div>', unsafe_allow_html=True)

except Exception as e:
    st.error(f"Erro de conexão. Aguarde 10 segundos. Detalhe: {e}")

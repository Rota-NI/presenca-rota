import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, time, timedelta
import pytz
from fpdf import FPDF
import urllib.parse

# --- CONFIGURAÇÃO DE ACESSO COM CACHE PARA EVITAR ERRO 429 ---
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

@st.cache_resource
def conectar_gsheets():
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=scope)
    return gspread.authorize(creds)

@st.cache_data(ttl=10) # Cache de 10 segundos para poupar a cota da API
def buscar_dados_planilha():
    client = conectar_gsheets()
    doc = client.open("ListaPresenca")
    sheet_p = doc.sheet1
    sheet_u = doc.worksheet("Usuarios")
    return sheet_p.get_all_values(), sheet_u.get_all_records()

def conectar_escrita():
    # Para operações de escrita, não usamos cache
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

    if len(dados_p) > 1:
        try:
            ultima_assinatura_str = dados_p[-1][0]
            ultima_assinatura_dt = datetime.strptime(ultima_assinatura_str, '%d/%m/%Y %H:%M:%S')
            ultima_assinatura_dt = fuso_br.localize(ultima_assinatura_dt)
            if ultima_assinatura_dt < marco_ciclo_atual:
                sheet_p.resize(rows=1)
                sheet_p.resize(rows=100)
                st.cache_data.clear()
                st.rerun()
        except: pass

    aberto = False
    if dia_semana == 6: # Domingo
        if hora_atual >= time(19, 0): aberto = True
    elif dia_semana in [0, 1, 2, 3]: # Seg-Qui
        if hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0) or hora_atual >= time(19, 0): aberto = True
    elif dia_semana == 4: # Sex
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
    return df.drop(columns=['is_fc', 'p_orig', 'p_grad', 'dt_temp'])

# --- INTERFACE ---
st.set_page_config(page_title="Rota Nova Iguaçu", layout="centered")

st.markdown("""
    <style>
    .titulo-container { text-align: center; width: 100%; }
    .titulo-responsivo { font-size: clamp(1.5rem, 5vw, 2.5rem); font-weight: bold; margin-bottom: 20px; }
    .stCheckbox { background-color: #f0f2f6; padding: 8px; border-radius: 5px; margin-bottom: 2px; border: 1px solid #d1d1d1; }
    </style>
    """, unsafe_allow_html=True)

st.markdown('<div class="titulo-container"><div class="titulo-responsivo">🚌 ROTA NOVA IGUAÇU</div></div>', unsafe_allow_html=True)

if 'usuario_logado' not in st.session_state:
    st.session_state.usuario_logado = None
if 'conferencia_ativa' not in st.session_state:
    st.session_state.conferencia_ativa = False

try:
    dados_p, records_u = buscar_dados_planilha()
    doc_escrita = conectar_escrita()
    sheet_p_escrita = doc_escrita.sheet1
    sheet_u_escrita = doc_escrita.worksheet("Usuarios")

    if st.session_state.usuario_logado is None:
        t1, t2, t3 = st.tabs(["Login", "Cadastro", "Esqueci a Senha"])
        with t1:
            l_n = st.text_input("Usuário (Nome de Escala):")
            l_s = st.text_input("Senha:", type="password")
            if st.button("Entrar", use_container_width=True):
                u_a = next((u for u in records_u if str(u['Nome']).strip() == l_n.strip() and str(u['Senha']).strip() == str(l_s).strip()), None)
                if u_a: 
                    st.session_state.usuario_logado = u_a
                    st.rerun()
                else: st.error("Usuário ou senha inválidos.")
        with t2:
            with st.form("cad"):
                n_n = st.text_input("Nome de Escala:")
                n_e = st.text_input("E-mail para recuperação:")
                n_g = st.selectbox("Graduação:", ["TCEL", "MAJ", "CAP", "1º TEN", "2º TEN", "SUBTEN", "1º SGT", "2º SGT", "3º SGT", "CB", "SD", "FC COM", "FC TER"])
                n_u = st.text_input("Lotação:")
                n_d = st.selectbox("Origem Padrão:", ["QG", "RMCF", "OUTROS"])
                n_s = st.text_input("Crie uma Senha:", type="password")
                if st.form_submit_button("Finalizar Cadastro", use_container_width=True):
                    sheet_u_escrita.append_row([n_n, n_g, n_u, n_s, n_d, n_e])
                    st.cache_data.clear()
                    st.success("Cadastro realizado!")
        with t3:
            e_r = st.text_input("Digite o e-mail cadastrado:")
            if st.button("Visualizar Dados", use_container_width=True):
                u_r = next((u for u in records_u if str(u.get('Email', '')).strip().lower() == e_r.strip().lower()), None)
                if u_r: st.info(f"Usuário: {u_r['Nome']} | Senha: {u_r['Senha']}")
                else: st.error("E-mail não encontrado.")
    else:
        user = st.session_state.usuario_logado
        st.sidebar.info(f"Conectado: {user['Graduação']} {user['Nome']}")
        if st.sidebar.button("Sair"): 
            st.session_state.usuario_logado = None
            st.rerun()
        
        aberto = verificar_status_e_limpar(sheet_p_escrita, dados_p)
        df = pd.DataFrame()
        
        ja = False
        posicao_usuario = 999
        if len(dados_p) > 1:
            df = aplicar_ordenacao_e_numeracao(pd.DataFrame(dados_p[1:], columns=dados_p[0]))
            ja = any(user['Nome'] == r[3] for r in dados_p[1:])
            if ja:
                try:
                    posicao_usuario = df.index[df['NOME'] == user['Nome']].tolist()[0] + 1
                except: pass

        if aberto:
            if not ja:
                orig_user = user.get('ORIGEM') or user.get('QG_RMCF_OUTROS') or "QG"
                if st.button("🚀 SALVAR MINHA PRESENÇA", use_container_width=True):
                    agora_str = datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M:%S')
                    sheet_p_escrita.append_row([agora_str, orig_user, user['Graduação'], user['Nome'], user['Lotação']])
                    st.cache_data.clear()
                    st.rerun()
            else:
                st.warning(f"✅ Presença registrada. Sua posição atual: {posicao_usuario}º")

        # --- FUNCIONALIDADE: LISTA DE PRESENÇA (CONFERÊNCIA) ---
        if ja and posicao_usuario <= 2:
            st.divider()
            st.subheader("📋 LISTA DE PRESENÇA")
            if st.button("📝 ABRIR DIÁRIO DE BORDO / CONFERÊNCIA", use_container_width=True):
                st.session_state.conferencia_ativa = not st.session_state.conferencia_ativa
            
            if st.session_state.conferencia_ativa:
                st.info("Marque os passageiros conforme entrarem no ônibus:")
                # Usamos um formulário para evitar que a página recarregue a cada clique no checkbox
                with st.form("form_conferencia"):
                    for index, row in df.iterrows():
                        # CHAVE ÚNICA ROBUSTA: Nº + Nome + Index para evitar conflitos de elementos iguais
                        key_conf = f"chk_{row['Nº']}_{row['NOME']}_{index}"
                        st.checkbox(f"{row['Nº']} - {row['GRADUAÇÃO']} {row['NOME']}", key=key_conf)
                    st.form_submit_button("Salvar Conferência Local")
                
                if st.button("Fechar Painel de Conferência"):
                    st.session_state.conferencia_ativa = False
                    st.rerun()
            st.divider()

        if len(dados_p) > 1:
            st.subheader(f"Pessoas Presentes ({len(df)})")
            if st.button("🔄 ATUALIZAR LISTA", use_container_width=True): 
                st.cache_data.clear()
                st.rerun()
            
            html_tabela = f'<div class="tabela-responsiva">{df.to_html(index=False, justify="center", border=0)}</div>'
            st.write(html_tabela, unsafe_allow_html=True)
            
            col_pdf, col_wpp = st.columns(2)
            with col_pdf:
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", "B", 14)
                pdf.cell(190, 10, "LISTA DE PRESENÇA - ROTA NOVA IGUAÇU", ln=True, align="C")
                pdf.set_font("Arial", "B", 8)
                w = [12, 30, 20, 25, 63, 40]
                headers = ["Nº", "DATA_HORA", "ORIGEM", "GRADUAÇÃO", "NOME", "LOTAÇÃO"]
                for i, h in enumerate(headers): pdf.cell(w[i], 8, h, border=1, align="C")
                pdf.ln()
                pdf.set_font("Arial", "", 8)
                for _, r in df.iterrows():
                    for i in range(len(headers)): pdf.cell(w[i], 8, str(r[i]), border=1)
                    pdf.ln()
                st.download_button("📄 BAIXAR PDF", pdf.output(dest="S").encode("latin-1"), f"lista.pdf", "application/pdf", use_container_width=True)
            
            with col_wpp:
                agora_f = datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%d/%m/%Y às %H:%M')
                texto_wpp = f"*🚌 LISTA DE PRESENÇA - ROTA NOVA IGUAÇU*\n_Atualizada em {agora_f}_\n\n"
                for _, r in df.iterrows(): texto_wpp += f"{r['Nº']}. {r['GRADUAÇÃO']} {r['NOME']} ({r['LOTAÇÃO']})\n"
                link_wpp = f"https://wa.me/?text={urllib.parse.quote(texto_wpp)}"
                st.markdown(f'<a href="{link_wpp}" target="_blank"><button style="width:100%; height:38px; background-color:#25D366; color:white; border:none; border-radius:4px; cursor:pointer; font-weight:bold; width:100%;">🟢 WHATSAPP</button></a>', unsafe_allow_html=True)

            if ja and st.button("❌ EXCLUIR MINHA ASSINATURA", use_container_width=True):
                for idx, r in enumerate(dados_p):
                    if r[3] == user['Nome']: 
                        sheet_p_escrita.delete_rows(idx + 1)
                        st.cache_data.clear()
                        st.rerun()

except Exception as e: 
    if "429" in str(e):
        st.error("⚠️ Muitas requisições ao Google. O sistema vai aguardar 10 segundos e atualizar sozinho.")
    else:
        st.error(f"Erro: {e}")

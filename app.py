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

def conectar():
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=scope)
    client = gspread.authorize(creds)
    return client.open("ListaPresenca")

def verificar_status_e_limpar(sheet_p):
    fuso_br = pytz.timezone('America/Sao_Paulo')
    agora = datetime.now(fuso_br)
    hora_atual = agora.time()
    dia_semana = agora.weekday()

    # 1. DEFINIR O MARCO INICIAL DO CICLO ATUAL
    # Se agora é depois das 18:50, o ciclo começou às 18:50 de hoje.
    if hora_atual >= time(18, 50):
        marco_ciclo_atual = agora.replace(hour=18, minute=50, second=0, microsecond=0)
    # Se agora é depois das 06:50 (mas antes das 18:50), o ciclo começou às 06:50 de hoje.
    elif hora_atual >= time(6, 50):
        marco_ciclo_atual = agora.replace(hour=6, minute=50, second=0, microsecond=0)
    # Se agora é madrugada (antes das 06:50), o ciclo começou às 18:50 de ONTEM.
    else:
        ontem = agora - timedelta(days=1)
        marco_ciclo_atual = ontem.replace(hour=18, minute=50, second=0, microsecond=0)

    # 2. VERIFICAR SE O BANCO PRECISA DE LIMPEZA
    dados = sheet_p.get_all_values()
    if len(dados) > 1: # Tem assinaturas
        try:
            # Pega a data/hora da última assinatura registrada (última linha, coluna 0)
            ultima_assinatura_str = dados[-1][0]
            ultima_assinatura_dt = datetime.strptime(ultima_assinatura_str, '%d/%m/%Y %H:%M:%S')
            ultima_assinatura_dt = fuso_br.localize(ultima_assinatura_dt)

            # Se a última assinatura aconteceu ANTES do marco do ciclo atual, limpa a lista.
            if ultima_assinatura_dt < marco_ciclo_atual:
                sheet_p.resize(rows=1)
                sheet_p.resize(rows=100)
                st.rerun()
        except Exception as e:
            pass # Em caso de erro de conversão, ignora para não travar o app

    # 3. VERIFICAR SE O BOTÃO DEVE ESTAR ABERTO
    aberto = False
    if dia_semana == 6: # Domingo
        if hora_atual >= time(19, 0): aberto = True
    elif dia_semana in [0, 1, 2, 3]: # Segunda a Quinta
        if hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0) or hora_atual >= time(19, 0): aberto = True
    elif dia_semana == 4: # Sexta
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
    .titulo-responsivo { font-size: clamp(1.5rem, 5vw, 2.5rem); font-weight: bold; margin-bottom: 20px; white-space: nowrap; }
    .tabela-responsiva { width: 100%; overflow-x: auto; display: block; }
    table { width: 100% !important; font-size: 12px; }
    th, td { white-space: nowrap; padding: 5px !important; }
    </style>
    """, unsafe_allow_html=True)

st.markdown('<div class="titulo-container"><div class="titulo-responsivo">🚌 ROTA NOVA IGUAÇU</div></div>', unsafe_allow_html=True)

if 'usuario_logado' not in st.session_state:
    st.session_state.usuario_logado = None

try:
    doc = conectar()
    sheet_p, sheet_u = doc.sheet1, doc.worksheet("Usuarios")

    if st.session_state.usuario_logado is None:
        t1, t2, t3 = st.tabs(["Login", "Cadastro", "Esqueci a Senha"])
        with t1:
            l_n = st.text_input("Usuário (Nome de Escala):")
            l_s = st.text_input("Senha:", type="password")
            if st.button("Entrar", use_container_width=True):
                users = sheet_u.get_all_records()
                u_a = next((u for u in users if str(u['Nome']).strip() == l_n.strip() and str(u['Senha']).strip() == str(l_s).strip()), None)
                if u_a: 
                    st.session_state.usuario_logado = u_a
                    st.rerun()
                else: st.error("Usuário ou senha inválidos.")
        with t2:
            with st.form("cad"):
                n_n, n_e = st.text_input("Nome de Escala:"), st.text_input("E-mail para recuperação:")
                n_g = st.selectbox("Graduação:", ["TCEL", "MAJ", "CAP", "1º TEN", "2º TEN", "SUBTEN", "1º SGT", "2º SGT", "3º SGT", "CB", "SD", "FC COM", "FC TER"])
                n_u, n_d = st.text_input("Lotação:"), st.selectbox("Origem Padrão:", ["QG", "RMCF", "OUTROS"])
                n_s = st.text_input("Crie uma Senha:", type="password")
                if st.form_submit_button("Finalizar Cadastro", use_container_width=True):
                    sheet_u.append_row([n_n, n_g, n_u, n_s, n_d, n_e])
                    st.success("Cadastro realizado!")
        with t3:
            e_r = st.text_input("Digite o e-mail cadastrado:")
            if st.button("Visualizar Dados", use_container_width=True):
                users = sheet_u.get_all_records()
                u_r = next((u for u in users if str(u.get('Email', '')).strip().lower() == e_r.strip().lower()), None)
                if u_r: st.info(f"Usuário: {u_r['Nome']} | Senha: {u_r['Senha']}")
                else: st.error("E-mail não encontrado.")
    else:
        user = st.session_state.usuario_logado
        st.sidebar.info(f"Conectado: {user['Graduação']} {user['Nome']}")
        if st.sidebar.button("Sair"): 
            st.session_state.usuario_logado = None
            st.rerun()
        
        # Chama a função que verifica limpeza e status de abertura
        aberto = verificar_status_e_limpar(sheet_p)
        
        dados_p = sheet_p.get_all_values()
        ja = any(user['Nome'] == r[3] for r in dados_p[1:]) if len(dados_p) > 1 else False
        
        if aberto:
            if not ja:
                orig_user = user.get('ORIGEM') or user.get('QG_RMCF_OUTROS') or user.get('QG_RMCF_OUT') or "QG"
                if st.button("🚀 SALVAR MINHA PRESENÇA", use_container_width=True):
                    agora_str = datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M:%S')
                    sheet_p.append_row([agora_str, orig_user, user['Graduação'], user['Nome'], user['Lotação']])
                    st.success("Presença registrada!"); st.rerun()
            else: st.warning("✅ Presença registrada.")
        else: st.info("⌛ A lista de presença encontra-se fechada no momento.")
        
        if len(dados_p) > 1:
            df = aplicar_ordenacao_e_numeracao(pd.DataFrame(dados_p[1:], columns=dados_p[0]))
            st.subheader(f"Pessoas Presentes ({len(df)})")
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
                st.download_button("📄 BAIXAR PDF", pdf.output(dest="S").encode("latin-1"), f"lista_{datetime.now().strftime('%Hh%M')}.pdf", "application/pdf", use_container_width=True)
            
            with col_wpp:
                agora_f = datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%d/%m/%Y às %H:%M')
                texto_wpp = f"*🚌 LISTA DE PRESENÇA - ROTA NOVA IGUAÇU*\n_Atualizada em {agora_f}_\n\n"
                for _, r in df.iterrows(): texto_wpp += f"{r['Nº']}. {r['GRADUAÇÃO']} {r['NOME']} ({r['LOTAÇÃO']})\n"
                link_wpp = f"https://wa.me/?text={urllib.parse.quote(texto_wpp)}"
                st.markdown(f'<a href="{link_wpp}" target="_blank"><button style="width:100%; height:38px; background-color:#25D366; color:white; border:none; border-radius:4px; cursor:pointer; font-weight:bold;">🟢 ENVIAR WHATSAPP</button></a>', unsafe_allow_html=True)

            if ja and st.button("❌ EXCLUIR MINHA ASSINATURA", use_container_width=True):
                for idx, r in enumerate(dados_p):
                    if r[3] == user['Nome']: sheet_p.delete_rows(idx + 1); st.rerun()

except Exception as e: st.error(f"Erro: {e}")

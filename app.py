import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, time
import pytz

# --- CONFIGURAÇÃO DE ACESSO ---
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

def conectar():
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=scope)
    client = gspread.authorize(creds)
    return client.open("ListaPresenca")

def verificar_status():
    fuso_br = pytz.timezone('America/Sao_Paulo')
    agora = datetime.now(fuso_br)
    dia_semana, hora_atual = agora.weekday(), agora.time()
    deve_limpar = (time(6, 50) <= hora_atual <= time(6, 59)) or (time(18, 50) <= hora_atual <= time(18, 59))
    
    aberto = False
    if dia_semana == 6 and hora_atual >= time(19, 0): aberto = True # Domingo
    elif dia_semana in [0, 1, 2, 3]: # Seg-Qui
        if hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0) or hora_atual >= time(19, 0): aberto = True
    elif dia_semana == 4: # Sex
        if hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0): aberto = True
    elif dia_semana == 5 and hora_atual <= time(5, 0): aberto = True # Sáb
    
    return aberto, deve_limpar

def aplicar_ordenacao_e_numeracao(df):
    # PADRONIZAÇÃO DA COLUNA DE DESTINO
    # Se a coluna na planilha estiver cortada, o código renomeia internamente para garantir a ordem
    if 'QG_RMCF_OUT' in df.columns:
        df = df.rename(columns={'QG_RMCF_OUT': 'QG_RMCF_OUTROS'})
    
    # Pesos para Ordenação
    peso_destino = {"QG": 1, "RMCF": 2, "OUTROS": 3}
    peso_grad = {"TCEL": 1, "MAJ": 2, "CAP": 3, "1º TEN": 4, "2º TEN": 5, "SUBTEN": 6, "1º SGT": 7, "2º SGT": 8, "3º SGT": 9, "CB": 10, "SD": 11, "FC COM": 101, "FC TER": 102}
    
    # Criando colunas temporárias para ordenar
    df['is_fc'] = df['GRADUAÇÃO'].apply(lambda x: 1 if "FC" in str(x) else 0)
    df['p_dest'] = df['QG_RMCF_OUTROS'].map(peso_destino).fillna(99)
    df['p_grad'] = df['GRADUAÇÃO'].map(peso_grad).fillna(999)
    df['dt_temp'] = pd.to_datetime(df['DATA_HORA'], dayfirst=True)
    
    # Ordenação: 1º Militares vs FC, 2º Destino (QG>RMCF), 3º Antiguidade, 4º Horário
    df = df.sort_values(by=['is_fc', 'p_dest', 'p_grad', 'dt_temp']).reset_index(drop=True)
    
    # Numeração de poltronas (1 a 37 e Excedentes)
    df.insert(0, 'Nº', [str(i+1) if i < 38 else f"Exc-{i-37:02d}" for i in range(len(df))])
    
    return df.drop(columns=['is_fc', 'p_dest', 'p_grad', 'dt_temp'])

# --- INTERFACE ---
st.markdown("<h1 style='text-align: center;'>🚌 ROTA NOVA IGUAÇU</h1>", unsafe_allow_html=True)

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
            if st.button("Entrar"):
                users = sheet_u.get_all_records()
                u_a = next((u for u in users if str(u['Nome']).strip() == l_n.strip() and str(u['Senha']).strip() == str(l_s).strip()), None)
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
                n_d = st.selectbox("Destino Padrão:", ["QG", "RMCF", "OUTROS"])
                n_s = st.text_input("Crie uma Senha:", type="password")
                if st.form_submit_button("Finalizar Cadastro"):
                    sheet_u.append_row([n_n, n_g, n_u, n_s, n_d, n_e])
                    st.success("Cadastro realizado! Faça o login.")
        
        with t3:
            st.write("Valide seu e-mail para recuperar seus dados.")
            e_r = st.text_input("Digite o e-mail cadastrado:")
            if st.button("Visualizar Dados"):
                users = sheet_u.get_all_records()
                u_r = next((u for u in users if str(u.get('Email', '')).strip().lower() == e_r.strip().lower()), None)
                if u_r:
                    st.success("Dados encontrados!")
                    st.info(f"**Usuário:** {u_r['Nome']} | **Senha:** {u_r['Senha']}")
                else: st.error("E-mail não encontrado.")

    else:
        u = st.session_state.usuario_logado
        st.sidebar.info(f"Conectado: {u['Graduação']} {u['Nome']}")
        if st.sidebar.button("Sair"): 
            st.session_state.usuario_logado = None
            st.rerun()
        
        aberto, limpar = verificar_status()
        
        # Limpeza de ciclo
        if limpar and len(sheet_p.get_all_values()) > 1: 
            sheet_p.resize(rows=1)
            sheet_p.resize(rows=100)
        
        dados_p = sheet_p.get_all_values()
        ja = any(u['Nome'] == r[3] for r in dados_p[1:]) if len(dados_p) > 1 else False
        
        if aberto:
            if not ja:
                # Pega o destino do cadastro (flexível caso a coluna mude o nome)
                dest_user = u.get('QG_RMCF_OUTROS') or u.get('QG_RMCF_OUT') or "QG"
                st.write(f"**Confirmar Presença:** {u['Graduação']} {u['Nome']} | **Destino:** {dest_user}")
                if st.button("🚀 SALVAR MINHA PRESENÇA"):
                    agora = datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M:%S')
                    sheet_p.append_row([agora, dest_user, u['Graduação'], u['Nome'], u['Lotação']])
                    st.success("Presença registrada!")
                    st.rerun()
            else: 
                st.warning("✅ Sua presença já está garantida neste turno.")
        else: 
            st.info("🕒 O sistema está fechado para assinaturas no momento.")

        # Exibição da Lista Ordenada
        if len(dados_p) > 1:
            df = aplicar_ordenacao_e_numeracao(pd.DataFrame(dados_p[1:], columns=dados_p[0]))
            st.subheader(f"Pessoas Presentes ({len(df)})")
            st.table(df)
            
            if ja and st.button("❌ EXCLUIR MINHA ASSINATURA"):
                for idx, r in enumerate(dados_p):
                    if r[3] == u['Nome']: 
                        sheet_p.delete_rows(idx + 1)
                        st.rerun()
        else: st.subheader("Pessoas Presentes (0)")

except Exception as e: st.error(f"Erro no sistema: {e}")

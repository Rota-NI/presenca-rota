import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, time
import pytz
from fpdf import FPDF

# --- CONFIGURAÇÃO DE ACESSO ---
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

def conectar():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    client = gspread.authorize(creds)
    return client.open("ListaPresenca")

def verificar_status():
    fuso_br = pytz.timezone('America/Sao_Paulo')
    agora = datetime.now(fuso_br)
    dia_semana = agora.weekday()
    hora_atual = agora.time()
    deve_limpar = (time(6, 50) <= hora_atual <= time(6, 59)) or (time(18, 50) <= hora_atual <= time(18, 59))
    aberto = False
    if dia_semana == 6:
        if hora_atual >= time(19, 0): aberto = True
    elif dia_semana in [0, 1, 2, 3]:
        if hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0) or hora_atual >= time(19, 0): aberto = True
    elif dia_semana == 4:
        if hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0): aberto = True
    elif dia_semana == 5:
        if hora_atual <= time(5, 0): aberto = True
    return aberto, deve_limpar

def aplicar_ordenacao_e_numeracao(df):
    peso_destino = {"QG": 1, "RMCF": 2, "OUTROS": 3}
    peso_grad = {"TCEL": 1, "MAJ": 2, "CAP": 3, "1º TEN": 4, "2º TEN": 5, "SUBTEN": 6, "1º SGT": 7, "2º SGT": 8, "3º SGT": 9, "CB": 10, "SD": 11, "FC COM": 101, "FC TER": 102}
    col_destino, col_grad, col_data = "QG_RMCF_OUTROS", "GRADUAÇÃO", "DATA_HORA"
    df['is_fc'] = df[col_grad].apply(lambda x: 1 if "FC" in str(x) else 0)
    df['p_dest'] = df.apply(lambda r: peso_destino.get(r[col_destino], 99) if r['is_fc'] == 0 else 99, axis=1)
    df['p_grad'] = df[col_grad].map(peso_grad).fillna(999)
    df['dt_temp'] = pd.to_datetime(df[col_data], dayfirst=True)
    df = df.sort_values(by=['is_fc', 'p_dest', 'p_grad', 'dt_temp']).reset_index(drop=True)
    def formatar_posicao(i):
        pos = i + 1
        return str(pos) if pos <= 38 else f"Exc-{pos-38:02d}"
    df.insert(0, 'Nº', [formatar_posicao(i) for i in range(len(df))])
    return df.drop(columns=['is_fc', 'p_dest', 'p_grad', 'dt_temp'])

# --- INTERFACE PRINCIPAL ---
st.markdown("<h1 style='text-align: center;'>🚌 ROTA NOVA IGUAÇU</h1>", unsafe_allow_html=True)

if 'usuario_logado' not in st.session_state:
    st.session_state.usuario_logado = None

try:
    doc = conectar()
    sheet_p = doc.sheet1
    sheet_u = doc.worksheet("Usuarios")

    if st.session_state.usuario_logado is None:
        tab_login, tab_cad = st.tabs(["Login", "Cadastro"])
        
        with tab_login:
            login_nome = st.text_input("Nome de Escala (Login):")
            login_senha = st.text_input("Senha:", type="password")
            if st.button("Entrar"):
                users = sheet_u.get_all_records()
                user_auth = next((u for u in users if str(u['Nome']) == login_nome and str(u['Senha']) == str(login_senha)), None)
                if user_auth:
                    st.session_state.usuario_logado = user_auth
                    st.rerun()
                else:
                    st.error("Usuário ou senha incorretos.")

        with tab_cad:
            with st.form("cad_form"):
                n_nome = st.text_input("Nome de Escala:")
                n_grad = st.selectbox("Graduação:", ["TCEL", "MAJ", "CAP", "1º TEN", "2º TEN", "SUBTEN", "1º SGT", "2º SGT", "3º SGT", "CB", "SD", "FC COM", "FC TER"])
                n_unid = st.text_input("Lotação (Unidade):")
                # NOVO CAMPO NO CADASTRO CONFORME SOLICITADO
                n_dest_padrao = st.selectbox("Destino Padrão:", ["QG", "RMCF", "OUTROS"])
                n_senha = st.text_input("Crie uma Senha:", type="password")
                if st.form_submit_button("Cadastrar"):
                    sheet_u.append_row([n_nome, n_grad, n_unid, n_senha, n_dest_padrao])
                    st.success("Cadastro realizado com sucesso!")

    else:
        user = st.session_state.usuario_logado
        st.sidebar.write(f"Conectado: **{user['Graduação']} {user['Nome']}**")
        if st.sidebar.button("Sair"):
            st.session_state.usuario_logado = None
            st.rerun()

        st.caption("Obs. 1: Preencher lista com Posto/Graduação, Nome de escala e lotação.")
        st.caption("Obs. 2: Ordem de prioridade (38 vagas): QG > RMCF > OUTROS > FC.")

        aberto, limpar = verificar_status()
        if limpar and len(sheet_p.get_all_values()) > 1:
            sheet_p.resize(rows=1)
            sheet_p.resize(rows=100)

        # Verificar se o usuário já assinou neste ciclo
        dados_p = sheet_p.get_all_values()
        ja_assinou = False
        if len(dados_p) > 1:
            df_atual = pd.DataFrame(dados_p[1:], columns=dados_p[0])
            if user['Nome'] in df_atual['NOME'].values:
                ja_assinou = True

        if aberto:
            if not ja_assinou:
                with st.form("form_presenca"):
                    # Carrega o destino padrão cadastrado pelo usuário
                    idx_dest = ["QG", "RMCF", "OUTROS"].index(user['QG_RMCF_OUTROS'])
                    dest = st.selectbox("Confirmar Destino:", ["QG", "RMCF", "OUTROS"], index=idx_dest)
                    st.info(f"Confirmar dados: {user['Graduação']} {user['Nome']} - {user['Lotação']}")
                    if st.form_submit_button("SALVAR MINHA PRESENÇA"):
                        agora = datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M:%S')
                        sheet_p.append_row([agora, dest, user['Graduação'], user['Nome'], user['Lotação']])
                        st.success("Presença registrada!")
                        st.rerun()
            else:
                st.warning("✅ Você já registrou sua presença neste ciclo.")
        else:
            st.info("🕒 Sistema fechado para registros.")

        # --- EXIBIÇÃO ---
        if len(dados_p) > 1:
            df_sorted = aplicar_ordenacao_e_numeracao(pd.DataFrame(dados_p[1:], columns=dados_p[0]))
            st.subheader(f"Pessoas Presentes ({len(df_sorted)})")
            st.table(df_sorted)

            if ja_assinou:
                if st.button("❌ EXCLUIR MINHA ASSINATURA"):
                    for idx, linha in enumerate(dados_p):
                        if linha[3] == user['Nome']:
                            sheet_p.delete_rows(idx + 1)
                            st.success("Registro removido.")
                            st.rerun()
        else:
            st.subheader("Pessoas Presentes (0)")

except Exception as e:
    st.error(f"Erro no sistema: {e}")

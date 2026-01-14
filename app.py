import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, time
import pytz
import smtplib
from email.mime.text import MIMEText
from fpdf import FPDF

# --- ACESSO E CONEXÃO ---
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

def conectar():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    client = gspread.authorize(creds)
    return client.open("ListaPresenca")

def enviar_email_recuperacao(destinatario, usuario, senha):
    try:
        # Puxa os dados salvos nos Secrets do Streamlit
        remetente = st.secrets["email_user"]
        senha_app = st.secrets["email_password"]
        
        corpo = f"Olá,\n\nSeus dados de acesso à Rota Nova Iguaçu são:\n\nUsuário: {usuario}\nSenha: {senha}\n\nUtilize estes dados para realizar o seu login."
        msg = MIMEText(corpo)
        msg['Subject'] = 'Recuperação de Acesso - Rota Nova Iguaçu'
        msg['From'] = remetente
        msg['To'] = destinatario
        
        # Conexão segura com o servidor do Gmail
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls() # Inicia criptografia
        server.login(remetente, senha_app)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        # Mostra o erro real apenas para o administrador nos logs se necessário
        return False

# --- LOGICA DE STATUS E ORDENAÇÃO (Mantida conforme solicitado anteriormente) ---
def verificar_status():
    fuso_br = pytz.timezone('America/Sao_Paulo')
    agora = datetime.now(fuso_br)
    dia_semana, hora_atual = agora.weekday(), agora.time()
    deve_limpar = (time(6, 50) <= hora_atual <= time(6, 59)) or (time(18, 50) <= hora_atual <= time(18, 59))
    aberto = False
    if dia_semana == 6 and hora_atual >= time(19, 0): aberto = True
    elif dia_semana in [0, 1, 2, 3]:
        if hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0) or hora_atual >= time(19, 0): aberto = True
    elif dia_semana == 4:
        if hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0): aberto = True
    elif dia_semana == 5 and hora_atual <= time(5, 0): aberto = True
    return aberto, deve_limpar

def aplicar_ordenacao_e_numeracao(df):
    peso_destino = {"QG": 1, "RMCF": 2, "OUTROS": 3}
    peso_grad = {"TCEL": 1, "MAJ": 2, "CAP": 3, "1º TEN": 4, "2º TEN": 5, "SUBTEN": 6, "1º SGT": 7, "2º SGT": 8, "3º SGT": 9, "CB": 10, "SD": 11, "FC COM": 101, "FC TER": 102}
    df['is_fc'] = df['GRADUAÇÃO'].apply(lambda x: 1 if "FC" in str(x) else 0)
    # Busca flexível pela coluna de destino
    col_dest = "QG_RMCF_OUTROS" if "QG_RMCF_OUTROS" in df.columns else "QG_RMCF_OUT"
    df['p_dest'] = df.apply(lambda r: peso_destino.get(r[col_dest], 99) if r['is_fc'] == 0 else 99, axis=1)
    df['p_grad'] = df['GRADUAÇÃO'].map(peso_grad).fillna(999)
    df['dt_temp'] = pd.to_datetime(df['DATA_HORA'], dayfirst=True)
    df = df.sort_values(by=['is_fc', 'p_dest', 'p_grad', 'dt_temp']).reset_index(drop=True)
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
                if u_a: st.session_state.usuario_logado = u_a; st.rerun()
                else: st.error("Usuário ou senha inválidos.")
        with t2:
            with st.form("cad"):
                n_n, n_e = st.text_input("Nome de Escala:"), st.text_input("E-mail:")
                n_g = st.selectbox("Graduação:", ["TCEL", "MAJ", "CAP", "1º TEN", "2º TEN", "SUBTEN", "1º SGT", "2º SGT", "3º SGT", "CB", "SD", "FC COM", "FC TER"])
                n_u, n_d = st.text_input("Lotação:"), st.selectbox("Destino Padrão:", ["QG", "RMCF", "OUTROS"])
                n_s = st.text_input("Crie uma Senha:", type="password")
                if st.form_submit_button("Cadastrar"):
                    sheet_u.append_row([n_n, n_g, n_u, n_s, n_d, n_e]); st.success("Cadastrado! Faça Login.")
        with t3:
            e_r = st.text_input("Digite o e-mail cadastrado para recuperar:")
            if st.button("Recuperar Dados"):
                users = sheet_u.get_all_records()
                u_r = next((u for u in users if str(u.get('Email', '')).strip().lower() == e_r.strip().lower()), None)
                if u_r:
                    if enviar_email_recuperacao(e_r, u_r.get('Nome'), u_r.get('Senha')):
                        st.success(f"Dados enviados com sucesso para {e_r}!")
                    else: st.error("Erro técnico ao enviar o e-mail. Verifique os Secrets.")
                else: st.error("E-mail não encontrado na nossa base de usuários.")
    else:
        # Interface do Usuário Logado (Mantida Conforme as regras anteriores)
        user = st.session_state.usuario_logado
        st.sidebar.info(f"Logado: {user['Graduação']} {user['Nome']}")
        if st.sidebar.button("Sair"): st.session_state.usuario_logado = None; st.rerun()
        
        aberto, limpar = verificar_status()
        if limpar and len(sheet_p.get_all_values()) > 1: sheet_p.resize(rows=1); sheet_p.resize(rows=100)
        
        dados_p = sheet_p.get_all_values()
        ja = any(user['Nome'] == r[3] for r in dados_p[1:]) if len(dados_p) > 1 else False
        
        if aberto:
            if not ja:
                # Usa o destino padrão do cadastro
                dest_user = user.get('QG_RMCF_OUTROS') or user.get('QG_RMCF_OUT') or "QG"
                st.info(f"Dados: {user['Graduação']} {user['Nome']} | Destino: {dest_user}")
                if st.button("🚀 SALVAR MINHA PRESENÇA"):
                    agora = datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M:%S')
                    sheet_p.append_row([agora, dest_user, user['Graduação'], user['Nome'], user['Lotação']])
                    st.success("Presença salva!"); st.rerun()
            else: st.warning("✅ Presença já registrada para este turno.")
        else: st.info("🕒 Sistema fechado para registros.")

        if len(dados_p) > 1:
            df = aplicar_ordenacao_e_numeracao(pd.DataFrame(dados_p[1:], columns=dados_p[0]))
            st.subheader(f"Pessoas Presentes ({len(df)})"); st.table(df)
            if ja and st.button("❌ EXCLUIR MINHA ASSINATURA"):
                for idx, r in enumerate(dados_p):
                    if r[3] == user['Nome']: sheet_p.delete_rows(idx + 1); st.rerun()
        else: st.subheader("Pessoas Presentes (0)")
except Exception as e: st.error(f"Erro: {e}")

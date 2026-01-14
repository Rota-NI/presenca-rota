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
    return client.open("ListaPresenca").sheet1

# --- LÓGICA DE HORÁRIO E LIMPEZA AUTOMÁTICA ---
def verificar_status():
    fuso_br = pytz.timezone('America/Sao_Paulo')
    agora = datetime.now(fuso_br)
    dia_semana = agora.weekday()
    hora_atual = agora.time()

    # Janelas de limpeza (10 min antes do início dos turnos: 06:50 e 18:50)
    deve_limpar = (time(6, 50) <= hora_atual <= time(6, 59)) or (time(18, 50) <= hora_atual <= time(18, 59))

    aberto = False
    if dia_semana == 6: # Dom
        if hora_atual >= time(19, 0): aberto = True
    elif dia_semana in [0, 1, 2, 3]: # Seg-Qui
        if hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0) or hora_atual >= time(19, 0): aberto = True
    elif dia_semana == 4: # Sex
        if hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0): aberto = True
    elif dia_semana == 5: # Sab
        if hora_atual <= time(5, 0): aberto = True

    return aberto, deve_limpar

# --- FUNÇÃO DE ORDENAÇÃO CONFORME DETERMINADO ---
def aplicar_ordenacao(df):
    # Definindo pesos para Destino
    peso_destino = {"QG": 10, "RMCF": 20, "OUTROS": 30}
    
    # Definindo pesos para Graduação (Militares 1-11, FCs 100+)
    peso_grad = {
        "TCEL": 1, "MAJ": 2, "CAP": 3, "1º TEN": 4, "2º TEN": 5, "SUBTEN": 6,
        "1º SGT": 7, "2º SGT": 8, "3º SGT": 9, "CB": 10, "SD": 11,
        "FC COM": 101, "FC TER": 102
    }

    # Ajuste para o nome exato da sua coluna na planilha
    col_destino = "QG_RMCF_OUTROS" 
    
    df['p_dest'] = df[col_destino].map(peso_destino).fillna(99)
    df['p_grad'] = df['GRADUAÇÃO'].map(peso_grad).fillna(999)
    df['dt_temp'] = pd.to_datetime(df['DATA_HORA'], dayfirst=True)

    # Ordena por Destino, depois pela categoria (Militar vs FC), depois Patente e Hora
    df = df.sort_values(by=['p_dest', 'p_grad', 'dt_temp']).reset_index(drop=True)
    return df.drop(columns=['p_dest', 'p_grad', 'dt_temp'])

# --- INTERFACE ---
st.markdown("<h1 style='text-align: center;'>🚌 ROTA NOVA IGUAÇU</h1>", unsafe_allow_html=True)

try:
    sheet = conectar()
    aberto, limpar = verificar_status()

    if limpar:
        if len(sheet.get_all_values()) > 1:
            sheet.resize(rows=1)
            sheet.resize(rows=100)
            st.warning("🧹 Limpando lista para o próximo turno...")

    if aberto:
        with st.form("form_rota", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                dest = st.selectbox("Destino:", ["QG", "RMCF", "OUTROS"])
                grad = st.selectbox("Graduação:", ["TCEL", "MAJ", "CAP", "1º TEN", "2º TEN", "SUBTEN", "1º SGT", "2º SGT", "3º SGT", "CB", "SD", "FC COM", "FC TER"])
            with c2:
                nome = st.text_input("Nome de Escala:")
                unid = st.text_input("Lotação (Unidade):")
            
            if st.form_submit_button("SALVAR PRESENÇA"):
                if nome and unid:
                    agora = datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M:%S')
                    sheet.append_row([agora, dest, grad, nome, unid])
                    st.success("Presença registrada!")
                    st.rerun()
    else:
        st.info("🕒 Sistema fechado para novos registros. Apenas consulta e PDF disponíveis.")

    # --- TABELA E PDF ---
    dados = sheet.get_all_values()
    if len(dados) > 1:
        df = pd.DataFrame(dados[1:], columns=dados[0])
        df_sorted = aplicar_ordenacao(df)
        st.subheader("Pessoas Presentes")
        st.table(df_sorted)

        # Gerar PDF com os dados ordenados
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", "B", 14)
        pdf.cell(190, 10, "LISTA DE PRESENÇA - ROTA NOVA IGUAÇU", ln=True, align="C")
        pdf.set_font("Arial", "B", 8)
        w = [35, 25, 25, 65, 40]
        for i, h in enumerate(df_sorted.columns): pdf.cell(w[i], 8, h, border=1, align="C")
        pdf.ln()
        pdf.set_font("Arial", "", 8)
        for _, r in df_sorted.iterrows():
            for i in range(5): pdf.cell(w[i], 8, str(r[i]), border=1)
            pdf.ln()
        
        st.download_button("📄 BAIXAR LISTA EM PDF", pdf.output(dest="S").encode("latin-1"), "lista.pdf", "application/pdf")

except Exception as e:
    st.error(f"Erro: {e}")

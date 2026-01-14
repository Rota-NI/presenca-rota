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

# --- LÓGICA DE HORÁRIO ---
def verificar_acesso():
    fuso_br = pytz.timezone('America/Sao_Paulo')
    agora = datetime.now(fuso_br)
    dia_semana = agora.weekday() # 0=Segunda, 6=Domingo
    hora_atual = agora.time()

    aberto = False

    # Domingo (6): Abre às 19:00 e vai até meia-noite
    if dia_semana == 6:
        if hora_atual >= time(19, 0):
            aberto = True
    
    # Segunda (0), Terça (1), Quarta (2), Quinta (3)
    elif dia_semana in [0, 1, 2, 3]:
        # Madrugada do dia anterior (até 05:00) OU 07:00 às 17:00 OU 19:00 em diante
        if hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0) or hora_atual >= time(19, 0):
            aberto = True

    # Sexta (4)
    elif dia_semana == 4:
        # Madrugada de quinta (até 05:00) OU 07:00 às 17:00
        if hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0):
            aberto = True
            
    # Sábado (5)
    elif dia_semana == 5:
        # Madrugada de sexta (até 05:00)
        if hora_atual <= time(5, 0):
            aberto = True

    return aberto

# --- FUNÇÃO PARA GERAR PDF ---
def gerar_pdf(df):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(190, 10, "LISTA DE PRESENÇA - ROTA NOVA IGUAÇU", ln=True, align="C")
    pdf.ln(10)
    
    pdf.set_font("Arial", "B", 10)
    col_widths = [40, 25, 25, 60, 40]
    headers = ["DATA/HORA", "DESTINO", "GRAD.", "NOME", "LOTAÇÃO"]
    
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 10, header, border=1, align="C")
    pdf.ln()
    
    pdf.set_font("Arial", "", 9)
    for index, row in df.iterrows():
        for i in range(len(headers)):
            pdf.cell(col_widths[i], 10, str(row[i]), border=1)
        pdf.ln()
        
    return pdf.output(dest="S").encode("latin-1")

# --- INTERFACE ---
st.markdown("<h1 style='text-align: center;'>🚌 ROTA NOVA IGUAÇU</h1>", unsafe_allow_html=True)

try:
    if verificar_acesso():
        sheet = conectar()
        
        with st.form("meu_formulario", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                qg_opcoes = st.selectbox("Destino:", ["QG", "RMCF", "OUTROS"])
                graduacao = st.selectbox("Graduação:", [
                    "TCEL", "MAJ", "CAP", "1º TEN", "2º TEN", 
                    "SUBTEN", "1º SGT", "2º SGT", "3º SGT", "CB", "SD", "FC COM", "FC TER"
                ])
            with col2:
                nome = st.text_input("Nome de Escala:")
                lotacao = st.text_input("Lotação (Unidade):")
                
            submit = st.form_submit_button("SALVAR PRESENÇA")
            
            if submit:
                if nome and lotacao:
                    fuso_br = pytz.timezone('America/Sao_Paulo')
                    agora_str = datetime.now(fuso_br).strftime('%d/%m/%Y %H:%M:%S')
                    sheet.append_row([agora_str, qg_opcoes, graduacao, nome, lotacao])
                    st.success(f"Presença de {nome} registrada!")
                    st.rerun()
                else:
                    st.error("Por favor, preencha o Nome e a Lotação.")
    else:
        st.warning("⚠️ O sistema está fora do horário de funcionamento.")
        st.info("Horários: Dom 19h às Seg 05h | Seg-Qui: 07h-17h e 19h-05h | Sex: 07h-17h")

    # --- TABELA E PDF (Sempre disponíveis para consulta) ---
    st.subheader("Pessoas Presentes")
    sheet_consulta = conectar()
    dados = sheet_consulta.get_all_values()
    
    if len(dados) > 1:
        df = pd.DataFrame(dados[1:], columns=dados[0])
        st.table(df)
        
        pdf_data = gerar_pdf(df)
        st.download_button(
            label="📄 BAIXAR LISTA EM PDF",
            data=pdf_data,
            file_name=f"presenca_rota_{datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf"
        )
    else:
        st.info("Nenhuma presença registrada ainda.")

except Exception as e:
    st.error(f"Erro de conexão ou configuração: {e}")

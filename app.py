import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime
from fpdf import FPDF

# --- CONFIGURAÇÃO DE ACESSO ---
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

def conectar():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    client = gspread.authorize(creds)
    return client.open("ListaPresenca").sheet1

# --- FUNÇÃO PARA GERAR PDF ---
def gerar_pdf(df):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(190, 10, "LISTA DE PRESENÇA - ROTA NOVA IGUAÇU", ln=True, align="C")
    pdf.ln(10)
    
    # Cabeçalhos
    pdf.set_font("Arial", "B", 10)
    col_widths = [40, 25, 25, 60, 40]
    headers = ["DATA/HORA", "DESTINO", "GRAD.", "NOME", "LOTAÇÃO"]
    
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 10, header, border=1, align="C")
    pdf.ln()
    
    # Dados
    pdf.set_font("Arial", "", 9)
    for index, row in df.iterrows():
        pdf.cell(col_widths[0], 10, str(row[0]), border=1)
        pdf.cell(col_widths[1], 10, str(row[1]), border=1)
        pdf.cell(col_widths[2], 10, str(row[2]), border=1)
        pdf.cell(col_widths[3], 10, str(row[3]), border=1)
        pdf.cell(col_widths[4], 10, str(row[4]), border=1)
        pdf.ln()
        
    return pdf.output(dest="S").encode("latin-1")

# --- TÍTULO ---
st.markdown("<h1 style='text-align: center;'>🚌 ROTA NOVA IGUAÇU</h1>", unsafe_allow_html=True)

try:
    sheet = conectar()
    
    # --- FORMULÁRIO ---
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
                agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                sheet.append_row([agora, qg_opcoes, graduacao, nome, lotacao])
                st.success(f"Presença de {nome} registrada!")
                st.rerun()
            else:
                st.error("Por favor, preencha o Nome e a Lotação.")

    # --- MOSTRAR TABELA E BOTÃO PDF ---
    st.subheader("Pessoas Presentes")
    dados = sheet.get_all_values()
    if len(dados) > 1:
        df = pd.DataFrame(dados[1:], columns=dados[0])
        st.table(df)
        
        # Botão para baixar PDF
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
    st.error(f"Erro: {e}")

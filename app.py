import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime
from fpdf import FPDF

# --- CONFIGURAÇÃO DE ACESSO ---
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

# O Streamlit vai ler as credenciais de um lugar seguro chamado "Secrets"
try:
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open("ListaPresenca")
    sheet = spreadsheet.sheet1
except Exception:
    st.error("Aguardando configuração das chaves de acesso...")

# --- TÍTULO DA PÁGINA ---
st.markdown("<h1 style='text-align: center;'>🚌 ROTA NOVA IGUAÇU</h1>", unsafe_allow_html=True)

# --- FORMULÁRIO ---
with st.form("meu_formulario", clear_on_submit=True):
    nome = st.text_input("Nome de Escala:")
    submit = st.form_submit_button("SALVAR PRESENÇA")
    
    if submit:
        if nome:
            agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            sheet.append_row([agora, nome])
            st.success(f"Presença de {nome} registrada!")
        else:
            st.error("Digite seu nome.")

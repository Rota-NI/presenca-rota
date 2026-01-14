import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime

# --- CONFIGURAÇÃO DE ACESSO ---
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

# Função para conectar
def conectar():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    client = gspread.authorize(creds)
    return client.open("ListaPresenca").sheet1

# --- TÍTULO ---
st.title("🚌 ROTA NOVA IGUAÇU")

try:
    sheet = conectar()
    
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

except Exception as e:
    st.error(f"Erro de conexão: {e}")
    st.info("Verifique se você compartilhou a planilha com o e-mail da conta de serviço.")

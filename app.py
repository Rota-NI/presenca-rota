import streamlit as st
import gspread
from gspread.exceptions import APIError
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, time, timedelta
import pytz
from fpdf import FPDF
import urllib.parse
import time as time_module
import random

# ==========================================================
# CONFIGURAÇÃO DE ACESSO
# ==========================================================
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

SPREADSHEET_NAME = "ListaPresenca"
WS_USUARIOS = "Usuarios"
WS_CONFIG = "Config"

FUSO_BR = pytz.timezone("America/Sao_Paulo")


# ==========================================================
# WRAPPER COM RETRY / BACKOFF PARA 429
# ==========================================================
def gs_call(func, *args, **kwargs):
    """
    Executa chamadas gspread com retry exponencial para erros 429/5xx.
    Evita quebrar o app em momentos de pico de quota.
    """
    max_tries = 6
    base = 0.6
    for attempt in range(max_tries):
        try:
            return func(*args, **kwargs)
        except APIError as e:
            msg = str(e)
            # gspread normalmente inclui código na mensagem
            is_429 = ("429" in msg) or ("Quota exceeded" in msg) or ("RESOURCE_EXHAUSTED" in msg)
            is_5xx = any(code in msg for code in ["500", "502", "503", "504"])
            if is_429 or is_5xx:
                # backoff exponencial + jitter
                sleep_s = (base * (2 ** attempt)) + random.uniform(0.0, 0.35)
                time_module.sleep(min(sleep_s, 6.0))
                continue
            raise
    # Se estourou tentativas:
    raise APIError("Google Sheets: muitas requisições (429). Tente novamente em instantes.")


# ==========================================================
# CONEXÕES (CACHE_RESOURCE) - não reautentica toda hora
# ==========================================================
@st.cache_resource
def conectar_gsheets():
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=scope)
    return gspread.authorize(creds)


@st.cache_resource
def abrir_documento():
    client = conectar_gsheets()
    return gs_call(client.open, SPREADSHEET_NAME)


@st.cache_resource
def ws_usuarios():
    doc = abrir_documento()
    return gs_call(doc.worksheet, WS_USUARIOS)


@st.cache_resource
def ws_presenca():
    doc = abrir_documento()
    # sheet1
    return doc.sheet1


@st.cache_resource
def ws_config():
    doc = abrir_documento()
    try:
        return gs_call(doc.worksheet, WS_CONFIG)
    except Exception:
        # cria uma vez e deixa cacheado como resource
        sheet_c = gs_call(doc.add_worksheet, title=WS_CONFIG, rows="10", cols="5")
        gs_call(sheet_c.update, "A1:A2", [["LIMITE"], ["100"]])
        return sheet_c


# ==========================================================
# LEITURAS (CACHE_DATA) - TTL MAIOR + "manual refresh"
# ==========================================================
@st.cache_data(ttl=30)
def buscar_usuarios_cadastrados():
    try:
        sheet_u = ws_usuarios()
        return gs_call(sheet_u.get_all_records)
    except Exception:
        return []


@st.cache_data(ttl=120)
def buscar_limite_dinamico():
    try:
        sheet_c = ws_config()
        val = gs_call(sheet_c.acell, "A2").value
        return int(val)
    except Exception:
        return 100


@st.cache_data(ttl=6)
def buscar_presenca_atualizada():
    try:
        sheet_p = ws_presenca()
        return gs_call(sheet_p.get_all_values)
    except Exception:
        return None


def verificar_status_e_limpar(sheet_p, dados_p):
    agora = datetime.now(FUSO_BR)
    hora_atual, dia_semana = agora.time(), agora.weekday()

    if hora_atual >= time(18, 50):
        marco = agora.replace(hour=18, minute=50, second=0, microsecond=0)
    elif hora_atual >= time(6, 50):
        marco = agora.replace(hour=6, minute=50, second=0, microsecond=0)
    else:
        marco = (agora - timedelta(days=1)).replace(hour=18, minute=50, second=0, microsecond=0)

    # Limpeza: só faz se conseguir ler a última data
    if dados_p and len(dados_p) > 1:
        try:
            ultima_str = dados_p[-1][0]
            ultima_dt = FUSO_BR.localize(datetime.strptime(ultima_str, "%d/%m/%Y %H:%M:%S"))
            if ultima_dt < marco:
                # IMPORTANTE: isso é operação pesada, mas acontece no máximo 2x por dia
                gs_call(sheet_p.resize, rows=1)
                gs_call(sheet_p.resize, rows=100)
                # NÃO limpar cache global agressivamente aqui
                st.session_state["_force_refresh_presenca"] = True
                st.rerun()
        except Exception:
            pass

    is_aberto = (dia_semana == 6 and hora_atual >= time(19, 0)) or \
                (dia_semana in [0, 1, 2, 3] and (hora_atual <= time(5, 0) or time(7, 0) <= hora_atual <= time(17, 0) or hora_atual >= time(19, 0))) or \
                (dia_semana == 4 and time(7, 0) <= hora_atual <= time(17, 0))

    janela_conferencia = (time(5, 0) < hora_atual < time(7, 0)) or (time(17, 0) < hora_atual < time(19, 0))
    return is_aberto, janela_conferencia


def aplicar_ordenacao(df):
    if "EMAIL" not in df.columns:
        df["EMAIL"] = "N/A"

    p_orig = {"QG": 1, "RMCF": 2, "OUTROS": 3}
    p_grad = {
        "TCEL": 1, "MAJ": 2, "CAP": 3, "1º TEN": 4, "2º TEN": 5, "SUBTEN": 6,
        "1º SGT": 7, "2º SGT": 8, "3º SGT": 9, "CB": 10, "SD": 11,
        "FC COM": 101, "FC TER": 102
    }

    df["is_fc"] = df["GRADUAÇÃO"].apply(lambda x: 1 if "FC" in str(x) else 0)
    df["p_o"] = df["QG_RMCF_OUTROS"].map(p_orig).fillna(99)
    df["p_g"] = df["GRADUAÇÃO"].map(p_grad).fillna(999)
    df["dt"] = pd.to_datetime(df["DATA_HORA"], dayfirst=True, errors="coerce")

    df = df.sort_values(by=["is_fc", "p_o", "p_g", "dt"]).reset_index(drop=True)
    df.insert(0, "Nº", [str(i + 1) if i < 38 else f"Exc-{i - 37:02d}" for i in range(len(df))])

    df_v = df.copy()
    for i, r in df_v.iterrows():
        if "Exc-" in str(r["Nº"]):
            for c in df_v.columns:
                df_v.at[i, c] = f"<span style='color:#d32f2f; font-weight:bold;'>{r[c]}</span>"

    return df.drop(columns=["is_fc", "p_o", "p_g", "dt"]), df_v.drop(columns=["is_fc", "p_o", "p_g", "dt"])


# ==========================================================
# INTERFACE
# ==========================================================
st.set_page_config(page_title="Rota Nova Iguaçu", layout="centered")
st.markdown('<script src="https://telegram.org/js/telegram-web-app.js"></script>', unsafe_allow_html=True)

st.markdown("""
<style>
    .titulo-container { text-align: center; width: 100%; }
    .titulo-responsivo { font-size: clamp(1.2rem, 5vw, 2.2rem); font-weight: bold; margin-bottom: 20px; }
    .stCheckbox { background-color: #f8f9fa; padding: 5px; border-radius: 4px; border: 1px solid #eee; }
    .tabela-responsiva { width: 100%; overflow-x: auto; }
    table { width: 100% !important; font-size: 10px; table-layout: fixed; border-collapse: collapse; }
    th, td { text-align: center; padding: 2px !important; white-space: normal !important; word-wrap: break-word; }
    .footer { text-align: center; font-size: 11px; color: #888; margin-top: 40px; padding: 10px; border-top: 1px solid #eee; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="titulo-container"><div class="titulo-responsivo">🚌 ROTA NOVA IGUAÇU 🚌</div></div>', unsafe_allow_html=True)

if "usuario_logado" not in st.session_state:
    st.session_state.usuario_logado = None
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
if "conf_ativa" not in st.session_state:
    st.session_state.conf_ativa = False
if "_force_refresh_presenca" not in st.session_state:
    st.session_state._force_refresh_presenca = False

try:
    # ==========================================================
    # IMPORTANTE: Não ler presença aqui.
    # Só carrega usuários/limite (mais leve) antes do login.
    # ==========================================================
    records_u = buscar_usuarios_cadastrados()
    limite_max = buscar_limite_dinamico()

    # Sheets de escrita: mantém via cache_resource (não reabre)
    sheet_u_escrita = ws_usuarios()

    # ==========================================================
    # LOGIN / CADASTRO / INSTRUÇÕES / RECUPERAR / ADM
    # ==========================================================
    if st.session_state.usuario_logado is None and not st.session_state.is_admin:
        t1, t2, t3, t4, t5 = st.tabs(["Login", "Cadastro", "Instruções", "Recuperar", "ADM"])

        with t1:
            with st.form("form_login"):
                l_e = st.text_input("E-mail:")
                l_t = st.text_input("Telefone:")
                l_s = st.text_input("Senha:", type="password")
                if st.form_submit_button("ENTRAR", use_container_width=True):
                    u_a = next(
                        (u for u in records_u
                         if str(u.get("Email", "")).strip().lower() == l_e.strip().lower()
                         and str(u.get("Senha", "")) == str(l_s)
                         and str(u.get("TELEFONE", "")).strip() == l_t.strip()),
                        None
                    )
                    if u_a:
                        status_user = str(u_a.get("STATUS", "")).strip().upper()
                        if status_user == "ATIVO":
                            st.session_state.usuario_logado = u_a
                            st.rerun()
                        else:
                            st.error("Acesso negado. Aguardando aprovação do Administrador.")
                    else:
                        st.error("Dados incorretos.")

        with t2:
            if len(records_u) >= limite_max:
                st.warning(f"⚠️ Limite de {limite_max} usuários atingido.")
            else:
                with st.form("form_novo_cadastro"):
                    n_n = st.text_input("Nome de Escala:")
                    n_e = st.text_input("E-mail:")
                    n_t = st.text_input("Telefone:")
                    n_g = st.selectbox("Graduação:", ["TCEL", "MAJ", "CAP", "1º TEN", "2º TEN", "SUBTEN", "1º SGT",
                                                      "2º SGT", "3º SGT", "CB", "SD", "FC COM", "FC TER"])
                    n_l = st.text_input("Lotação:")
                    n_o = st.selectbox("Origem:", ["QG", "RMCF", "OUTROS"])
                    n_p = st.text_input("Senha:", type="password")

                    if st.form_submit_button("FINALIZAR CADASTRO", use_container_width=True):
                        if any(str(u.get("Email", "")).strip().lower() == n_e.strip().lower() for u in records_u):
                            st.error("E-mail já cadastrado.")
                        else:
                            gs_call(sheet_u_escrita.append_row, [n_n, n_g, n_l, n_p, n_o, n_e, n_t, "PENDENTE"])
                            # em vez de limpar cache global, apenas rerun e deixar TTL cuidar
                            st.success("Cadastro realizado! Aguardando aprovação do Administrador.")
                            st.rerun()

        with t3:
            st.markdown("### 📖 Guia de Uso")
            st.success("📲 **COMO INSTALAR (TELA INICIAL)**")
            st.markdown("**No Chrome (Android):** Toque nos 3 pontos (⋮) e em 'Instalar Aplicativo'.")
            st.markdown("**No Safari (iPhone):** Toque em Compartilhar (⬆️) e em 'Adicionar à Tela de Início'.")
            st.markdown("**No Telegram:** Procure o bot `@RotaNovaIguacuBot` e toque no botão 'Abrir App Rota' no menu.")
            st.markdown("**QR CODE:** https://drive.google.com/file/d/1RU1i0u1hSqdfaL3H7HUaeV4hRvR2cROf/view?usp=sharing")
            st.markdown("**LINK PARA NAVEGADOR:** https://presenca-rota-gbiwh9bjrwdergzc473xyg.streamlit.app/")
            st.divider()
            st.info("**CADASTRO E LOGIN:** Use seu e-mail como identificador único.")
            st.markdown("""
            **1. Regras de Horário:**
            * **Manhã:** Inscrições abertas até às 05:00h. Reabre às 07:00h.
            * **Tarde:** Inscrições abertas até às 17:00h. Reabre às 19:00h.
            * **Finais de Semana:** Abrem domingo às 19:00h.

            **2. Observação:**
            * Nos períodos em que a lista ficar suspensa para conferência (05:00h às 07:00h / 17:00h às 19:00h),
              os três PPMM que estiverem no topo da lista terão acesso à lista de check up (botão no topo da lista) para
              tirar a falta de quem estará entrando no ônibus.
            * Após o horário de 06:50h e de 18:50h, a lista será automaticamente zerada.
            """)

        with t4:
            e_r = st.text_input("E-mail cadastrado:")
            if st.button("RECUPERAR DADOS", use_container_width=True):
                u_r = next((u for u in records_u if str(u.get("Email", "")).strip().lower() == e_r.strip().lower()), None)
                if u_r:
                    st.info(f"Usuário: {u_r.get('Nome')} | Senha: {u_r.get('Senha')} | Tel: {u_r.get('TELEFONE')}")
                else:
                    st.error("E-mail não encontrado.")

        with t5:
            with st.form("form_admin"):
                ad_u = st.text_input("Usuário ADM:")
                ad_s = st.text_input("Senha ADM:", type="password")
                if st.form_submit_button("ACESSAR PAINEL"):
                    if ad_u == "Administrador" and ad_s == "Administrador@123":
                        st.session_state.is_admin = True
                        st.rerun()
                    else:
                        st.error("ADM inválido.")

    # ==========================================================
    # PAINEL ADM
    # ==========================================================
    elif st.session_state.is_admin:
        st.header("🛡️ PAINEL ADMINISTRATIVO")
        if st.button("⬅️ SAIR DO PAINEL"):
            st.session_state.is_admin = False
            st.rerun()

        st.subheader("⚙️ Configurações Globais")
        novo_limite = st.number_input("Limite máximo de usuários:", value=int(limite_max))
        if st.button("💾 SALVAR NOVO LIMITE"):
            sheet_c = ws_config()
            gs_call(sheet_c.update, "A2", [[str(novo_limite)]])
            st.success("Limite atualizado!")
            st.rerun()

        st.divider()
        st.subheader("👥 Gestão de Usuários")
        busca = st.text_input("🔍 Pesquisar por Nome ou E-mail:").strip().lower()

        if st.button("✅ ATIVAR TODOS E DESLOGAR", use_container_width=True):
            if records_u:
                # update em lote (1 chamada)
                start = 2
                end = len(records_u) + 1
                rng = f"H{start}:H{end}"
                gs_call(sheet_u_escrita.update, rng, [["ATIVO"]] * len(records_u))
                time_module.sleep(1)
                st.session_state.clear()
                st.rerun()

        for i, user in enumerate(records_u):
            if busca == "" or busca in str(user.get("Nome", "")).lower() or busca in str(user.get("Email", "")).lower():
                status = str(user.get("STATUS", "")).upper()
                with st.expander(f"{user.get('Graduação')} {user.get('Nome')} - {status}"):
                    c1, c2, c3 = st.columns([2, 1, 1])
                    c1.write(f"📧 {user.get('Email')} | 📱 {user.get('TELEFONE')}")
                    is_ativo = (status == "ATIVO")

                    # IMPORTANTE: checkbox só altera quando muda (reduz updates)
                    new_val = c2.checkbox("Liberar", value=is_ativo, key=f"adm_chk_{i}")
                    if new_val != is_ativo:
                        gs_call(sheet_u_escrita.update_cell, i + 2, 8, "ATIVO" if new_val else "INATIVO")
                        st.rerun()

                    if c3.button("🗑️", key=f"del_{i}"):
                        gs_call(sheet_u_escrita.delete_rows, i + 2)
                        st.rerun()

    # ==========================================================
    # USUÁRIO LOGADO
    # ==========================================================
    else:
        u = st.session_state.usuario_logado

        st.sidebar.markdown("### 👤 Usuário Conectado")
        st.sidebar.info(f"**{u.get('Graduação')} {u.get('Nome')}**")
        if st.sidebar.button("Sair", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        st.sidebar.markdown("---")
        st.sidebar.caption("Desenvolvido por: MAJ ANDRÉ AGUIAR - CAES")

        # Agora sim: só logado lê presença (reduz MUITO reads)
        sheet_p_escrita = ws_presenca()

        # “forçar refresh” (limpeza automática) sem cache_data.clear global
        if st.session_state._force_refresh_presenca:
            buscar_presenca_atualizada.clear()
            st.session_state._force_refresh_presenca = False

        dados_p = buscar_presenca_atualizada()
        aberto, janela_conf = verificar_status_e_limpar(sheet_p_escrita, dados_p)

        df_o, df_v = pd.DataFrame(), pd.DataFrame()
        ja, pos = False, 999

        if dados_p and len(dados_p) > 1:
            df_o, df_v = aplicar_ordenacao(pd.DataFrame(dados_p[1:], columns=dados_p[0]))
            email_logado = str(u.get("Email")).strip().lower()
            ja = any(email_logado == str(row.get("EMAIL", "")).strip().lower() for _, row in df_o.iterrows())
            if ja:
                pos = df_o.index[df_o["EMAIL"].str.lower() == email_logado].tolist()[0] + 1

        if ja:
            st.success(f"✅ Presença registrada: {pos}º")
            if st.button("❌ EXCLUIR MINHA ASSINATURA", use_container_width=True):
                email_logado = str(u.get("Email")).strip().lower()
                for idx, r in enumerate(dados_p):
                    if len(r) >= 6 and str(r[5]).strip().lower() == email_logado:
                        gs_call(sheet_p_escrita.delete_rows, idx + 1)
                        # invalida só presença
                        buscar_presenca_atualizada.clear()
                        st.rerun()

        elif aberto:
            if st.button("🚀 SALVAR MINHA PRESENÇA", use_container_width=True):
                agora = datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M:%S")
                gs_call(sheet_p_escrita.append_row, [
                    agora,
                    u.get("ORIGEM") or "QG",
                    u.get("Graduação"),
                    u.get("Nome"),
                    u.get("Lotação"),
                    u.get("Email")
                ])
                buscar_presenca_atualizada.clear()
                st.rerun()
        else:
            st.info("⌛ Lista fechada para novas inscrições.")

        if ja and pos <= 3 and janela_conf:
            st.divider()
            st.subheader("📋 CONFERÊNCIA")
            if st.button("📝 PAINEL", use_container_width=True):
                st.session_state.conf_ativa = not st.session_state.conf_ativa
            if st.session_state.conf_ativa and (dados_p and len(dados_p) > 1):
                for i, row in df_o.iterrows():
                    st.checkbox(f"{row['Nº']} - {row.get('NOME')}", key=f"chk_p_{i}")

        if dados_p and len(dados_p) > 1:
            insc = len(df_o)
            rest = 38 - insc
            st.subheader(f"Inscritos: {insc} | Vagas: 38 | {'Sobra' if rest >= 0 else 'Exc'}: {abs(rest)}")

            c_up1, c_up2 = st.columns([1, 1])
            with c_up1:
                if st.button("🔄 ATUALIZAR", use_container_width=True):
                    buscar_presenca_atualizada.clear()
                    st.rerun()

            with c_up2:
                st.caption("Atualiza...).")

            st.write(
                f"<div class='tabela-responsiva'>{df_v.drop(columns=['EMAIL']).to_html(index=False, justify='center', border=0, escape=False)}</div>",
                unsafe_allow_html=True
            )

            c1, c2 = st.columns(2)
            with c1:
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", "B", 12)
                pdf.cell(190, 10, "LISTA DE PRESENÇA", ln=True, align="C")
                pdf.ln(5)

                headers = ["Nº", "GRADUAÇÃO", "NOME", "LOTAÇÃO"]
                col_widths = [15, 25, 80, 70]
                for h_idx, h in enumerate(headers):
                    pdf.cell(col_widths[h_idx], 8, h, border=1, align="C")
                pdf.ln()
                pdf.set_font("Arial", "", 8)

                for _, r in df_o.iterrows():
                    pdf.cell(col_widths[0], 8, str(r["Nº"]), border=1)
                    pdf.cell(col_widths[1], 8, str(r["GRADUAÇÃO"]), border=1)
                    pdf.cell(col_widths[2], 8, str(r["NOME"])[:45], border=1)
                    pdf.cell(col_widths[3], 8, str(r["LOTAÇÃO"])[:40], border=1)
                    pdf.ln()

                st.download_button(
                    "📄 PDF",
                    pdf.output(dest="S").encode("latin-1"),
                    "lista.pdf",
                    use_container_width=True
                )

            with c2:
                txt_w = "*🚌 LISTA DE PRESENÇA*\n\n"
                for _, r in df_o.iterrows():
                    txt_w += f"{r['Nº']}. {r['GRADUAÇÃO']} {r['NOME']}\n"
                st.markdown(
                    f'<a href="https://wa.me/?text={urllib.parse.quote(txt_w)}" target="_blank">'
                    f"<button style='width:100%; height:38px; background-color:#25D366; color:white; border:none; "
                    f"border-radius:4px; font-weight:bold;'>🟢 WHATSAPP</button></a>",
                    unsafe_allow_html=True
                )

    st.markdown('<div class="footer">Desenvolvido por:       <b>MAJ ANDRÉ AGUIAR - CAES</b></div>', unsafe_allow_html=True)

except Exception as e:
    st.error(f"⚠️ Erro: {e}")

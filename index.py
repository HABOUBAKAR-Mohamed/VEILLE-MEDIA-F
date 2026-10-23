"""Tableau de bord Streamlit : veille média et réseaux sociaux France (version unifiée)."""
import json
import os
import re
import html
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
import pandas as pd
import streamlit as st
import feedparser

# Configuration de la page
st.set_page_config(page_title="Veille média France", page_icon="📰", layout="wide")

# Gestion des secrets Streamlit
for _k in ("ANTHROPIC_API_KEY", "YOUTUBE_API_KEY", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
           "BSKY_HANDLE", "BSKY_APP_PASSWORD"):
    try:
        if _k in st.secrets:
            os.environ.setdefault(_k, str(st.secrets[_k]))
    except Exception:
        pass

# --- MODULE PRESSE & SOCIAL INTÉGRÉ ---
GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=fr&gl=FR&ceid=FR:fr"

FLUX_DIRECTS = {
    "Le Monde": "https://www.lemonde.fr/rss/une.xml",
    "Le Monde - Société": "https://www.lemonde.fr/societe/rss_full.xml",
    "Le Monde - Économie": "https://www.lemonde.fr/economie/rss_full.xml",
    "Le Figaro": "https://www.lefigaro.fr/rss/figaro_actualites.xml",
    "Le Figaro - Social": "https://www.lefigaro.fr/rss/figaro_social.xml",
    "Franceinfo": "https://www.francetvinfo.fr/titres.rss",
    "20 Minutes": "https://www.20minutes.fr/feeds/rss-une.xml",
}

THEMES = {
    "Transports": ["sncf", "ratp", "train", "metro", "aerien", "aiguilleur", "controleur", "tgv"],
    "Éducation": ["enseignant", "ecole", "college", "lycee", "universite", "education nationale"],
    "Santé": ["hopital", "soignant", "medecin", "infirmier", "urgences"],
    "Énergie": ["edf", "energie", "raffinerie", "carburant", "electricite"],
    "Fonction publique": ["fonctionnaire", "fonction publique", "service public"],
    "Retraites / Social": ["retraite", "assurance chomage", "salaire", "pouvoir d'achat", "reforme"],
    "Budget": ["budget", "plf", "plfss", "49.3", "austerite"],
}

ACTEURS = {
    "CGT": ["cgt"], "CFDT": ["cfdt"], "FO": ["force ouvriere", " fo "], "SUD": ["sud-rail", "solidaires", "sud "],
    "UNSA": ["unsa"], "CFE-CGC": ["cfe-cgc"], "Gouvernement": ["gouvernement", "premier ministre", "ministre"],
    "Assemblée / Sénat": ["assemblee", "senat", "depute", "senateur"], "Patronat": ["medef", "cpme", "patronat"],
}

POSITIF_PERTURBATION = ["perturbation", "paralys", "bloqu", "annul", "retard", "manifestation", "mobilisation"]
DESESCALADE = ["accord", "negociation", "levee du preavis", "suspend", "fin de la greve", "reprise"]

def norm(txt: str) -> str:
    if not txt:
        return ""
    txt = unicodedata.normalize("NFD", txt.lower())
    return "".join(c for c in txt if unicodedata.category(c) != "Mn")

def tags(texte: str, dico: dict) -> list:
    t = f" {texte} "
    return [k for k, mots in dico.items() if any(m in t for m in mots)]

def date_entree(e):
    for champ in ("published_parsed", "updated_parsed"):
        if getattr(e, champ, None):
            return datetime(*getattr(e, champ)[:6], tzinfo=timezone.utc)
    return None

def collecter_presse(mots, jours):
    seuil = datetime.now(timezone.utc) - timedelta(days=jours)
    requetes = [(f"Google Actualités : {m}", GOOGLE_NEWS.format(q=urllib.parse.quote(f"{m} when:{jours}d"))) for m in mots]
    requetes += list(FLUX_DIRECTS.items())
    mots_n = [norm(m) for m in mots]
    cles = {w for m in mots_n for w in m.split() if len(w) > 3}
    articles = []
    for nom, url in requetes:
        try:
            flux = feedparser.parse(url, agent="veille-media/1.0")
        except Exception:
            continue
        if not flux.entries:
            continue
        for e in flux.entries:
            d = date_entree(e)
            if d and d < seuil:
                continue
            titre = re.sub(r"<[^>]+>", "", e.get("title", "")).strip()
            resume = re.sub(r"<[^>]+>", "", e.get("summary", "")).strip()
            texte = norm(f"{titre} {resume}")
            if mots_n and not any(all(w in texte for w in m.split() if len(w) > 3) for m in mots_n):
                continue
            source = (e.get("source") or {}).get("title") or nom.replace("Google Actualités : " + "", "").split(" - ")[0]
            if nom.startswith("Google") and " - " in titre:
                titre, source = titre.rsplit(" - ", 1)
            pertur = sum(texte.count(m) for m in POSITIF_PERTURBATION)
            deesc = sum(texte.count(m) for m in DESESCALADE)
            articles.append({
                "date": d.isoformat() if d else "", "source": source.strip(), "titre": titre,
                "resume": resume[:400], "url": e.get("link", ""),
                "themes": tags(texte, THEMES), "acteurs": tags(f" {texte} ", ACTEURS),
                "tendance": "désescalade" if deesc > pertur else ("tension" if pertur else "neutre"),
                "score": sum(texte.count(w) for w in cles) + pertur + deesc,
            })
    vus, uniques = set(), []
    for a in sorted(articles, key=lambda x: (x["date"], x["score"]), reverse=True):
        cle = norm(a["titre"])[:80]
        if cle not in vus:
            vus.add(cle)
            uniques.append(a)
    return uniques

def synthese_claude(articles):
    cle = os.environ.get("ANTHROPIC_API_KEY")
    if not cle:
        return ""
    corpus = "\n".join(f"- [{a['date'][:16]}] {a['source']} : {a['titre']} — {a['resume'][:200]}" for a in articles[:60])
    consigne = (
        "Tu es analyste en affaires publiques. À partir de ces titres de presse française sur une grève, rédige en français "
        "une note de veille : 1) état de la situation, 2) acteurs et positions, "
        "3) signaux annonçant un arbitrage ou une négociation, 4) points de vigilance.\n\n" + corpus
    )
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps({"model": "claude-3-5-sonnet-20241022", "max_tokens": 2000,
                             "messages": [{"role": "user", "content": consigne}]}).encode(),
            headers={"x-api-key": cle, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            res_json = json.load(r)
            return "".join(b.get("text", "") for b in res_json.get("content", []))
    except Exception:
        return "Erreur lors de la génération de la note par Claude."


def to_df(rows, listes):
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    for c in listes:
        df[c + "_txt"] = df[c].apply(lambda v: ", ".join(v) if isinstance(v, list) else "")
    return df


# --- Barre latérale ------------------------------------------------------------
st.sidebar.title("Paramètres")
mots = tuple(m.strip() for m in st.sidebar.text_area("Mots-clés (un par ligne)", "grève").splitlines() if m.strip())
jours = st.sidebar.slider("Période (jours)", 1, 14, 3)
sources = st.sidebar.multiselect("Réseaux sociaux", ["Mastodon", "Reddit", "Bluesky", "YouTube"], default=[])
st.sidebar.caption("Les clés API se configurent dans les secrets Streamlit.")
st.sidebar.divider()
fa = st.sidebar.file_uploader("…ou charger articles.json", type="json")
fs = st.sidebar.file_uploader("…ou charger social.json", type="json")
st.sidebar.divider()
live = st.sidebar.toggle("Temps réel (actualisation automatique)", value=False)
interval = st.sidebar.slider("Fréquence (minutes)", 2, 30, 5, disabled=not live)
seuil_alerte = st.sidebar.slider("Alerte si tension ≥ (%)", 30, 100, 60)
if st.sidebar.button("Actualiser maintenant"):
    st.cache_data.clear()

TTL = max(60, interval * 60 - 5) if live else 900

@st.cache_data(ttl=TTL, show_spinner="Collecte de la presse…")
def get_presse(mots: tuple, jours: int):
    return collecter_presse(list(mots), jours)

st.title("Veille média France")

@st.fragment(run_every=interval * 60 if live else None)
def dashboard():
    if fa:
        arts = json.loads(fa.getvalue()).get("articles", [])
    else:
        if not mots:
            st.warning("Saisissez au moins un mot-clé.")
            return
        arts = get_presse(mots, jours)

    posts = []
    if fs:
        posts = json.loads(fs.getvalue()).get("posts", [])

    dfA, dfS = to_df(arts, ["themes", "acteurs"]), to_df(posts, ["hashtags"])

    urls = {a["url"] for a in arts} | {p.get("url", "") for p in posts}
    deja = st.session_state.get("vus", set())
    nouveaux = (urls - deja) if deja else set()
    st.session_state["vus"] = deja | urls
    if live and nouveaux:
        st.toast(f"{len(nouveaux)} nouveau(x) contenu(x)", icon="🔔")
    st.caption(f"Dernière actualisation : {datetime.now().strftime('%H:%M:%S')}")

    # Filtres
    c1, c2, c3 = st.columns([2, 2, 3])
    themes = sorted({t for l in dfA.get("themes", []) for t in l}) if not dfA.empty else []
    th = c1.multiselect("Thèmes", themes)
    td = c2.multiselect("Tendance", ["tension", "apaisement", "neutre"])
    q = c3.text_input("Recherche").lower()

    if not dfA.empty:
        if th:
            dfA = dfA[dfA["themes"].apply(lambda l: any(t in l for t in th))]
        if td:
            dfA = dfA[dfA["tendance"].isin(td)]
        if q:
            dfA = dfA[(dfA["titre"] + " " + dfA["resume"]).str.lower().str.contains(q, regex=False)]
    if not dfS.empty:
        if td:
            dfS = dfS[dfS["tendance"].isin(td)]
        if q:
            dfS = dfS[dfS["texte"].str.lower().str.contains(q, regex=False)]

    tout = pd.concat([dfA.get("tendance", pd.Series(dtype=str)), dfS.get("tendance", pd.Series(dtype=str))])
    k = st.columns(5)
    k[0].metric("Articles", len(dfA))
    k[1].metric("Médias", dfA["source"].nunique() if not dfA.empty else 0)
    k[2].metric("Publications sociales", len(dfS))
    k[3].metric("En tension", f"{round(100 * (tout == 'tension').mean())} %" if len(tout) else "–")
    k[4].metric("Engagement social", f"{int(dfS['engagement'].sum()):,}".replace(",", " ") if not dfS.empty and "engagement" in dfS else 0)

    if dfA.empty and dfS.empty:
        st.info("Aucune donnée disponible. Vérifiez vos mots-clés.")
        return

    t1, t2, t3, t4 = st.tabs(["Vue d’ensemble", "Presse", "Réseaux sociaux", "Note de synthèse (Claude)"])

    with t1:
        a, b = st.columns(2)
        if not dfA.empty:
            a.subheader("Thèmes (presse)")
            a.bar_chart(dfA.explode("themes")["themes"].dropna().value_counts().head(10))
            b.subheader("Tendances globales")
            b.bar_chart(tout.value_counts())

    with t2:
        if dfA.empty:
            st.info("Aucun article.")
        else:
            v = dfA.sort_values("date", ascending=False)[["date", "source", "titre", "themes_txt", "acteurs_txt", "tendance", "url"]]
            st.dataframe(v, hide_index=True, column_config={"url": st.column_config.LinkColumn("Lien", display_text="ouvrir")})

    with t3:
        if dfS.empty:
            st.info("Aucune publication sociale.")
        else:
            st.dataframe(dfS, hide_index=True)

    with t4:
        st.write("Claude rédige une note d’analyse à partir des articles actuellement filtrés.")
        if st.button("Générer la note"):
            if not os.environ.get("ANTHROPIC_API_KEY"):
                st.error("ANTHROPIC_API_KEY absente des secrets.")
            elif dfA.empty:
                st.warning("Aucun article à analyser.")
            else:
                with st.spinner("Analyse en cours…"):
                    rows = dfA.assign(date=dfA["date"].astype(str)).to_dict("records")
                    st.session_state["note"] = synthese_claude(rows)
        if st.session_state.get("note"):
            st.markdown(st.session_state["note"])

dashboard()

"""Tableau de bord Streamlit : veille média et réseaux sociaux France."""
import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

# Les secrets Streamlit (Cloud ou .streamlit/secrets.toml) deviennent des variables d'environnement.
for _k in ("ANTHROPIC_API_KEY", "YOUTUBE_API_KEY", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
           "BSKY_HANDLE", "BSKY_APP_PASSWORD"):
    try:
        if _k in st.secrets:
            os.environ.setdefault(_k, str(st.secrets[_k]))
    except Exception:
        pass

from veille import agent, presse, social  # noqa: E402

st.set_page_config(page_title="Veille média France", page_icon="📰", layout="wide")


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
sources = st.sidebar.multiselect("Réseaux sociaux", ["Mastodon", "Reddit", "Bluesky", "YouTube"],
                                 default=["Mastodon", "Reddit", "Bluesky", "YouTube"])
hashtags = tuple(h.strip().lstrip("#") for h in st.sidebar.text_input(
    "Hashtags (séparés par des virgules)", "").split(",") if h.strip()) or tuple(
    social.norm(m).replace(" ", "") for m in mots)
agent_mode = st.sidebar.radio(
    "Mode de collecte", ["Agents IA (Claude)", "Scripts (sans IA)"],
    help="Agents IA : Claude choisit et affine lui-même ses requêtes, croise les sources et extrait des signaux "
         "(facturé à l'usage). Scripts : collecte fixe, gratuite.") == "Agents IA (Claude)"
web = st.sidebar.checkbox("Autoriser la recherche web de Claude", value=False, disabled=not agent_mode,
                          help="Ajoute l'outil de recherche web de l'API (facturé en plus).")
st.sidebar.caption("Les clés API se configurent dans les secrets (voir README). Une source sans clé est ignorée.")
st.sidebar.divider()
fa = st.sidebar.file_uploader("…ou charger articles.json", type="json")
fs = st.sidebar.file_uploader("…ou charger social.json", type="json")
st.sidebar.divider()
live = st.sidebar.toggle("Temps réel (actualisation automatique)", value=False)
interval = st.sidebar.slider("Fréquence (minutes)", 2, 30, 5, disabled=not live)
seuil_alerte = st.sidebar.slider("Alerte si tension ≥ (%)", 30, 100, 60)
if st.sidebar.button("Actualiser maintenant"):
    st.cache_data.clear()

# Cache aligné sur la fréquence : en mode temps réel, chaque cycle récupère des données fraîches.
TTL = max(60, interval * 60 - 5) if live else 900


@st.cache_data(ttl=TTL, show_spinner="Collecte de la presse…")
def get_presse(mots: tuple, jours: int):
    return presse.collecter(list(mots), jours)


@st.cache_data(ttl=TTL, show_spinner="Collecte des réseaux sociaux…")
def get_social_libre(mots: tuple, hashtags: tuple, jours: int, sources: tuple):
    seuil = datetime.now(timezone.utc) - timedelta(days=jours)
    posts = []
    if "Mastodon" in sources:
        posts += social.mastodon(list(hashtags), seuil)
    if "Reddit" in sources:
        posts += social.reddit(list(mots), seuil, jours)
    if "Bluesky" in sources:
        posts += social.bluesky(list(mots), seuil)
    return posts


@st.cache_data(ttl=max(TTL, 1800), show_spinner=False)  # la recherche YouTube coûte 100 unités de quota
def get_youtube(mots: tuple, jours: int):
    return social.youtube(list(mots), datetime.now(timezone.utc) - timedelta(days=jours))


@st.cache_data(ttl=max(TTL, 900), show_spinner="L’agent IA mène la veille (1 à 2 minutes)…")
def get_agent(mots: tuple, jours: int, sources: tuple, web: bool):
    return agent.run_agent(list(mots), jours, plateformes=list(sources), web=web)


def get_social(mots, hashtags, jours, sources):
    posts = get_social_libre(mots, hashtags, jours, sources)
    if "YouTube" in sources:
        posts = posts + get_youtube(mots, jours)
    vus, uniques = set(), []
    for p in sorted(posts, key=lambda x: x["date"], reverse=True):
        if p["url"] not in vus:
            vus.add(p["url"])
            uniques.append(p)
    return uniques

st.title("Veille média France")


@st.fragment(run_every=interval * 60 if live else None)
def dashboard():
    # --- Données -----------------------------------------------------------------------
    signaux, journal = None, []
    if fa or fs:
        arts = json.loads(fa.getvalue()).get("articles", []) if fa else []
        posts = json.loads(fs.getvalue()).get("posts", []) if fs else []
    else:
        if not mots:
            st.warning("Saisissez au moins un mot-clé.")
            return
        if agent_mode:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                st.error("Le mode Agents IA nécessite ANTHROPIC_API_KEY (voir README). "
                         "Choisissez « Scripts (sans IA) » pour une collecte gratuite.")
                return
            try:
                res = get_agent(mots, jours, tuple(sources), web)
            except Exception as e:
                st.error(f"Erreur de l’agent : {e}")
                return
            arts, posts, signaux, journal = res["articles"], res["posts"], res["resultats"], res["journal"]
        else:
            arts = get_presse(mots, jours)
            posts = get_social(mots, hashtags, jours, tuple(sources)) if sources else []

    dfA, dfS = to_df(arts, ["themes", "acteurs"]), to_df(posts, ["hashtags"])

    # --- Nouveautés et alerte ---
    urls = {a["url"] for a in arts} | {p["url"] for p in posts}
    deja = st.session_state.get("vus", set())
    nouveaux = (urls - deja) if deja else set()
    st.session_state["vus"] = deja | urls
    if live and nouveaux:
        st.toast(f"{len(nouveaux)} nouveau(x) contenu(x)", icon="🔔")
    st.caption(f"Dernière actualisation : {datetime.now().strftime('%H:%M:%S')}"
               + (f" · prochaine dans {interval} min" if live else " · mode manuel"))
    for d in (dfA, dfS):
        if not d.empty:
            d["nouveau"] = d["url"].isin(nouveaux)

    # --- Filtres ---------------------------------------------------------------------------
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
        if th:  # les thèmes ne s'appliquent qu'à la presse
            dfS = dfS.iloc[0:0]

    # --- Indicateurs -----------------------------------------------------------------------
    tout = pd.concat([dfA.get("tendance", pd.Series(dtype=str)), dfS.get("tendance", pd.Series(dtype=str))])
    k = st.columns(5)
    k[0].metric("Articles", len(dfA))
    k[1].metric("Médias", dfA["source"].nunique() if not dfA.empty else 0)
    k[2].metric("Publications sociales", len(dfS))
    k[3].metric("En tension", f"{round(100 * (tout == 'tension').mean())} %" if len(tout) else "–")
    k[4].metric("Engagement social", f"{int(dfS['engagement'].sum()):,}".replace(",", " ") if not dfS.empty else 0)

    if len(tout) and 100 * (tout == "tension").mean() >= seuil_alerte:
        st.warning(f"Alerte : {round(100 * (tout == 'tension').mean())} % des contenus sont en tension (seuil {seuil_alerte} %).")
    if nouveaux:
        st.info(f"{len(nouveaux)} nouveau(x) contenu(x) depuis la dernière actualisation.")

    if dfA.empty and dfS.empty:
        st.info("Aucune donnée. Vérifiez vos mots-clés ou votre connexion, ou chargez des fichiers JSON.")
        return

    t1, t5, t2, t3, t4 = st.tabs(["Vue d’ensemble", "Signaux (agent IA)", "Presse", "Réseaux sociaux", "Note de synthèse (Claude)"])

    with t5:
        if not signaux:
            st.info("Les signaux sont produits par l'agent : choisissez le mode « Agents IA (Claude) » dans la barre latérale.")
        else:
            st.markdown(signaux.get("synthese", ""))
            couleur = {"fort": "🔴", "moyen": "🟠", "faible": "🟢"}
            ordre = {"fort": 0, "moyen": 1, "faible": 2}
            tous = {**{a["id"]: a for a in arts}, **{p["id"]: p for p in posts}}
            for sg in sorted(signaux.get("signaux", []), key=lambda x: ordre.get(x.get("niveau"), 3)):
                with st.expander(f"{couleur.get(sg.get('niveau'), '⚪')} {sg['titre']} · {sg['type']}"):
                    st.write(sg["resume"])
                    st.markdown(f"**Pourquoi c’est important :** {sg['pourquoi_important']}")
                    if sg.get("acteurs"):
                        st.caption("Acteurs : " + ", ".join(sg["acteurs"]))
                    if sg.get("echeance"):
                        st.caption("Échéance : " + sg["echeance"])
                    for i in sg.get("ids", []):
                        if i in tous and tous[i].get("url", "#") != "#":
                            st.markdown(f"- [{(tous[i].get('titre') or tous[i].get('texte', ''))[:110]}]({tous[i]['url']})")
            if signaux.get("points_vigilance"):
                st.subheader("Points de vigilance")
                for v in signaux["points_vigilance"]:
                    st.markdown(f"- {v}")
            if signaux.get("lacunes"):
                st.caption("Limites de la collecte : " + signaux["lacunes"])
            st.download_button("Télécharger les signaux (JSON)",
                               json.dumps(signaux, ensure_ascii=False, indent=2), "signaux.json")
            with st.expander("Journal de l’agent (requêtes effectuées)"):
                st.write("\n".join(f"- {j}" for j in journal))

    with t1:
        a, b = st.columns(2)
        jour = pd.concat([
            dfA.assign(type="Presse")[["date", "type"]] if not dfA.empty else pd.DataFrame(columns=["date", "type"]),
            dfS.assign(type="Réseaux")[["date", "type"]] if not dfS.empty else pd.DataFrame(columns=["date", "type"]),
        ])
        jour["jour"] = pd.to_datetime(jour["date"], utc=True).dt.strftime("%Y-%m-%d")
        a.subheader("Volume par jour")
        a.bar_chart(jour.groupby(["jour", "type"]).size().unstack(fill_value=0))
        b.subheader("Tendance")
        b.bar_chart(tout.value_counts())
        c, d = st.columns(2)
        if not dfA.empty:
            c.subheader("Thèmes (presse)")
            c.bar_chart(dfA.explode("themes")["themes"].dropna().value_counts().head(10))
            d.subheader("Acteurs cités (presse)")
            d.bar_chart(dfA.explode("acteurs")["acteurs"].dropna().value_counts().head(10))
        if not dfS.empty:
            st.subheader("Hashtags dominants")
            h = dfS.explode("hashtags")["hashtags"].dropna().value_counts().head(20)
            st.write("  ".join(f"`#{t}` {n}" for t, n in h.items()) or "Aucun hashtag")

    with t2:
        if dfA.empty:
            st.info("Aucun article.")
        else:
            v = dfA.sort_values("date", ascending=False)[["date", "source", "titre", "themes_txt", "acteurs_txt", "tendance", "nouveau", "url"]]
            st.dataframe(v, hide_index=True, width="stretch", column_config={
                "url": st.column_config.LinkColumn("Lien", display_text="ouvrir"),
                "themes_txt": "Thèmes", "acteurs_txt": "Acteurs"})
            st.download_button("Télécharger en CSV", v.to_csv(index=False, sep=";").encode("utf-8-sig"), "articles.csv")

    with t3:
        if dfS.empty:
            st.info("Aucune publication (sources sans clé ignorées, voir README).")
        else:
            v = dfS.sort_values("engagement", ascending=False)[["date", "plateforme", "texte", "engagement", "tendance", "nouveau", "url"]]
            st.dataframe(v, hide_index=True, width="stretch",
                         column_config={"url": st.column_config.LinkColumn("Lien", display_text="ouvrir")})
            st.download_button("Télécharger en CSV", v.to_csv(index=False, sep=";").encode("utf-8-sig"), "social.csv")

    with t4:
        st.write("Claude rédige une note d’analyse à partir des articles actuellement filtrés. "
                 "Nécessite `ANTHROPIC_API_KEY` ; l’API est facturée à l’usage.")
        if st.button("Générer la note"):
            if not os.environ.get("ANTHROPIC_API_KEY"):
                st.error("ANTHROPIC_API_KEY absente (voir README).")
            elif dfA.empty:
                st.warning("Aucun article à analyser.")
            else:
                with st.spinner("Analyse en cours…"):
                    try:
                        rows = dfA.assign(date=dfA["date"].astype(str)).to_dict("records")
                        st.session_state["note"] = presse.synthese_claude(rows)
                    except Exception as e:
                        st.error(f"Erreur API : {e}")
        if st.session_state.get("note"):
            st.markdown(st.session_state["note"])
            st.download_button("Télécharger la note", st.session_state["note"], "synthese.md")


dashboard()

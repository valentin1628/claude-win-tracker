# Claude Usage Tray

Petite appli Windows, sobre, qui vit dans la zone de notification et affiche l'utilisation
de ton abonnement Claude (Pro / Max) : la **session 5 h** et le **quota hebdomadaire**,
avec leurs heures de reset. Ce sont les mêmes chiffres que `/usage` dans Claude Code.

<p align="center">
  <img src="docs/popup.png" alt="Popup" width="300">
  &nbsp;
  <img src="docs/popup-offline.png" alt="Popup hors ligne" width="300">
</p>
<p align="center"><img src="docs/tray-icons.png" alt="Icônes du tray" width="380"></p>

- **Icône** : un anneau qui se remplit (vert < 60 %, orange < 85 %, rouge au-delà), avec le % au centre.
- **Clic gauche** : mini-fenêtre avec les deux jauges et le compte à rebours avant reset. Une ligne « Opus (semaine) » s'ajoute en bas uniquement sur les offres **Max**, qui ont un quota hebdo séparé pour Opus. Sur **Pro**, elle n'apparaît pas.
- **Clic droit** : Rafraîchir, choix de la valeur affichée dans l'icône (session, semaine ou la plus élevée), lancement au démarrage de Windows, Quitter.
- **Notifications** quand la session ou la semaine dépasse 80 % puis 95 %.
- Survole l'icône pour un résumé dans l'infobulle.

## Prérequis

- Windows 10/11 et Python 3.10+ (pour lancer depuis les sources ou construire l'exe).
- **Claude Code installé et connecté** avec ton compte Claude (`claude` puis `/login`).
  L'appli lit le jeton dans `%USERPROFILE%\.claude\.credentials.json`. Elle ne demande aucun mot de passe et n'envoie rien ailleurs qu'à `api.anthropic.com`.

## Lancer depuis les sources

```powershell
py -3 -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev]
python -m claude_tracker          # vraie appli
python -m claude_tracker --demo   # fausses données, pour voir le rendu
```

### Mode démo ou vraies données ?

`--demo` affiche des **valeurs inventées** qui montent de 3 % à chaque actualisation. Le popup porte alors
un badge orange **DÉMO** et l'infobulle commence par `[Démo]`. Pour voir tes vrais chiffres, lance
`python -m claude_tracker` **sans option**, ou l'exe. L'offre affichée (« Claude · Pro ») vient
alors de ton compte, et les % doivent correspondre à `/usage` dans Claude Code.

<p align="center"><img src="docs/popup-demo.png" alt="Popup en mode démo" width="300"></p>

## Construire l'exécutable

```powershell
.\build.ps1
```

Le script crée un venv, lance les tests et produit `dist\ClaudeTracker.exe`, un exe unique sans console.
Place-le où tu veux, par exemple dans `%LOCALAPPDATA%\Programs\ClaudeTracker\`, puis coche
**Lancer au démarrage** dans le menu.

> Si PowerShell refuse le script : `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Réglages

Le fichier de réglages est `%APPDATA%\ClaudeTracker\config.json`. Il est créé dès que tu changes une option dans le menu.

```json
{
  "poll_seconds": 120,
  "icon_metric": "five_hour",
  "notify_thresholds": [80, 95],
  "auto_refresh_token": false
}
```

| Clé | Rôle |
|---|---|
| `poll_seconds` | Intervalle de rafraîchissement (60 s minimum). |
| `icon_metric` | Valeur affichée dans l'icône : `five_hour`, `seven_day` ou `max` (la plus élevée). |
| `notify_thresholds` | Seuils (en %) qui déclenchent une notification. |
| `auto_refresh_token` | Quand le jeton expire, l'appli le renouvelle elle-même (voir plus bas). |

### À propos du jeton

Le jeton de Claude Code expire au bout de quelques heures et Claude Code le renouvelle à chaque utilisation.
Par défaut, si le jeton a expiré, l'appli passe en gris et affiche « ouvre Claude Code ».
Il suffit de lancer `claude` une fois pour que ça reparte.

Avec `auto_refresh_token: true`, l'appli renouvelle le jeton elle-même et réécrit le fichier.
C'est pratique si tu n'utilises pas Claude Code tous les jours. L'inconvénient : une session Claude Code
déjà ouverte au même moment peut devoir se reconnecter.

## Fonctionnement

```
src/claude_tracker/
├─ usage_client.py  # lecture du jeton + appel GET /api/oauth/usage, parsing tolérant
├─ render.py        # anneaux dessinés avec Pillow (supersampling x4 → anti-aliasing)
├─ popup.py         # fenêtre customtkinter sans bordure, au-dessus de la barre des tâches
├─ app.py           # Tk (thread principal) + pystray + thread de polling, reliés par une file
├─ formatting.py    # textes FR : « reset dans 2 h 14 », infobulle…
├─ config.py        # réglages JSON
└─ autostart.py     # clé de registre HKCU\…\Run
```

L'endpoint `api.anthropic.com/api/oauth/usage` est celui qu'utilise Claude Code. Il n'est **pas documenté
officiellement** et peut donc changer. Tout ce qui dépend de son format est regroupé dans `usage_client.py`.

Pour regénérer les aperçus des icônes : `python -m claude_tracker.render --preview preview`.

## Tests

```powershell
pytest
```

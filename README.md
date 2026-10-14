# Claude Usage Tray

Une petite icône à côté de l'horloge Windows qui te dit où tu en es de ton abonnement Claude (Pro ou Max).

Claude limite l'utilisation de deux façons : une **session de 5 heures** et un **quota par semaine**. Quand tu arrives au bout, il faut attendre. Cette appli te montre en permanence combien tu as consommé, et dans combien de temps ça se recharge. Plus besoin d'aller vérifier sur le site.

<p align="center">
  <img src="docs/popup.png" alt="La fenêtre de l'appli" width="300">
</p>

> Projet personnel, non officiel. Il n'est ni fait ni soutenu par Anthropic (l'entreprise derrière Claude).

---

## Ce qu'il te faut

- Un PC sous **Windows 10 ou 11**.
- Un abonnement **Claude Pro ou Max**.
- **Claude Code** installé et connecté à ton compte. On le fait ensemble juste en dessous, c'est gratuit avec ton abonnement.

Pourquoi Claude Code ? L'appli ne te demande jamais ton mot de passe. Elle réutilise la connexion que Claude Code garde sur ton PC. L'appli Claude « classique » (Claude Desktop) ou le site claude.ai ne suffisent pas : leur connexion n'est pas lisible par un autre programme.

---

## Installation

### Étape 1 : installer et connecter Claude Code

1. Ouvre le menu Démarrer, tape **PowerShell** et lance-le. Pas besoin du mode administrateur.
2. Copie cette ligne, colle-la dans la fenêtre (clic droit pour coller), puis appuie sur Entrée :
   ```powershell
   irm https://claude.ai/install.ps1 | iex
   ```
3. Quand c'est fini, tape `claude` puis Entrée.
4. Dans Claude Code, tape `/login` puis Entrée. Ton navigateur s'ouvre : connecte-toi avec ton compte Claude.
5. Une fois connecté, tape `/exit` pour quitter. Tu peux fermer PowerShell.

Tu n'auras plus besoin d'y toucher.

### Étape 2 : installer l'appli

1. Va sur la page des [téléchargements](https://github.com/valentin1628/claude-win-tracker/releases/latest).
2. Dans la partie **Assets**, clique sur le fichier `ClaudeTracker-...-Setup.exe` pour le télécharger.
3. Lance-le.

Windows va probablement afficher un écran bleu « Windows a protégé votre ordinateur ». C'est normal : l'appli n'est pas « signée », parce qu'un certificat de signature coûte plusieurs centaines d'euros par an. Clique sur **Informations complémentaires**, puis sur **Exécuter quand même**.

4. Suis l'installation. Je te conseille de cocher **Lancer au démarrage de Windows**.

Pas besoin d'être administrateur. Une fois l'installation finie, l'icône apparaît près de l'horloge.

C'est tout. La connexion de Claude Code expire toutes les quelques heures (et après un redémarrage du PC), mais l'appli la renouvelle toute seule, exactement comme le fait Claude Code. Tu n'as pas besoin d'ouvrir Claude Code pour que les chiffres restent à jour.

---

## Utilisation

**L'icône** affiche le pourcentage utilisé de ta session de 5 heures. L'anneau change de couleur :

| Couleur | Signification |
|---|---|
| Vert | moins de 60 % utilisés, tranquille |
| Orange | entre 60 et 85 %, ça commence à monter |
| Rouge | plus de 85 %, bientôt la limite |
| Gris | pas de données (pas de connexion, ou connexion expirée) |

<p align="center"><img src="docs/tray-icons.png" alt="Les icônes selon le niveau" width="380"></p>

**Passe la souris dessus** pour avoir un résumé rapide.

**Clic gauche** : ouvre la petite fenêtre avec deux jauges, la session 5 h et la semaine, et l'heure à laquelle chacune se recharge. Clique ailleurs pour la fermer.

**Clic droit** : le menu, avec :
- **Rafraîchir** : met à jour les chiffres tout de suite. Sinon, ils se mettent à jour seuls toutes les 2 minutes.
- **L'icône affiche** : choisir ce que montre l'icône (la session, la semaine, ou la plus haute des deux).
- **Notifications** : voir plus bas.
- **Lancer au démarrage** : pour que l'appli se lance avec Windows.
- **Quitter**.

Sur les abonnements Max, une ligne « Opus (semaine) » peut apparaître en bas de la fenêtre : c'est un quota séparé pour le modèle Opus. Sur Pro, elle n'apparaît pas.

---

## Notifications

L'appli peut te prévenir quand tu dépasses un certain niveau, par exemple « Session 5h : 82 % utilisés · reset à 16:30 ».

Par défaut, tu es prévenu à **80 %** et à **95 %**. Tout se règle dans **clic droit → Notifications** :
- **Activées** : couper ou remettre toutes les notifications.
- **À 50 %, 75 %, 80 %, 90 %, 95 %, 100 %** : coche les paliers qui t'intéressent.
- **Pour la session 5h / Pour la semaine** : choisir quels quotas surveiller.
- **Quand la session est rechargée** : être prévenu quand ta session repart à zéro.
- **Tester une notification** : pour voir à quoi ça ressemble.

Tu n'es prévenu qu'une fois par palier, au moment où tu le dépasses.

---

## Mises à jour

Tu n'as rien à faire. L'appli vérifie toute seule s'il existe une nouvelle version. Si oui, une notification apparaît. Fais **clic droit → Installer la mise à jour** : elle se télécharge, s'installe et l'appli redémarre.

Tu peux aussi vérifier à la main avec **clic droit → Rechercher les mises à jour**.

---

## Problèmes fréquents

**Je ne vois pas l'icône.**
Windows cache souvent les nouvelles icônes. Clique sur la petite flèche **^** à côté de l'horloge : elle y est sûrement. Pour la garder toujours visible : Paramètres → Personnalisation → Barre des tâches → Autres icônes de la barre d'état système, puis active **Claude Usage Tray**.

**L'icône est grise juste après le démarrage du PC.**
Rien d'anormal : le réseau n'est pas toujours prêt quand l'appli démarre. Elle réessaie au bout de 15 secondes, puis de 30 secondes.

**L'icône est grise et la fenêtre dit « Connexion à Claude expirée ».**
L'appli n'a pas réussi à renouveler la connexion. Ça arrive si tu t'es déconnecté de Claude Code, ou si la connexion a été révoquée (changement de mot de passe, par exemple). Clique sur le bouton **Se reconnecter à Claude** dans la fenêtre. Une fenêtre PowerShell s'ouvre avec Claude Code : s'il te le demande, reconnecte-toi, puis tape `/exit` et ferme la fenêtre. L'appli se met à jour aussitôt.

**L'icône reste grise et je ne comprends pas pourquoi.**
Dans le menu Démarrer, lance **Claude Usage Tray - diagnostic**. Une fenêtre vérifie chaque étape et te dit laquelle bloque, et quoi faire. Elle n'affiche aucune information secrète, tu peux en faire une capture pour demander de l'aide.

**Je suis sur un PC de boulot et ça ne marche pas.**
Certains réseaux d'entreprise filtrent les connexions sécurisées. Le diagnostic te le dira avec une « erreur SSL ». Dans ce cas, il faut voir avec ton service informatique.

**Les chiffres ne sont pas les mêmes que sur claude.ai.**
L'appli se met à jour toutes les 2 minutes. Fais clic droit → Rafraîchir. Ce sont les mêmes chiffres que la commande `/usage` dans Claude Code.

---

## Désinstaller

Paramètres Windows → Applications → **Claude Usage Tray** → Désinstaller.

---

## Réglages avancés

Tous les réglages sont dans le fichier `%APPDATA%\ClaudeTracker\config.json`. Pour l'ouvrir, colle ce chemin dans la barre d'adresse de l'Explorateur de fichiers. La plupart se changent depuis le menu de l'icône, donc tu n'as normalement pas besoin d'y toucher.

| Réglage | À quoi ça sert | Par défaut |
|---|---|---|
| `poll_seconds` | Toutes les combien de secondes les chiffres sont mis à jour (minimum 60) | `120` |
| `icon_metric` | Ce que montre l'icône : `five_hour` (session), `seven_day` (semaine) ou `max` | `five_hour` |
| `notifications_enabled` | Notifications activées | `true` |
| `notify_thresholds` | Paliers des notifications, en % | `[80, 95]` |
| `notify_session` / `notify_weekly` | Notifier pour la session / pour la semaine | `true` |
| `notify_recharge` | Notifier quand la session est rechargée | `false` |
| `auto_refresh_token` | L'appli renouvelle elle-même la connexion quand elle expire | `true` |
| `check_updates` | Rechercher les mises à jour | `true` |

Après une modification, redémarre l'appli. Les mises à jour ne touchent pas à ce fichier.

Pour les curieux : quand la connexion expire, l'appli fait la même chose que Claude Code. Elle demande un nouveau jeton à Anthropic et l'enregistre dans le fichier de Claude Code, que les deux partagent. Si Claude Code l'a déjà renouvelé, l'appli réutilise simplement le sien. Avec `"auto_refresh_token": false`, l'appli ne touche jamais à ce fichier : il faudra alors ouvrir Claude Code (ou cliquer sur **Se reconnecter à Claude**) quand la connexion expire.

---

<details>
<summary><b>Pour les développeurs</b></summary>

### Comment ça marche

L'appli lit le jeton que Claude Code enregistre dans `%USERPROFILE%\.claude\.credentials.json`. Avec ce jeton, elle appelle `https://api.anthropic.com/api/oauth/usage`, c'est-à-dire le service qu'utilise la commande `/usage` de Claude Code. Il n'est pas documenté officiellement et peut donc changer. Tout ce qui en dépend est regroupé dans `usage_client.py`.

```
src/claude_tracker/
├─ usage_client.py   lecture du jeton et appel à l'API
├─ app.py            icône (pystray), fenêtre (Tk) et rafraîchissement en arrière-plan
├─ popup.py          la fenêtre (customtkinter)
├─ render.py         dessin des anneaux (Pillow)
├─ formatting.py     textes affichés
├─ config.py         réglages
├─ updater.py        mises à jour depuis les releases GitHub
├─ login.py          bouton « Se reconnecter »
├─ diagnose.py       diagnostic (--check)
└─ autostart.py      lancement au démarrage
installer/ClaudeTracker.iss     installeur (Inno Setup)
.github/workflows/release.yml   build et publication automatiques
```

### Lancer depuis le code

Il faut [Python 3.10+](https://www.python.org/downloads/) et [Git](https://git-scm.com/download/win).

```powershell
git clone https://github.com/valentin1628/claude-win-tracker.git
cd claude-win-tracker
py -3 -m venv .venv
.\.venv\Scripts\activate
python -m pip install -e .[dev]

python -m claude_tracker            # lance l'appli
python -m claude_tracker --demo     # avec de fausses données (badge DÉMO)
python -m claude_tracker --check    # diagnostic dans la console
pytest                              # tests
```

Si `activate` est refusé : `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### Construire l'installeur

```powershell
winget install JRSoftware.InnoSetup   # une seule fois
.\build.ps1                           # -> dist\ClaudeTracker-<version>-Setup.exe
```

### Publier une version

1. Change `__version__` dans `src/claude_tracker/__init__.py`.
2. Fusionne dans `main`.

GitHub Actions lance les tests, construit l'installeur sur Windows et publie la release. Les applis installées la proposent ensuite toutes seules. Sur une pull request, l'installeur est construit sans être publié : il est disponible dans les artefacts du build.

</details>

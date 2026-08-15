# Context Hub

Context Hub centralise les **raccourcis et métadonnées** de Gmail, Google Chat, Google Drive, Google Calendar et Odoo autour de contextes métier. Les emails, fichiers, messages, événements et fiches CRM restent dans leurs applications d’origine.

L’expérience repose sur trois surfaces complémentaires :

- l’interface web du Hub, dédiée à la recherche et au CRUD des contextes ainsi qu’à la configuration des connexions ;
- un Chromium Docker affiché dans le Hub, pour utiliser les applications sans quitter Context Hub ;
- une extension Chrome/Edge qui affiche Context Hub dans un panneau latéral à côté des interfaces officielles de Gmail, Chat, Drive, Calendar et Odoo.

Cette architecture conserve l’expérience complète et la session de chaque application. Gmail et les autres applications Google ne peuvent pas être intégrés de manière fiable dans une `iframe` classique à cause de leurs règles de sécurité et d’authentification ; le navigateur Docker diffuse donc une vraie session Chromium dans la page.

## Lancement avec Docker Desktop

Prérequis : Docker Desktop en cours d’exécution.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Ouvrir ensuite [http://localhost:8080](http://localhost:8080). Le premier lancement charge un jeu de démonstration si `DEMO_MODE=true`.

Commandes utiles :

```powershell
docker compose ps
docker compose logs -f app
docker compose down
```

La base est conservée dans le volume Docker `context-hub_context_hub_data`. La commande `docker compose down -v` supprime volontairement et définitivement ces données.

### Inspection TLS locale

Si la construction échoue avec `CERTIFICATE_VERIFY_FAILED`, un antivirus ou proxy inspecte probablement TLS. Exporter son autorité racine publique au format PEM dans `certs/` avec l’extension `.crt`, puis relancer `docker compose up --build`. Les images de l’API et de Chromium ajoutent ces certificats à leurs magasins de confiance. Les certificats locaux sont ignorés par Git et ne doivent jamais contenir de clé privée.

## Utilisation

### Contextes

La page principale permet de :

- créer, lire, modifier et supprimer un contexte ;
- rechercher et filtrer les contextes ;
- supprimer directement une ligne, ou sélectionner plusieurs contextes pour les supprimer ensemble ;
- rattacher ou retirer un raccourci vers une ressource source ;
- ouvrir la ressource dans le navigateur intégré ou, au choix, dans le mode extension.

Une référence contient uniquement la source, l’identifiant stable, le lien profond, le titre et quelques métadonnées. Le contenu complet n’est pas recopié.

### Navigateur intégré Docker

Par défaut, les boutons Gmail, Chat, Drive, Calendar et Odoo ouvrent désormais un Chromium exécuté dans le conteneur `chromium` et rendu directement dans l’interface Context Hub. Une colonne de contextualisation reste visible à droite pour rechercher un contexte, en créer un et rattacher la page affichée. La détection de la page courante est actualisée automatiquement.

Le profil Chromium est conservé dans le volume `context-hub_context_browser_data`. La première ouverture demande donc de se connecter à Google et Odoo dans ce navigateur, indépendamment de la session Chrome/Edge locale. Le premier démarrage télécharge également l’image Chromium et peut prendre plusieurs minutes.

En local, le flux graphique est publié uniquement sur `127.0.0.1:3000`. Sur un VPS, Caddy le publie sous `/browser/` sur le même domaine ; il faut impérativement protéger le domaine complet par le SSO avant d’y enregistrer une session Google ou Odoo.

### Applications natives et extension

1. Depuis **Paramètres**, télécharger `context-hub-browser-extension.zip`.
2. Décompresser l’archive.
3. Ouvrir `chrome://extensions` ou `edge://extensions` et activer le mode développeur.
4. Choisir **Charger l’extension non empaquetée** puis le dossier `browser-extension` extrait.
5. Ouvrir l’icône Context Hub et épingler le panneau latéral.
6. Dans les réglages du panneau, vérifier l’URL du Hub et renseigner l’URL Odoo.

Le bouton **Mode extension** de la vue intégrée conserve l’expérience locale : Gmail, Chat, Drive, Calendar ou Odoo s’ouvrent dans l’onglet Chrome/Edge avec le panneau Context Hub. Le panneau permet de rechercher et sélectionner un contexte existant, ou d’en créer un qui sera immédiatement rattaché à l’élément affiché. Un bouton flottant **Rattacher au contexte** est aussi injecté dans les applications autorisées.

Après une mise à jour de l’extension non empaquetée, remplacer le dossier extrait puis cliquer sur **Actualiser** dans `chrome://extensions`. La page du Hub doit afficher `Active · v0.4.0`.

L’installation d’une extension non empaquetée est adaptée au développement et aux tests. Pour une organisation, publier l’extension de façon privée via Chrome Enterprise ou Microsoft Edge Add-ons.

## Connexions dans Paramètres

Les secrets sont chiffrés en base avec `APP_SECRET_KEY`. Ils ne sont jamais renvoyés par l’API après enregistrement.

### Google Workspace

1. Dans Google Cloud, créer ou choisir un projet.
2. Activer les API Gmail, Google Drive, Google Calendar et Google Chat.
3. Configurer l’écran de consentement OAuth. Pour un Google Workspace d’entreprise, choisir une application interne lorsque cela convient à l’organisation.
4. Créer un client OAuth de type **Application Web**.
5. Ajouter l’URI de redirection affichée dans **Paramètres → Google Workspace**. En local, elle vaut par défaut `http://localhost:8080/api/v1/connectors/google/callback`.
6. Copier le Client ID et le Client secret dans le formulaire, enregistrer, puis cliquer sur **Connecter Google**.
7. Autoriser la fenêtre OAuth, puis lancer une synchronisation pour vérifier les accès.

Le connecteur demande des accès en lecture aux fils Gmail, métadonnées Drive, événements Calendar et espaces Chat. Certains scopes peuvent exiger une validation Google pour une application externe.

### Odoo

Créer de préférence une clé API dédiée dans Odoo, puis renseigner :

- l’URL racine de l’instance ;
- le nom technique de la base ;
- l’identifiant utilisateur ;
- la clé API.

Le bouton **Tester et enregistrer** valide immédiatement l’authentification XML-RPC. La synchronisation récupère uniquement des compteurs de contacts, opportunités et projets ; les fiches restent dans Odoo.

## Configuration

Les variables sont documentées dans [`.env.example`](./.env.example).

| Variable | Rôle |
|---|---|
| `CONTEXT_HUB_PORT` | Port exposé sur l’hôte, `8080` par défaut |
| `APP_PUBLIC_URL` | URL absolue utilisée par OAuth, les liens et les intégrations |
| `POSTGRES_PASSWORD` | Mot de passe PostgreSQL |
| `APP_SECRET_KEY` | Clé stable d’au moins 32 caractères pour chiffrer les identifiants |
| `EMBEDDED_BROWSER_ENABLED` | Active le navigateur Chromium intégré |
| `EMBEDDED_BROWSER_PUBLIC_URL` | URL chargée dans la vue intégrée |
| `CONTEXT_BROWSER_PORT` | Port local de l’interface Chromium, `3000` par défaut |
| `CONTEXT_BROWSER_USER` | Utilisateur HTTP facultatif du navigateur |
| `CONTEXT_BROWSER_PASSWORD` | Mot de passe HTTP facultatif ; laisser vide derrière le SSO |
| `DEMO_MODE` | Charge les exemples lorsque la base est vide |
| `CORS_ORIGINS` | Origines web autorisées, séparées par des virgules |
| `INTEGRATION_API_KEY` | Protège les API entrantes génériques et Odoo |
| `ODOO_WEBHOOK_SECRET` | Vérifie les webhooks Odoo en HMAC SHA-256 |

Ne plus changer `APP_SECRET_KEY` après avoir configuré des connecteurs, sinon leurs secrets ne pourront plus être déchiffrés.

API et diagnostic :

- OpenAPI : [http://localhost:8080/docs](http://localhost:8080/docs)
- Santé : [http://localhost:8080/health](http://localhost:8080/health)

## Intégrations complémentaires

Le dépôt conserve aussi :

- un runtime HTTP Google Workspace dans `integrations/google-workspace` ;
- une application Google Chat via `/integrations/google-chat/events` ;
- le module Odoo 17 `integrations/odoo/context_hub_bridge`.

Ces composants peuvent être déployés de manière administrée dans l’organisation. L’extension navigateur constitue le chemin le plus direct pour obtenir le panneau transversal tout en gardant les interfaces natives.

## Déploiement sur un VPS

Pointer le DNS du domaine vers le VPS, puis configurer `.env` :

```dotenv
CONTEXT_HUB_DOMAIN=context.example.com
CONTEXT_HUB_PORT=127.0.0.1:8080
APP_PUBLIC_URL=https://context.example.com
POSTGRES_PASSWORD=un-secret-long-et-aleatoire
APP_SECRET_KEY=une-cle-de-chiffrement-stable-et-tres-longue
DEMO_MODE=false
CORS_ORIGINS=https://context.example.com
INTEGRATION_API_KEY=une-cle-longue-et-aleatoire
ODOO_WEBHOOK_SECRET=un-autre-secret-long
```

Lancer la pile avec HTTPS automatique :

```bash
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
```

Caddy obtient et renouvelle le certificat TLS. Pour déplacer le Hub : sauvegarder PostgreSQL, copier le dépôt et `.env`, restaurer la base, puis relancer Compose.

```bash
docker compose exec -T db pg_dump -U context_hub context_hub > context-hub-backup.sql
```

Mettre ensuite l’URL HTTPS du VPS dans les réglages de l’extension et accorder l’accès à cette origine lorsqu’elle le demande.

## Sécurité avant production

Le MVP n’intègre pas encore de fournisseur d’identité propre au Hub. Avant une exposition métier :

- placer l’interface et l’API derrière le SSO/OIDC de l’organisation ;
- protéger également `/browser/`, car le volume Chromium contient des cookies et sessions applicatives ;
- utiliser des secrets uniques et gérer leur rotation avec une procédure de reconnexion ;
- réserver l’application OAuth Google aux utilisateurs autorisés et limiter ses scopes ;
- ne jamais exposer le port PostgreSQL ;
- désactiver `DEMO_MODE`, sauvegarder les volumes et centraliser les journaux ;
- utiliser un compte Odoo à privilèges minimaux et une clé API dédiée.

La conception détaillée figure dans [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md).

## Développement et tests

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest -q
ruff check app tests
node --check app/static/assets/app.js
node --check browser-extension/sidepanel.js
```

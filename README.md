# Context Hub

Context Hub est une couche de contextualisation transverse pour Gmail, Google Chat, Google Drive, Google Calendar et Odoo. Un contexte métier regroupe des **références persistantes** vers les ressources sources, ainsi que les quelques métadonnées nécessaires pour les retrouver. Les messages, fichiers, événements et fiches CRM restent hébergés dans leurs outils d’origine.

Le dépôt contient un MVP complet :

- une interface web responsive pour chercher, créer et parcourir les contextes ;
- une API REST documentée automatiquement ;
- un panneau Google Workspace en runtime HTTP pour Gmail, Drive et Calendar ;
- une application Google Chat qui recherche les contextes depuis une conversation ;
- un module Odoo 17 avec bouton intelligent sur contacts, opportunités, projets et tâches ;
- une base PostgreSQL et un déploiement entièrement Dockerisé ;
- une configuration VPS avec HTTPS automatique via Caddy.

## Lancement avec Docker Desktop

Prérequis : Docker Desktop en cours d’exécution.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Ouvrir ensuite [http://localhost:8080](http://localhost:8080). Le premier lancement charge un jeu de démonstration qui illustre les cinq sources.

Pour arrêter l’application :

```powershell
docker compose down
```

La base est conservée dans le volume Docker `context-hub_context_hub_data`. Pour repartir volontairement de zéro, exécuter `docker compose down -v` — cette commande supprime définitivement les données du Hub.

## Utilisation

1. Créer un contexte pour un client, projet, sujet, opportunité ou activité.
2. Ouvrir le contexte et choisir **Lier une ressource**.
3. Coller le lien permanent de la ressource et son identifiant source.
4. Retrouver ensuite le contexte depuis l’interface, une recherche, Workspace, Chat ou Odoo.

Le rattachement mémorise le titre, l’URL, l’identifiant source, le type, une note facultative et des métadonnées techniques. Il ne télécharge ni le corps d’un email, ni un fichier Drive, ni le contenu d’un espace Chat.

API et diagnostic :

- OpenAPI : [http://localhost:8080/docs](http://localhost:8080/docs)
- Santé : [http://localhost:8080/health](http://localhost:8080/health)

## Configuration

Les variables disponibles sont documentées dans [`.env.example`](./.env.example).

| Variable | Rôle |
|---|---|
| `CONTEXT_HUB_PORT` | Port exposé sur l’hôte, `8080` par défaut |
| `APP_PUBLIC_URL` | URL absolue utilisée par les liens profonds et intégrations |
| `POSTGRES_PASSWORD` | Mot de passe PostgreSQL |
| `DEMO_MODE` | Charge les exemples lorsque la base est vide |
| `CORS_ORIGINS` | Origines web autorisées, séparées par des virgules |
| `INTEGRATION_API_KEY` | Protège les API entrantes génériques et Odoo |
| `ODOO_WEBHOOK_SECRET` | Vérifie les webhooks Odoo en HMAC SHA-256 |

## Google Workspace : Gmail, Drive et Calendar

Le fichier [`integrations/google-workspace/deployment.example.json`](./integrations/google-workspace/deployment.example.json) déclare :

- la page d’accueil du panneau latéral ;
- le déclencheur contextuel d’un message Gmail ;
- le déclencheur d’une sélection Drive ;
- le déclencheur d’ouverture d’un événement Calendar.

Déploiement :

1. Publier Context Hub sur une URL HTTPS.
2. Remplacer `YOUR_CONTEXT_HUB_DOMAIN` dans le manifeste.
3. Activer le Google Workspace Marketplace SDK dans un projet Google Cloud.
4. Créer un **HTTP deployment** avec le contenu du manifeste, ou utiliser `gcloud workspace-add-ons deployments create`.
5. Installer le déploiement en mode test, puis autoriser les scopes demandés.

Les endpoints concernés sont `/integrations/workspace/home`, `/integrations/workspace/contextual` et `/integrations/workspace/attach`.

> Avant une diffusion à l’échelle de l’organisation, valider `authorizationEventObject.systemIdToken` au niveau de la passerelle ou de l’application et terminer la revue OAuth Google.

## Google Chat

Dans la configuration de l’API Google Chat du projet Cloud :

1. activer les fonctionnalités interactives ;
2. sélectionner **HTTP endpoint URL** ;
3. renseigner `https://VOTRE_DOMAINE/integrations/google-chat/events` ;
4. rendre l’application visible au groupe pilote ;
5. ajouter si souhaité une commande `context`.

Dans Chat, `context Helios` recherche et retourne jusqu’à cinq cartes ouvrant les contextes correspondants.

## Odoo

Le module [`context_hub_bridge`](./integrations/odoo/context_hub_bridge) cible Odoo 17.

1. Copier son dossier dans un chemin `addons` d’Odoo.
2. Redémarrer Odoo, actualiser la liste des applications puis installer **Context Hub Bridge**.
3. Dans **Paramètres généraux → Context Hub**, renseigner l’URL HTTPS du Hub.
4. Utiliser le bouton **Context Hub** sur un contact, une opportunité, un projet ou une tâche.

Si la fiche est déjà liée, le contexte s’ouvre immédiatement. Sinon, le Hub propose une création préremplie et rattache automatiquement la fiche Odoo au nouveau contexte.

Pour rattacher une fiche par API, envoyer un `POST /integrations/odoo/reference` avec `context_id`, `external_id` au format `modèle:id`, `title`, `url` et `resource_type`. Si les secrets sont activés, ajouter `X-Context-Hub-Key` et `X-Context-Hub-Signature: sha256=<HMAC_DU_CORPS>`.

## Déploiement sur un VPS

Pointer d’abord le DNS du domaine vers le VPS, puis configurer `.env` :

```dotenv
CONTEXT_HUB_DOMAIN=context.example.com
CONTEXT_HUB_PORT=127.0.0.1:8080
APP_PUBLIC_URL=https://context.example.com
POSTGRES_PASSWORD=un-secret-long-et-aleatoire
DEMO_MODE=false
CORS_ORIGINS=https://context.example.com
INTEGRATION_API_KEY=une-cle-longue-et-aleatoire
ODOO_WEBHOOK_SECRET=un-autre-secret-long
```

Lancer la pile avec le proxy HTTPS :

```bash
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
```

Caddy obtient et renouvelle automatiquement le certificat TLS. Les données restent dans des volumes Docker, ce qui rend le déplacement vers un autre serveur prévisible : sauvegarder la base, copier le dépôt et `.env`, restaurer la base, puis relancer Compose.

Sauvegarde PostgreSQL :

```bash
docker compose exec -T db pg_dump -U context_hub context_hub > context-hub-backup.sql
```

## Sécurité avant production

Le MVP est volontairement sans fournisseur d’identité afin de fonctionner immédiatement en local. Avant d’exposer des données métier :

- placer l’interface et l’API derrière le SSO/OIDC de l’organisation (oauth2-proxy, Cloudflare Access, Traefik ForwardAuth, etc.) ;
- valider les jetons d’identité signés des appels Google Workspace et Google Chat ;
- définir les trois secrets de `.env` et les faire tourner régulièrement ;
- limiter l’accès réseau à PostgreSQL — le Compose ne publie déjà aucun port de base ;
- désactiver `DEMO_MODE`, sauvegarder le volume et centraliser les journaux ;
- n’accorder que les scopes OAuth Google strictement nécessaires.

La conception détaillée et les choix d’évolution figurent dans [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md).

## Développement et tests

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest -q
ruff check app tests
```

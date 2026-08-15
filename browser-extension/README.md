# Extension navigateur Context Hub

Cette extension Manifest V3 transforme un onglet Chrome/Edge en espace de travail Context Hub. Gmail, Chat, Drive, Calendar et Odoo remplacent le contenu principal du même onglet, tandis que le panneau latéral Context Hub reste affiché et utilise la session déjà ouverte dans le navigateur.

## Installation locale

1. Ouvrir `chrome://extensions` ou `edge://extensions`.
2. Activer le mode développeur.
3. Cliquer sur **Charger l’extension non empaquetée**.
4. Sélectionner ce dossier `browser-extension`.
5. Cliquer sur l’icône Context Hub, puis épingler le panneau si nécessaire.
6. Dans les paramètres du panneau, saisir l’URL du Hub et l’URL Odoo.

Si une ancienne version est déjà installée, remplacer son dossier, cliquer sur **Actualiser** dans la fiche de l’extension, puis recharger Context Hub. L’état de la barre latérale doit indiquer `Active · v0.4.0`.

Le bouton flottant **Rattacher au contexte** est injecté uniquement dans les applications Google déclarées et dans l’origine Odoo explicitement autorisée par l’utilisateur. Le panneau permet soit de rechercher et choisir un contexte, soit d’en créer un ; dans ce second cas, la ressource courante est rattachée automatiquement.

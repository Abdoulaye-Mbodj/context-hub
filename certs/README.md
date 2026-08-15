# Autorités locales

Déposer ici, au format PEM avec l’extension `.crt`, toute autorité racine requise par un proxy HTTPS ou un antivirus avec inspection TLS.

Les fichiers `.crt` sont copiés dans les images pendant la construction, ajoutés au bundle Linux et au magasin NSS de Chromium, et ignorés par Git. Ne jamais placer de clé privée dans ce dossier.

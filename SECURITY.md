# Sécurité

## Ce que ce service est, et pour qui

L'Atelier est conçu pour **un pod, un utilisateur**. Il n'y a qu'une identité
propriétaire, et elle ouvre tout.

Ce n'est pas une limitation qu'on prévoit de lever au fil de l'eau : le harnais
lance `claude` avec `--permission-mode bypassPermissions`. Qui obtient un
identifiant valide obtient l'exécution de code arbitraire sur le pod, donc le
PVC, la clé du modèle, et tous les jetons amont enregistrés en base. Il n'existe
pas de « petit » accès à cette API.

Déployé pour plusieurs personnes, il faudrait que chacune ait sa propre
authentification, sans clé mutualisée derrière l'interface. **Rien dans le code
ne l'assure aujourd'hui.**

## Le modèle de menace, explicitement

| | |
|---|---|
| **Ce qui protège** | l'ingress authentifié d'Onyxia, et la clé propriétaire |
| **Ce qui ne protège pas** | l'adresse d'origine d'une requête — derrière un ingress, le service ne voit que celle du contrôleur |
| **Ce qu'un accès donne** | tout : exécution sur le pod, secrets, données |
| **Ce qui est assumé** | `bypassPermissions`, parce que l'utilisateur est le propriétaire du pod |

**Ne pas exposer ce service sans un ingress qui authentifie devant lui.**

## Où vivent les secrets

Hors du dépôt, dans `~/work/.secrets/` sur le pod, en 0600 :

- `atelier_owner_key` — la clé propriétaire, au porteur ;
- `atelier_internal_secret` — le secret partagé qui garde les appels annoncés
  comme internes ;
- `llm_api_key` — la clé de la passerelle de modèles ;
- `vscode_password` — le mot de passe code-server, enregistré par le pod.

Aucun de ces fichiers n'est versionné, et rien ne les écrit dans un dossier de
projet : un dossier de projet se partage et se versionne.

## Ce qui a été corrigé, et pourquoi le dire

Les commentaires du code qui expliquent *pourquoi* une garde existe sont de la
documentation de sécurité. Les raccourcir revient à perdre la raison d'être du
correctif.

- **`/v1/internal/vscode-password`** n'était gardé que par l'adresse d'origine.
  Mesuré depuis Internet, la garde laissait passer : derrière l'ingress, uvicorn
  voit l'adresse du contrôleur, dans une plage privée. Un secret partagé décide
  désormais.
- **Le cookie de navigation** portait la clé propriétaire elle-même, trente
  jours durant. Il porte un identifiant de session sans pouvoir propre, daté et
  révocable côté serveur.

## Ce qui reste ouvert

Suivi en issues sur le dépôt. Un projet public qui porte des issues de sécurité
ouvertes sur un service mono-utilisateur est un projet tenu, pas un projet
fautif.

- La clé propriétaire circule encore en paramètre d'URL pour le flux
  d'événements et le WebSocket : une URL traverse les journaux d'ingress,
  l'historique du navigateur et le `Referer`.
- Rien ne permet de faire tourner la clé propriétaire depuis l'interface.
- Le proxy `/vscode` retransmet les en-têtes du client, `Authorization` et
  `Cookie` compris, vers code-server. Même pod, risque faible, mais un proxy ne
  devrait pas faire cela.

## Signaler une faille

Par courriel à l'adresse de l'auteur du dépôt, plutôt qu'en issue publique s'il
s'agit d'un défaut exploitable. Ce projet est maintenu par une personne, sur son
temps ; il n'y a pas de délai de réponse garanti.

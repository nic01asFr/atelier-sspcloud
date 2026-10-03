# Arbitrage du GPU partagé : protocole commun

*Statut : spec à valider, destinée au courtier GPU de la Passerelle (`gpu_broker`)
et à ses clients : l'Atelier, le hub QGIS (GeoAI), ZEBRA, les sessions
Jupyter. Rédigée à partir de ce que l'Atelier appelle aujourd'hui
(`gpu_status`, `gpu_switch`, `gpu_release`) et de l'état observé du namespace le
03/10/2026. Ce qui n'a pas pu être vérifié dans le courtier est marqué **[à
vérifier]**.*

## 1. Le problème

Un namespace, **un seul GPU**, plusieurs demandeurs qui ne se connaissent pas :
les projets de l'Atelier, GeoAI, ZEBRA, les sessions Jupyter de la personne.
Chacun applique ses règles ; personne ne sait qui tient le GPU, depuis quand, ni
s'il s'en sert.

Constat du 03/10 : `proj-depth-models-jupyter-pytorch-gpu` (1/1) tient le GPU ;
`proj-depth-models-gpu-jupyter-pytorch-gpu` est à 0/1 depuis 46 h, en échec
permanent. Rien ne l'a remis à zéro, et rien ne dit qui l'a demandé.

Aujourd'hui l'Atelier borne ce qu'il peut (pods `proj-<projet>-gpu-…`, jamais
`preempt`), mais il n'est qu'un client parmi d'autres : le connecteur Onyxia
brut, lui, accepte tout.

## 2. Principes

1. **Un propriétaire écrit.** Tenir le GPU, c'est avoir un bail (*lease*) lisible
   par tous : qui, depuis quand, jusqu'à quand.
2. **Un bail expire.** Sans renouvellement, il tombe. Un demandeur mort ne tient
   pas le GPU indéfiniment.
3. **Préempter se demande, ne se prend pas.** On préempte par priorité, avec un
   préavis pendant lequel le détenteur peut sauvegarder. Jamais silencieusement.
4. **Un échec se compense.** Une demande qui n'aboutit pas ne laisse rien à 1
   réplique.
5. **Les modèles ne préemptent pas seuls.** Un agent (modèle) demande ; la
   préemption d'un détenteur de rang supérieur ou égal est un geste de la personne.
6. **Un seul endroit de vérité** : l'état est sur le cluster, pas dans la
   mémoire d'un client.

## 3. Identité

Un demandeur s'identifie par `owner = <service>:<projet>:<instance>` :

| Service | Exemple |
|---|---|
| Atelier | `atelier:depth-models:conv-9e743f1e` |
| GeoAI / hub QGIS | `qgis:geoai:job-4412` |
| ZEBRA | `zebra:zebra:run-0173` |
| Jupyter (la personne) | `jupyter:depth-models:session` |

`instance` permet de retrouver et de rendre ce qu'une conversation ou un travail
a pris, quand il se termine.

## 4. L'état : un bail par GPU

Écrit sur la ressource qui tient le GPU (annotations du StatefulSet, ou à défaut
une ConfigMap `gpu-lease`, **[à vérifier : où le courtier écrit aujourd'hui]**) :

```json
{
  "owner": "atelier:depth-models:conv-9e743f1e",
  "priority": "normal",
  "since": "2026-10-03T07:50:05Z",
  "expires": "2026-10-03T08:20:05Z",
  "workload": "proj-depth-models-gpu-jupyter-pytorch-gpu",
  "preempt_requested": null
}
```

`preempt_requested`, s'il est posé, vaut :

```json
{ "by": "qgis:geoai:job-4412", "priority": "high", "at": "…", "deadline": "…" }
```

## 5. Priorités

Quatre rangs, du plus fort au plus faible :

| Rang | Qui | Exemple |
|---|---|---|
| `person` | La personne, à la main | « Libérer » sur la page projet |
| `high` | Travail interactif attendu | Une session Jupyter utilisée, une analyse QGIS demandée |
| `normal` | Travail d'un agent ou d'un projet | `gpu_switch` d'un agent de l'Atelier |
| `batch` | Entretien, essais, préchauffage | Une routine de nuit |

Une demande de rang **strictement supérieur** peut demander la préemption d'un
bail ; de rang égal ou inférieur, elle attend ou échoue. `person` préempte tout.
**Les modèles ne peuvent émettre que `normal` et `batch`** : `high` et `person`
sont posés par le service ou l'interface, jamais par un argument d'outil.

## 5 bis. Opérations

Cinq outils, les mêmes pour tous les services (les trois premiers existent déjà ;
leurs paramètres actuels sont à reprendre **[à vérifier]**) :

| Outil | Rôle | Retour |
|---|---|---|
| `gpu_status` | Qui tient le GPU, depuis quand, jusqu'à quand, qui attend. | Le bail, la file, l'état du pod. |
| `gpu_acquire(owner, workload, priority, ttl_s, wait_s)` | Demander le GPU. Libre : accordé. Pris : `queued` (file) ou `preempt_requested` (voir §6). | `granted`, `queued`, `refused` + raison. |
| `gpu_renew(owner, ttl_s)` | Prolonger son bail. | Nouvelle échéance, ou `lost` si préempté. |
| `gpu_release(owner)` | Rendre le GPU. Idempotent. | `released`. |
| `gpu_yield(owner)` | Le détenteur répond à une préemption demandée : il a sauvegardé, il rend. | `released`. |

Un seul champ d'erreur lisible : `refused` dit pourquoi (`held_by`, `rank_too_low`,
`not_ready_in_time`).

## 6. Préemption coopérative

1. Le demandeur de rang supérieur appelle `gpu_acquire(priority=high, …)`. Le GPU
   est pris par un rang inférieur : le courtier pose `preempt_requested` avec une
   échéance (`deadline`, **30 s à 5 min** selon le rang du détenteur).
2. Le détenteur le voit par `gpu_renew` (qui rend `preempt_requested`) ou par
   `gpu_status`. Il sauvegarde, puis appelle `gpu_yield`.
3. Si le détenteur répond avant l'échéance : le GPU est transféré au demandeur.
4. Sinon, **à l'échéance**, le courtier arrête la charge (mise à 0 du
   StatefulSet) et transfère. Le détenteur découvre `lost` à son prochain
   `gpu_renew`.
5. La personne (`person`) peut forcer sans préavis : c'est le seul cas.

Le préavis donne le temps de sauvegarder un modèle ou un point de reprise ; c'est
ce qui fait la différence entre « préempter » et « tuer ».

## 7. Compensation des échecs

- Une demande `granted` dont le pod n'est pas prêt dans `ready_timeout_s` (défaut
  5 min) est **annulée** : StatefulSet à 0, bail rendu, réponse `refused:
  not_ready_in_time`.
- Un **réaper** (une fois par minute) rend tout bail expiré et remet à 0 tout
  StatefulSet GPU sans bail valide.
- `gpu_release` est idempotent et ne dépend pas de l'état du pod.

C'est ce qui aurait évité le `proj-depth-models-gpu-…` à 0/1 pendant 46 h.

## 8. Sécurité

- Le courtier **reçoit** l'`owner` et la `priority` du service appelant ; il ne
  les prend pas d'un argument fourni par un modèle. Chaque service les pose à
  partir de son propre contexte (l'Atelier : la conversation).
- `person` n'est accordé qu'à un appel dont le service atteste l'origine
  humaine (session d'interface).
- Le courtier garde un **journal** : chaque `acquire`, `renew`, `release`,
  `yield`, préemption, avec qui et pourquoi.
- Un service ne peut rendre ou renouveler que son propre bail (comparer `owner`).

## 9. Ce que chacun fait

### Le courtier (Passerelle)
Le bail, la file, la préemption coopérative, le réaper, le journal. Les outils du
§5 bis. Un module commun dans le SDK, importé par tous les clients plutôt que
copié.

### L'Atelier (client)
- Impose `owner = atelier:<projet>:<conversation>` et `priority ≤ normal` à tout
  appel d'un modèle, **Assistant compris** ; supprime `preempt` des arguments.
- Rend le GPU à la fin d'un lancement et au `SessionEnd`.
- Répond à `preempt_requested` par une carte « Le GPU est demandé ailleurs »
  et, dans un agent supervisé, par un message au lanceur.
- Affiche sur la page projet : libre / tenu par X depuis Y, et un « Libérer »
  réservé à la personne.
- Journalise chaque appel avec la conversation.

### GeoAI / hub QGIS, ZEBRA
Appellent `gpu_acquire` avec `priority=high` pour un travail demandé en direct,
`normal` sinon. Renouvellent tant qu'ils travaillent, rendent à la fin,
répondent à `preempt_requested` en sauvegardant puis en appelant `gpu_yield`.

### Les sessions Jupyter de la personne
Un petit crochet de démarrage et d'arrêt de la session prend et rend le bail
(`jupyter:<projet>:session`, `high`). C'est ce qui rend visible la session qui
tient le GPU aujourd'hui.

## 10. Migration

1. Le courtier ajoute le bail et le réaper, et reste compatible avec les
   appels actuels (`gpu_switch` ≈ `gpu_acquire(normal)`).
2. Les clients passent à `owner`/`priority`.
3. `gpu_switch` avec `preempt: true` est retiré pour les modèles.
4. Les sessions Jupyter prennent leur bail.

## 11. Mesures à faire pour valider

- Deux demandes simultanées : une seule `granted`, l'autre `queued`.
- Une demande qui n'aboutit pas : StatefulSet à 0, bail rendu.
- Un détenteur mort (sans renouvellement) : bail repris à l'échéance.
- Une préemption `high` sur `normal` : préavis puis transfert ; le détenteur voit
  `lost`.
- Un modèle qui passe `priority=high` en argument : refusé.

## 12. Questions ouvertes

- **Où le courtier écrit-il l'état aujourd'hui ?** **[à vérifier]** : annotation,
  ConfigMap, ou rien.
- **Que fait `gpu_switch` quand le GPU est pris ?** **[à vérifier]** : échec,
  attente, ou création d'un StatefulSet à 1 qui n'est jamais planifié (ce qu'on
  observe sur `proj-depth-models-gpu-…`).
- **Durées par défaut** du bail et du préavis : à ajuster à l'usage.
- **Une file ou un rejet** quand le GPU est pris par un rang égal ? Je propose
  une file courte (3) puis le rejet.

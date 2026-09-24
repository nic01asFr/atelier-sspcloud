{{- define "atelier.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "atelier.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "atelier.labels" -}}
helm.sh/chart: {{ include "atelier.name" . }}-{{ .Chart.Version }}
{{ include "atelier.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "atelier.selectorLabels" -}}
app.kubernetes.io/name: {{ include "atelier.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Le modèle de langage : Onyxia expose deux conventions pour la configuration
IA de l'utilisateur — `user.profile.aiAssistant.*` (historique, celle qui est
réellement alimentée) et `{{ ai.activeProvider.* }}` (récente). On prend la
première, la seconde en repli, et l'on retire les espaces de bord que le
formulaire du profil laisse passer.
*/}}
{{- define "atelier.llm.apiKey" -}}
{{- $legacy := .Values.llm.apiKey | default "" | trim -}}
{{- $recent := (.Values.llm.provider).apiKey | default "" | trim -}}
{{- default $recent $legacy -}}
{{- end }}

{{- define "atelier.llm.baseUrl" -}}
{{- $legacy := .Values.llm.baseUrl | default "" | trim -}}
{{- $recent := (.Values.llm.provider).apiBase | default "" | trim -}}
{{- default $recent $legacy | default "https://llm.lab.sspcloud.fr/api" -}}
{{- end }}

{{- define "atelier.llm.model" -}}
{{- $legacy := .Values.llm.model | default "" | trim -}}
{{- $recent := (.Values.llm.provider).selectedModel | default "" | trim -}}
{{- default $recent $legacy -}}
{{- end }}

{{/*
L'hôte des applications des projets : une seconde origine, pour qu'aucun
contenu produit par un agent ne s'exécute dans celle de l'Atelier. Valeur
`apps.hostname` si elle est donnée ; sinon le premier label de
`ingress.hostname` suivi de `-apps`, puis le reste du domaine :
user-<idep>-atelier.<domaine> donne user-<idep>-atelier-apps.<domaine>. Un
seul niveau sous le domaine, pour rester couvert par le certificat wildcard
de la classe d'Ingress `onyxia`.
*/}}
{{- define "atelier.appsHostname" -}}
{{- $explicite := (.Values.apps).hostname | default "" | trim -}}
{{- if $explicite -}}
{{- $explicite -}}
{{- else -}}
{{- $morceaux := splitn "." 2 (.Values.ingress.hostname | default "" | trim) -}}
{{- $label := printf "%s-apps" $morceaux._0 -}}
{{- if gt (len $label) 63 -}}
{{- fail (printf "apps.hostname : le label %q dépasse 63 caractères ; donnez apps.hostname" $label) -}}
{{- end -}}
{{- if $morceaux._1 -}}
{{- printf "%s.%s" $label $morceaux._1 -}}
{{- else if $morceaux._0 -}}
{{- $label -}}
{{- end -}}
{{- end -}}
{{- end }}

{{/*
Le second hôte n'existe que si l'Atelier est lui-même exposé : sans Ingress,
il n'y a pas d'origine à séparer, et « Ouvrir » reste grisé.
*/}}
{{- define "atelier.appsExposees" -}}
{{- if and (.Values.apps).enabled .Values.ingress.enabled (include "atelier.appsHostname" .) -}}1{{- end -}}
{{- end }}

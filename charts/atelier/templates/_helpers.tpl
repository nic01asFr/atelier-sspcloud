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

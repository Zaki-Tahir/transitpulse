{{- define "tp.name" -}}{{ .Release.Name }}{{- end }}

{{- define "tp.labels" -}}
app.kubernetes.io/part-of: transitpulse
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{- define "tp.selector" -}}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{- define "tp.apiImage" -}}
{{ .Values.images.api.repository }}:{{ .Values.images.api.tag | default .Chart.AppVersion }}
{{- end }}

{{- define "tp.webImage" -}}
{{ .Values.images.web.repository }}:{{ .Values.images.web.tag | default .Chart.AppVersion }}
{{- end }}

{{- define "tp.secretName" -}}
{{ .Values.database.existingSecret | default (printf "%s-connections" .Release.Name) }}
{{- end }}

{{/* Environment shared by every backend container. */}}
{{- define "tp.backendEnv" -}}
- name: TP_DATABASE_URL
  valueFrom: { secretKeyRef: { name: {{ include "tp.secretName" . }}, key: DATABASE_URL } }
- name: TP_REDIS_URL
  valueFrom: { secretKeyRef: { name: {{ include "tp.secretName" . }}, key: REDIS_URL } }
- name: TP_POLL_SECONDS
  value: {{ .Values.config.pollSeconds | quote }}
{{- with .Values.config.feedUrls }}
- name: TP_FEED_URLS
  value: {{ toJson . | quote }}
{{- end }}
{{- if .Values.config.mtaApiKeySecret }}
- name: TP_MTA_API_KEY
  valueFrom: { secretKeyRef: { name: {{ .Values.config.mtaApiKeySecret }}, key: MTA_API_KEY } }
{{- end }}
{{- end }}

{{- define "tp.podSecurity" -}}
runAsNonRoot: true
runAsUser: 65534
seccompProfile: { type: RuntimeDefault }
{{- end }}

{{- define "tp.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities: { drop: [ALL] }
{{- end }}

{{/* Applies migrations before the app starts. Safe in every pod: an advisory lock serialises them. */}}
{{- define "tp.migrateInit" -}}
- name: migrate
  image: {{ include "tp.apiImage" . }}
  imagePullPolicy: {{ .Values.images.pullPolicy }}
  command: ["python", "-m", "transitpulse.migrate"]
  env: {{- include "tp.backendEnv" . | nindent 4 }}
  securityContext: {{- include "tp.containerSecurity" . | nindent 4 }}
{{- end }}

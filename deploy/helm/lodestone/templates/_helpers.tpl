{{- define "lodestone.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- define "lodestone.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end -}}
{{- define "lodestone.selector" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
{{- define "lodestone.secretName" -}}
{{- default (include "lodestone.fullname" .) .Values.existingSecret -}}
{{- end -}}
{{- define "lodestone.image" -}}
{{ .Values.image.repository }}:{{ default .Chart.AppVersion .Values.image.tag }}
{{- end -}}
{{- define "lodestone.env" -}}
- name: LODESTONE_SECRET_KEY
  valueFrom: {secretKeyRef: {name: {{ include "lodestone.secretName" . }}, key: secret-key}}
- name: LODESTONE_DATABASE_URL
  valueFrom: {secretKeyRef: {name: {{ include "lodestone.secretName" . }}, key: database-url}}
- name: LODESTONE_LDAP_BIND_PASSWORD
  valueFrom: {secretKeyRef: {name: {{ include "lodestone.secretName" . }}, key: ldap-bind-password, optional: true}}
- name: LODESTONE_ADMIN_PASSWORD
  valueFrom: {secretKeyRef: {name: {{ include "lodestone.secretName" . }}, key: admin-password, optional: true}}
- name: LODESTONE_OIDC_CLIENT_SECRET
  valueFrom: {secretKeyRef: {name: {{ include "lodestone.secretName" . }}, key: oidc-client-secret, optional: true}}
- name: LODESTONE_SMTP_PASSWORD
  valueFrom: {secretKeyRef: {name: {{ include "lodestone.secretName" . }}, key: smtp-password, optional: true}}
- name: LODESTONE_ENCRYPTION_KEY
  valueFrom: {secretKeyRef: {name: {{ include "lodestone.secretName" . }}, key: encryption-key, optional: true}}
- name: LODESTONE_SETUP_TOKEN
  valueFrom: {secretKeyRef: {name: {{ include "lodestone.secretName" . }}, key: setup-token, optional: true}}
{{- end -}}
{{- define "lodestone.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities: {drop: ["ALL"]}
{{- end -}}

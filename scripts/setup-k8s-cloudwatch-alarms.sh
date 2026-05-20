#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# setup-k8s-cloudwatch-alarms.sh
#
# Creates:
#   1. CloudWatch Logs metric filters (detect CrashLoopBackOff, OOMKilled, Pending)
#   2. CloudWatch Custom Metrics published by a Kubernetes CronJob
#      (kube-state-metrics values → CloudWatch every 60s)
#   3. CloudWatch Alarms (trigger when pod is in bad state > 2 min)
#   4. SNS Topic + subscription to your Lambda forwarder
#
# Prerequisites:
#   - AWS CLI configured with permissions for CloudWatch, SNS, Lambda
#   - FluentBit deployed (logs flowing to /eks/otel-demo log group)
#   - Lambda function deployed (see lambda_code/k8s_pod_alert_forwarder.py)
#
# Usage:
#   export CLUSTER_NAME="my-eks-cluster"
#   export REGION="ap-south-1"
#   export INFRAAI_WEBHOOK_URL="http://<your-lb>/api/alerts/webhook"
#   export LAMBDA_ARN="arn:aws:lambda:REGION:ACCOUNT:function:k8s-pod-alert-forwarder"
#   bash scripts/setup-k8s-cloudwatch-alarms.sh
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-my-eks-cluster}"
REGION="${REGION:-ap-south-1}"
LAMBDA_ARN="${LAMBDA_ARN:?Please export LAMBDA_ARN}"
LOG_GROUP="/eks/otel-demo"
NAMESPACE_FILTER="otel-demo"

echo "=== Setting up CloudWatch Alarms for K8s pod health ==="
echo "    Cluster : $CLUSTER_NAME"
echo "    Region  : $REGION"
echo "    LogGroup: $LOG_GROUP"

# ── 1. SNS Topic ──────────────────────────────────────────────────────────────
echo ""
echo "[1/5] Creating SNS topic..."
TOPIC_ARN=$(aws sns create-topic \
  --name "k8s-pod-alert-${CLUSTER_NAME}" \
  --region "$REGION" \
  --query TopicArn --output text)
echo "      SNS Topic: $TOPIC_ARN"

# Subscribe Lambda to the SNS topic
aws sns subscribe \
  --topic-arn "$TOPIC_ARN" \
  --protocol lambda \
  --notification-endpoint "$LAMBDA_ARN" \
  --region "$REGION" > /dev/null

# Allow SNS to invoke the Lambda
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws lambda add-permission \
  --function-name "$LAMBDA_ARN" \
  --statement-id "sns-k8s-pod-alert-$(date +%s)" \
  --action "lambda:InvokeFunction" \
  --principal sns.amazonaws.com \
  --source-arn "$TOPIC_ARN" \
  --region "$REGION" 2>/dev/null || true

echo "      Lambda subscribed to SNS."

# ── 2. Metric Filter: CrashLoopBackOff ───────────────────────────────────────
echo ""
echo "[2/5] Creating metric filter for CrashLoopBackOff..."

# Fluent Bit enriches logs with kubernetes.pod_name etc.
# The container runtime logs "Back-off restarting failed container" when crashing.
aws logs put-metric-filter \
  --log-group-name "$LOG_GROUP" \
  --filter-name "k8s-CrashLoopBackOff-${CLUSTER_NAME}" \
  --filter-pattern '"Back-off restarting failed container" || "CrashLoopBackOff"' \
  --metric-transformations \
    metricName="PodCrashLoopBackOff",metricNamespace="InfraAI/Kubernetes/${CLUSTER_NAME}",metricValue=1,unit=Count,defaultValue=0 \
  --region "$REGION"

echo "      CrashLoopBackOff metric filter created."

# ── 3. Metric Filter: OOMKilled ───────────────────────────────────────────────
echo ""
echo "[3/5] Creating metric filter for OOMKilled..."
aws logs put-metric-filter \
  --log-group-name "$LOG_GROUP" \
  --filter-name "k8s-OOMKilled-${CLUSTER_NAME}" \
  --filter-pattern '"OOMKilled" || "out of memory" || "Killed process"' \
  --metric-transformations \
    metricName="PodOOMKilled",metricNamespace="InfraAI/Kubernetes/${CLUSTER_NAME}",metricValue=1,unit=Count,defaultValue=0 \
  --region "$REGION"

echo "      OOMKilled metric filter created."

# ── 4. CloudWatch Alarm: CrashLoopBackOff (any occurrence in 2-min window) ───
echo ""
echo "[4/5] Creating CloudWatch Alarms..."

# CrashLoopBackOff alarm
aws cloudwatch put-metric-alarm \
  --alarm-name "k8s-PodCrashLoopBackOff-${CLUSTER_NAME}" \
  --alarm-description "One or more pods in otel-demo are CrashLoopBackOff on cluster ${CLUSTER_NAME}" \
  --metric-name "PodCrashLoopBackOff" \
  --namespace "InfraAI/Kubernetes/${CLUSTER_NAME}" \
  --statistic Sum \
  --period 60 \
  --evaluation-periods 2 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$TOPIC_ARN" \
  --ok-actions "$TOPIC_ARN" \
  --dimensions "Name=Namespace,Value=${NAMESPACE_FILTER}" \
  --region "$REGION"

echo "      CrashLoopBackOff alarm created (fires after 2 consecutive 1-min periods)."

# OOMKilled alarm
aws cloudwatch put-metric-alarm \
  --alarm-name "k8s-PodOOMKilled-${CLUSTER_NAME}" \
  --alarm-description "One or more pods in otel-demo were OOMKilled on cluster ${CLUSTER_NAME}" \
  --metric-name "PodOOMKilled" \
  --namespace "InfraAI/Kubernetes/${CLUSTER_NAME}" \
  --statistic Sum \
  --period 60 \
  --evaluation-periods 1 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$TOPIC_ARN" \
  --ok-actions "$TOPIC_ARN" \
  --region "$REGION"

echo "      OOMKilled alarm created."

# ── 5. Kubernetes CronJob: publish pod Pending count to CloudWatch ────────────
# Fluent Bit only collects log text; pod STATUS (Pending) is not a log line.
# This CronJob uses kubectl to query live pod states and publishes them as
# custom CloudWatch metrics every 60 seconds.
echo ""
echo "[5/5] Deploying pod-state-reporter CronJob..."

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: pod-state-reporter
  namespace: otel-demo
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: pod-state-reader
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: pod-state-reporter-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: pod-state-reader
subjects:
  - kind: ServiceAccount
    name: pod-state-reporter
    namespace: otel-demo
---
# CronJob runs every minute; publishes Pending + Failed pod counts to CloudWatch
# Requires: node IAM role or IRSA with cloudwatch:PutMetricData permission
apiVersion: batch/v1
kind: CronJob
metadata:
  name: pod-state-reporter
  namespace: otel-demo
spec:
  schedule: "* * * * *"       # every minute
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 1
  failedJobsHistoryLimit: 1
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: pod-state-reporter
          restartPolicy: Never
          containers:
            - name: reporter
              image: amazon/aws-cli:latest
              env:
                - name: REGION
                  value: "${REGION}"
                - name: CLUSTER_NAME
                  value: "${CLUSTER_NAME}"
              command: ["/bin/bash", "-c"]
              args:
                - |
                  set -e

                  # Count pods in each bad phase in otel-demo namespace
                  PENDING=\$(kubectl get pods -n otel-demo --no-headers 2>/dev/null \
                    | awk '\$3=="Pending"' | wc -l | tr -d ' ')
                  FAILED=\$(kubectl get pods -n otel-demo --no-headers 2>/dev/null \
                    | awk '\$3=="Failed"' | wc -l | tr -d ' ')
                  UNKNOWN=\$(kubectl get pods -n otel-demo --no-headers 2>/dev/null \
                    | awk '\$3=="Unknown"' | wc -l | tr -d ' ')

                  echo "Pending=\$PENDING Failed=\$FAILED Unknown=\$UNKNOWN"

                  # Publish to CloudWatch
                  aws cloudwatch put-metric-data \
                    --region "\$REGION" \
                    --namespace "InfraAI/Kubernetes/\$CLUSTER_NAME" \
                    --metric-data \
                      MetricName=PodPendingCount,Value="\$PENDING",Unit=Count,Dimensions=[{Name=Namespace,Value=otel-demo}] \
                    2>/dev/null || true

                  aws cloudwatch put-metric-data \
                    --region "\$REGION" \
                    --namespace "InfraAI/Kubernetes/\$CLUSTER_NAME" \
                    --metric-data \
                      MetricName=PodFailedCount,Value="\$FAILED",Unit=Count,Dimensions=[{Name=Namespace,Value=otel-demo}] \
                    2>/dev/null || true

              resources:
                requests:
                  cpu: 20m
                  memory: 32Mi
                limits:
                  cpu: 100m
                  memory: 64Mi
EOF

echo "      Pod-state reporter CronJob deployed."

# CloudWatch Alarm: pods stuck Pending for > 2 minutes
aws cloudwatch put-metric-alarm \
  --alarm-name "k8s-PodPendingTooLong-${CLUSTER_NAME}" \
  --alarm-description "Pods in otel-demo namespace have been Pending for more than 2 minutes on cluster ${CLUSTER_NAME}. Likely cause: insufficient cluster capacity (no autoscaler), image pull failure, or resource quota." \
  --metric-name "PodPendingCount" \
  --namespace "InfraAI/Kubernetes/${CLUSTER_NAME}" \
  --statistic Maximum \
  --period 60 \
  --evaluation-periods 2 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$TOPIC_ARN" \
  --ok-actions "$TOPIC_ARN" \
  --dimensions "Name=Namespace,Value=${NAMESPACE_FILTER}" \
  --region "$REGION"

aws cloudwatch put-metric-alarm \
  --alarm-name "k8s-PodFailed-${CLUSTER_NAME}" \
  --alarm-description "Pods in otel-demo namespace are in Failed state on cluster ${CLUSTER_NAME}." \
  --metric-name "PodFailedCount" \
  --namespace "InfraAI/Kubernetes/${CLUSTER_NAME}" \
  --statistic Maximum \
  --period 60 \
  --evaluation-periods 1 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$TOPIC_ARN" \
  --ok-actions "$TOPIC_ARN" \
  --dimensions "Name=Namespace,Value=${NAMESPACE_FILTER}" \
  --region "$REGION"

echo ""
echo "=== Done! ==="
echo ""
echo "Summary:"
echo "  SNS Topic          : $TOPIC_ARN"
echo "  Lambda subscribed  : $LAMBDA_ARN"
echo "  Alarms created:"
echo "    k8s-PodCrashLoopBackOff-${CLUSTER_NAME}   (CrashLoop detected in logs)"
echo "    k8s-PodOOMKilled-${CLUSTER_NAME}           (OOMKill detected in logs)"
echo "    k8s-PodPendingTooLong-${CLUSTER_NAME}      (pods Pending >= 2 min)"
echo "    k8s-PodFailed-${CLUSTER_NAME}              (pods in Failed state)"
echo ""
echo "Next steps:"
echo "  1. Deploy lambda_code/k8s_pod_alert_forwarder.py as a Lambda function"
echo "  2. Set INFRAAI_WEBHOOK_URL in Lambda env vars"
echo "  3. Set CLUSTER_NAME and KUBECONFIG_SECRET in Lambda env vars"
echo "  4. Add k8s_exec MCP config in InfraAI (Settings → MCP Servers)"

#!/usr/bin/env bash
# EC2 user-data: install Docker and set up the Detection service
set -euo pipefail

# Install Docker
dnf update -y
dnf install -y docker
systemctl enable --now docker

# Write a systemd service that pulls + runs the container on start
cat > /etc/systemd/system/mag10-detection.service <<'UNIT'
[Unit]
Description=MAG-10 Signal Detection
After=docker.service network-online.target
Requires=docker.service

[Service]
Restart=always
RestartSec=10
ExecStartPre=/bin/bash -c 'aws ecr get-login-password --region ${aws_region} | docker login --username AWS --password-stdin ${ecr_registry}'
ExecStartPre=-/usr/bin/docker pull ${detection_image}
ExecStart=/usr/bin/docker run --rm \
  --name mag10-detection \
  -e AWS_REGION=${aws_region} \
  -e KINESIS_STREAM_RAW_TRADES=${kinesis_raw_trades} \
  ${detection_image}
ExecStop=/usr/bin/docker stop mag10-detection

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable mag10-detection
systemctl start mag10-detection

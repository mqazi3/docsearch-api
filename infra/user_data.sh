#!/bin/bash
set -euxo pipefail

# The Elastic IP attaches a few seconds after boot. Until then there's no internet, so wait.
until curl -fsS --max-time 5 https://get.docker.com > /dev/null; do sleep 5; done

# 2 GB swap: headroom for Docker image builds on a 2 GB instance.
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Docker Engine + Compose + Buildx (Docker's official install script).
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# AWS CLI: the deploy script uses it to read secrets from Parameter Store.
snap install aws-cli --classic

# Application code.
git clone ${repo_url} /opt/docsearch

echo "DOCSEARCH BOOTSTRAP COMPLETE"

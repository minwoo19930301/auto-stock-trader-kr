#cloud-config
write_files:
  - path: /usr/local/bin/stock-broker-firstboot.sh
    permissions: "0755"
    owner: root:root
    content: |
      #!/bin/bash
      set -euxo pipefail

      APP_DIR="/opt/stock-broker-onboarding"
      TMP_BUNDLE="/tmp/stock-broker-onboarding.tar.gz"

      if command -v dnf >/dev/null 2>&1; then
        dnf install -y curl tar
      elif command -v apt-get >/dev/null 2>&1; then
        apt-get update
        apt-get install -y curl tar
      fi

      mkdir -p /opt
      chown __APP_USER__:__APP_USER__ /opt

      curl -fsSL "__BUNDLE_URL__" -o "${TMP_BUNDLE}"

      rm -rf "${APP_DIR}"
      mkdir -p "${APP_DIR}"
      tar -xzf "${TMP_BUNDLE}" -C "${APP_DIR}"
      chown -R __APP_USER__:__APP_USER__ "${APP_DIR}"

      cd "${APP_DIR}"
      chmod +x infra/oracle/scripts/bootstrap_oracle_ubuntu.sh
      APP_USER="__APP_USER__" APP_GROUP="__APP_USER__" SERVER_NAME="_" ./infra/oracle/scripts/bootstrap_oracle_ubuntu.sh 2>&1 | tee /var/log/stock-broker-bootstrap.log
runcmd:
  - [ bash, -lc, /usr/local/bin/stock-broker-firstboot.sh ]

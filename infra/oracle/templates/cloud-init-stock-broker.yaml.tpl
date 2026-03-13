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
      SERVICE_PATH="/etc/systemd/system/stock-broker-onboarding.service"
      SYNC_SCRIPT="/usr/local/bin/stock-broker-sync.sh"
      SYNC_SERVICE="/etc/systemd/system/stock-broker-sync.service"
      SYNC_TIMER="/etc/systemd/system/stock-broker-sync.timer"
      PORTS_SCRIPT="/usr/local/bin/stock-broker-open-ports.sh"
      PORTS_SERVICE="/etc/systemd/system/stock-broker-open-ports.service"
      CADDYFILE="/etc/caddy/Caddyfile"
      REPO_URL="__REPO_URL__"
      REPO_BRANCH="__REPO_BRANCH__"
      APP_DOMAIN_FROM_ENV="__APP_DOMAIN__"
      APP_USER="__APP_USER__"

      if ! id "${APP_USER}" >/dev/null 2>&1; then
        for candidate in ubuntu opc ec2-user; do
          if id "${candidate}" >/dev/null 2>&1; then
            APP_USER="${candidate}"
            break
          fi
        done
      fi

      export DEBIAN_FRONTEND=noninteractive
      apt-get update -y
      apt-get install -y curl ca-certificates tar python3 git caddy

      mkdir -p /opt
      chown "${APP_USER}:${APP_USER}" /opt

      curl -fsSL "__BUNDLE_URL__" -o "${TMP_BUNDLE}"

      rm -rf "${APP_DIR}"
      mkdir -p "${APP_DIR}"
      tar -xzf "${TMP_BUNDLE}" -C "${APP_DIR}"
      chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

      if [[ -d "${APP_DIR}/.git" ]]; then
        sudo -u "${APP_USER}" git -C "${APP_DIR}" remote set-url origin "${REPO_URL}" || true
        sudo -u "${APP_USER}" git -C "${APP_DIR}" fetch origin "${REPO_BRANCH}" || true
      fi

      cat > "${PORTS_SCRIPT}" <<'EOF'
      #!/bin/bash
      set -euo pipefail
      if command -v iptables >/dev/null 2>&1; then
        iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || iptables -I INPUT 4 -p tcp --dport 80 -j ACCEPT
        iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || iptables -I INPUT 5 -p tcp --dport 443 -j ACCEPT
      fi
      EOF
      chmod 0755 "${PORTS_SCRIPT}"

      cat > "${PORTS_SERVICE}" <<'EOF'
      [Unit]
      Description=Open HTTP/HTTPS ports for Stock Broker Onboarding
      After=network-online.target
      Wants=network-online.target

      [Service]
      Type=oneshot
      ExecStart=/usr/local/bin/stock-broker-open-ports.sh
      RemainAfterExit=yes

      [Install]
      WantedBy=multi-user.target
      EOF

      cat > "${SERVICE_PATH}" <<'EOF'
      [Unit]
      Description=Stock Broker Onboarding Static Server
      After=network-online.target
      Wants=network-online.target

      [Service]
      Type=simple
      WorkingDirectory=/opt/stock-broker-onboarding
      EnvironmentFile=-/etc/stock-broker-onboarding/app.env
      ExecStart=/usr/bin/env PORT=8080 python3 /opt/stock-broker-onboarding/server.py
      Restart=always
      RestartSec=2

      [Install]
      WantedBy=multi-user.target
      EOF

      cat > "${SYNC_SCRIPT}" <<EOF
      #!/bin/bash
      set -euo pipefail
      APP_DIR="/opt/stock-broker-onboarding"
      APP_USER="${APP_USER}"
      REPO_BRANCH="${REPO_BRANCH}"
      REPO_URL="${REPO_URL}"

      if [[ ! -d "\${APP_DIR}/.git" ]]; then
        exit 0
      fi

      sudo -u "\${APP_USER}" git -C "\${APP_DIR}" remote set-url origin "\${REPO_URL}" || true
      sudo -u "\${APP_USER}" git -C "\${APP_DIR}" fetch origin "\${REPO_BRANCH}"
      LOCAL_HEAD="\$(sudo -u "\${APP_USER}" git -C "\${APP_DIR}" rev-parse HEAD)"
      REMOTE_HEAD="\$(sudo -u "\${APP_USER}" git -C "\${APP_DIR}" rev-parse origin/\${REPO_BRANCH})"
      if [[ "\${LOCAL_HEAD}" != "\${REMOTE_HEAD}" ]]; then
        sudo -u "\${APP_USER}" git -C "\${APP_DIR}" pull --ff-only origin "\${REPO_BRANCH}"
        systemctl restart stock-broker-onboarding.service
      fi
      EOF
      chmod 0755 "${SYNC_SCRIPT}"

      cat > "${SYNC_SERVICE}" <<'EOF'
      [Unit]
      Description=Sync AUTO STOCK TRADER(KR) from GitHub
      After=network-online.target
      Wants=network-online.target

      [Service]
      Type=oneshot
      ExecStart=/usr/local/bin/stock-broker-sync.sh
      EOF

      cat > "${SYNC_TIMER}" <<'EOF'
      [Unit]
      Description=Run Git sync timer for AUTO STOCK TRADER(KR)

      [Timer]
      OnBootSec=2min
      OnUnitActiveSec=1min
      Unit=stock-broker-sync.service

      [Install]
      WantedBy=timers.target
      EOF

      PUBLIC_IP="$(curl -fsS -H "Authorization: Bearer Oracle" http://169.254.169.254/opc/v2/vnics/ | python3 -c 'import json,sys; d=json.load(sys.stdin); print((d[0].get("publicIp","") if d else ""))')"
      if [[ -z "${PUBLIC_IP}" ]]; then
        PUBLIC_IP="$(curl -fsS http://ifconfig.me || true)"
      fi
      APP_DOMAIN="${APP_DOMAIN_FROM_ENV}"
      if [[ -z "${APP_DOMAIN}" ]]; then
        APP_DOMAIN="${PUBLIC_IP}.sslip.io"
      fi
      mkdir -p /etc/stock-broker-onboarding
      echo "${APP_DOMAIN}" > /etc/stock-broker-onboarding/domain.txt
      if [[ ! -f /etc/stock-broker-onboarding/app.env ]]; then
        cat > /etc/stock-broker-onboarding/app.env <<EOF
      APP_BASE_URL=https://${APP_DOMAIN}
      EOF
      fi

      cat > "${CADDYFILE}" <<EOF
      ${APP_DOMAIN} {
        encode gzip
        reverse_proxy 127.0.0.1:8080
      }
      EOF

      systemctl daemon-reload
      systemctl enable stock-broker-open-ports.service
      systemctl restart stock-broker-open-ports.service
      systemctl enable stock-broker-onboarding.service
      systemctl restart stock-broker-onboarding.service
      systemctl enable stock-broker-sync.timer
      systemctl restart stock-broker-sync.timer
      systemctl enable caddy
      systemctl restart caddy

      if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
        firewall-cmd --permanent --add-service=http || true
        firewall-cmd --permanent --add-service=https || true
        firewall-cmd --reload || true
      fi
runcmd:
  - [ bash, -lc, /usr/local/bin/stock-broker-firstboot.sh ]
